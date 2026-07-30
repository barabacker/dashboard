"""Authoring form for a source (a site to crawl).

A source *is* a Config — see `control.models.Source`. What differs is how it is filled in: one
field per site attribute instead of a JSON object, with the choices and defaults read from the
collector's own schema so the form cannot drift from what enqueue will accept.

The fields are the union of the four tender schemas, and `clean()` keeps only the ones the
chosen engine actually declares. That is why a Config authored here always validates: the same
`resolve_parameters` that enqueue uses runs on the assembled dict before saving.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors import schemas
from collectors.schemas.tender import (
    DEFAULT_LISTING_PATHS,
    ENGINE_KEYS,
    available_certs,
    collector_key,
    engine_of,
)
from control.models import Source

#: Site attributes, in the order they are asked for. Every name is a parameter of at least one
#: tender schema; `_schema_params` decides which of them the chosen engine keeps.
PARAM_FIELDS = (
    "domain",
    "listing_path",
    "max_pages",
    "only_active",
    "concurrency",
    "fetch_details",
    "extra_ca_cert",
    "skip_tls_verify",
)


def _spec(engine: str, name: str):
    return schemas.get_collector(collector_key(engine)).param(name)


def _help(name: str, *, engine: str = "kendo") -> str:
    """The parameter's own description — the schema is the single source of that text."""
    for candidate in (engine, "fogsoft"):
        spec = _spec(candidate, name)
        if spec is not None:
            return spec.description
    return ""


class SourceForm(forms.ModelForm):
    collector_key = forms.ChoiceField(
        label="Движок",
        help_text="Семейство площадок, к которому относится сайт. От него зависит, "
        "как разбираются страницы.",
    )

    domain = forms.URLField(
        label="Домен",
        max_length=200,
        assume_scheme="https",
        help_text=_help("domain"),
    )
    listing_path = forms.CharField(
        label="Путь к листингу",
        max_length=200,
        required=False,
        help_text="Пусто — путь по умолчанию для выбранного движка: "
        + ", ".join(f"{engine} → {path}" for engine, path in DEFAULT_LISTING_PATHS.items()),
    )
    max_pages = forms.IntegerField(
        label="Максимум страниц",
        min_value=0,
        initial=0,
        help_text=_help("max_pages"),
    )
    only_active = forms.BooleanField(
        label="Только незавершённые торги",
        required=False,
        initial=True,
        help_text=_help("only_active"),
    )
    concurrency = forms.IntegerField(
        label="Параллельных запросов",
        min_value=1,
        max_value=16,
        initial=1,
        help_text=_help("concurrency"),
    )
    fetch_details = forms.BooleanField(
        label="Заходить в карточку лота",
        required=False,
        initial=True,
        help_text=_help("fetch_details", engine="fogsoft")
        + " Применимо только к движку iTender (Fogsoft); для остальных игнорируется.",
    )
    extra_ca_cert = forms.ChoiceField(
        label="Доп. сертификат",
        required=False,
        help_text=_help("extra_ca_cert"),
    )
    skip_tls_verify = forms.BooleanField(
        label="Не проверять сертификат",
        required=False,
        help_text=_help("skip_tls_verify"),
    )

    class Meta:
        model = Source
        fields = ["name", "collector_key", "enabled", "archived", "tags", "owner"]
        labels = {"name": "Название источника"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["collector_key"].choices = [
            (collector_key(engine), schemas.get_collector(collector_key(engine)).display_name)
            for engine in ENGINE_KEYS
        ]
        self.fields["extra_ca_cert"].choices = [("", "— обычный набор корневых —")] + [
            (name, name) for name in available_certs()
        ]

        # Fill the site fields from the stored parameters, so editing shows what is authored
        # rather than the form's defaults.
        parameters = getattr(self.instance, "parameters", None) or {}
        for name in PARAM_FIELDS:
            if name in parameters and parameters[name] is not None:
                self.fields[name].initial = parameters[name]

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        key = cleaned.get("collector_key")
        if not key:
            return cleaned

        parameters = self._collect_parameters(key, cleaned)
        try:
            schemas.resolve_parameters(key, parameters)
        except schemas.UnknownCollector:
            self.add_error("collector_key", f"Сборщика {key!r} нет в кодовой базе.")
            return cleaned
        except schemas.ParameterError as exc:
            for message in exc.errors:
                # Point at the field when the message names one; otherwise show it on the form.
                field = message.split(":", 1)[0]
                self.add_error(field if field in self.fields else None, message)
            return cleaned

        cleaned["parameters"] = parameters
        return cleaned

    def _collect_parameters(self, key: str, cleaned: dict[str, Any]) -> dict[str, Any]:
        """The form's site fields → the parameter dict this collector declares.

        Two things are dropped rather than stored: values for parameters the chosen engine does
        not declare (`fetch_details` outside fogsoft), and a blank `listing_path`, which means
        "whatever the engine's default is" — storing the resolved value would freeze today's
        default into every site.
        """
        engine = engine_of(key)
        parameters: dict[str, Any] = {}
        for name in PARAM_FIELDS:
            if _spec(engine, name) is None:
                continue
            value = cleaned.get(name)
            if name in {"listing_path", "extra_ca_cert"} and not value:
                continue
            parameters[name] = value
        return parameters

    def save(self, commit: bool = True) -> Source:
        source = super().save(commit=False)
        source.parameters = self.cleaned_data.get("parameters", source.parameters)
        if commit:
            source.save()
            self.save_m2m()
        return source
