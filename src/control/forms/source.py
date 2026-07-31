"""Authoring form for a source (a site to crawl).

A source *is* a Config — see `control.models.Config` and `CollectorDescriptor.is_source` (D22).
What differs from the raw `ConfigForm` is how it is filled in: one field per parameter instead of
a JSON object, built on the fly from the chosen collector's own `ParamSpec` list — so the field
set can never drift from what `enqueue` will accept, and a new source-like collector needs no new
Form class here to get a proper form.

`__init__` needs to know the collector *before* it can know the field set, so it reads
`collector_key` from wherever a request could have put it: POST data (final submission), initial
data (the second step of the add flow — see `ConfigAdmin.add_view` — or an existing instance
being edited), or the instance itself.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors import schemas
from control.models import Config

_FIELD_CLASSES: dict[str, type[forms.Field]] = {
    "str": forms.CharField,
    "int": forms.IntegerField,
    "float": forms.FloatField,
    "bool": forms.BooleanField,
    "list": forms.JSONField,
    "dict": forms.JSONField,
}


def _build_field(spec: schemas.ParamSpec) -> forms.Field:
    """One `ParamSpec` → one Django form field, typed and labelled from the spec alone."""
    kwargs: dict[str, Any] = {"label": spec.name, "help_text": spec.description}

    choices = spec.choices_provider() if spec.choices_provider else spec.choices
    if choices is not None:
        field_choices = [(value, value) for value in choices]
        if not spec.required:
            field_choices = [("", "—")] + field_choices
        return forms.ChoiceField(required=spec.required, choices=field_choices, **kwargs)

    if spec.kind == "bool":
        # An HTML checkbox has no way to be "required" in ParamSpec's sense — absence just
        # means False, which is exactly what an optional bool's `required=False` already gives.
        return forms.BooleanField(required=False, **kwargs)

    if spec.kind in {"int", "float"}:
        if spec.min_value is not None:
            kwargs["min_value"] = spec.min_value
        if spec.max_value is not None:
            kwargs["max_value"] = spec.max_value

    return _FIELD_CLASSES[spec.kind](required=spec.required, **kwargs)


class SourceForm(forms.ModelForm):
    collector_key = forms.ChoiceField(
        label="Сборщик",
        help_text="Семейство площадок, к которому относится сайт. От него зависит, "
        "как разбираются страницы и какие поля ниже нужны.",
    )

    class Meta:
        model = Config
        fields = ["name", "collector_key", "enabled", "archived", "tags", "owner"]
        labels = {"name": "Название источника"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["collector_key"].choices = [
            (d.key, d.display_name) for d in schemas.all_collectors() if d.is_source
        ]

        self._param_names: tuple[str, ...] = ()
        descriptor = self._resolve_descriptor()
        if descriptor is None:
            return

        self._param_names = tuple(p.name for p in descriptor.params)
        parameters = getattr(self.instance, "parameters", None) or {}
        for spec in descriptor.params:
            self.fields[spec.name] = _build_field(spec)
            if spec.name in parameters and parameters[spec.name] is not None:
                self.fields[spec.name].initial = parameters[spec.name]

    def _resolve_descriptor(self) -> schemas.CollectorDescriptor | None:
        key = (
            (self.data.get("collector_key") if self.is_bound else None)
            or self.initial.get("collector_key")
            or getattr(self.instance, "collector_key", "")
        )
        if not key:
            return None
        try:
            return schemas.get_collector(key)
        except schemas.UnknownCollector:
            return None

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        key = cleaned.get("collector_key")
        if not key:
            return cleaned

        parameters = self._collect_parameters(cleaned)
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

    def _collect_parameters(self, cleaned: dict[str, Any]) -> dict[str, Any]:
        """The form's fields → the parameter dict this collector declares.

        A blank optional value is dropped rather than stored as `""`/`None`: that means "whatever
        the collector's default is". Storing the resolved default would freeze today's default
        into every source ever created under it.
        """
        parameters: dict[str, Any] = {}
        for name in self._param_names:
            value = cleaned.get(name)
            if value in (None, ""):
                continue
            parameters[name] = value
        return parameters

    def save(self, commit: bool = True) -> Config:
        source = super().save(commit=False)
        source.parameters = self.cleaned_data.get("parameters", source.parameters)
        if commit:
            source.save()
            self.save_m2m()
        return source
