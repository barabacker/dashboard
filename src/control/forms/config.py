"""Authoring form for Config.

The parameter fields are built from the selected collector's own `ParamSpec` list — one Django
field per declared parameter, not a hand-maintained set. Adding a collector whose parameters are
plain `str`/`int`/`float`/`bool`/`choices` needs no change here; the mapping already covers the
closed `kind` set `collectors.schemas.base` defines (D4).

Only one collector's fields are ever rendered at a time: the admin reloads the add page (via a
plain `?collector_key=` query string, no JS framework) when the dropdown changes, so there is never
a moment where two collectors' parameters coexist in the same form and might collide by name.

Validation here is a *convenience*, not the guarantee: enqueue re-validates against the schema it
actually resolves (§6). Catching a bad parameter set at authoring time is nicer than discovering it
as a failed Job, but a Config's raw parameters can still drift out of step with the code — the
schema is edited in place as requirements change — and that case is meant to fail fast at enqueue,
not to be prevented here.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors import schemas
from collectors.schemas.base import ParamSpec
from control.models import Config, Source

#: Direct reflection of the closed `kind` set in `collectors/schemas/base.py` (D4) — not a
#: general-purpose form generator, just this one, bounded mapping.
_FIELD_TYPES: dict[str, type[forms.Field]] = {
    "str": forms.CharField,
    "int": forms.IntegerField,
    "float": forms.FloatField,
    "bool": forms.BooleanField,
    "list": forms.JSONField,
    "dict": forms.JSONField,
}


def _build_field(spec: ParamSpec) -> forms.Field:
    help_text = spec.description
    if spec.is_credential_ref:
        help_text = f"Ссылка на секрет (имя, не сам секрет). {help_text}".strip()

    if spec.choices is not None:
        field = forms.ChoiceField(
            choices=[(c, c) for c in spec.choices], required=spec.required, help_text=help_text
        )
    else:
        field_class = _FIELD_TYPES[spec.kind]
        kwargs: dict[str, Any] = {"required": spec.required, "help_text": help_text}
        if spec.kind == "bool":
            # An unchecked box already means "false", a valid value, not "missing" — a
            # required BooleanField would instead demand the box be *checked*, which is not
            # what "required" means for a flag.
            kwargs["required"] = False
        if spec.kind in {"int", "float"}:
            if spec.min_value is not None:
                kwargs["min_value"] = spec.min_value
            if spec.max_value is not None:
                kwargs["max_value"] = spec.max_value
        field = field_class(**kwargs)

    field.label = spec.name
    return field


class ConfigForm(forms.ModelForm):
    collector_key = forms.ChoiceField(
        label="Сборщик",
        help_text="Конкретная версия определяется в момент постановки в очередь.",
    )

    class Meta:
        model = Config
        fields = ["name", "collector_key", "source", "enabled", "archived", "tags", "owner"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        known = [(d.key, d.display_name) for d in schemas.all_collectors()]
        current = self._current_collector_key(known)
        # A Config may point at a collector that has since been removed from the code. Keep the
        # stale value selectable so editing the rest of the row still works.
        if current and current not in {key for key, _ in known}:
            known.insert(0, (current, f"{current} — больше нет в кодовой базе"))
        self.fields["collector_key"].choices = known
        self.fields["collector_key"].initial = current
        # Reloading the add page is the whole mechanism: no JS framework, no risk of two
        # collectors' fields coexisting and colliding by name (only one is ever rendered).
        self.fields["collector_key"].widget.attrs["onchange"] = (
            "location.href = location.pathname + '?collector_key=' + this.value"
        )

        #: Public: `ConfigAdmin.get_fieldsets` reads this off a probe instance of this form to
        #: know which fieldset fields to render for the currently selected collector.
        self.param_field_names: list[str] = []
        if current:
            self._add_parameter_fields(current)

    def _current_collector_key(self, known: list[tuple[str, str]]) -> str:
        """Which collector's parameter fields to render.

        Priority: what was actually submitted (a POST, or a reload after picking a different
        engine via the `?collector_key=` query string, which `ConfigAdmin.get_changeform_initial
        _data` — Django's own, unoverridden default — already folds into `initial`), then the
        instance's own value (editing an existing profile), then the first known collector (a
        brand-new, never-touched add form has to show *something*).
        """
        submitted = self.data.get(self.add_prefix("collector_key")) if self.data else None
        if submitted:
            return submitted
        if self.instance.pk:
            return self.instance.collector_key
        if self.initial.get("collector_key"):
            return self.initial["collector_key"]
        return known[0][0] if known else ""

    def _add_parameter_fields(self, collector_key: str) -> None:
        try:
            descriptor = schemas.get_collector(collector_key)
        except schemas.UnknownCollector:
            return
        stored = self.instance.parameters if self.instance.pk else {}
        for spec in descriptor.params:
            if spec.name in Source.PARAM_FIELDS:
                # Supplied by the profile's `source`, not re-entered here — see
                # `Config.raw_parameters`.
                continue
            if spec.name in self.fields:
                # A parameter sharing a name with a real Config field (name/enabled/tags/...)
                # would need a naming scheme to disambiguate — no current collector does this,
                # so it is left as a sharp edge rather than a speculative mechanism for one that
                # might.
                continue
            field = _build_field(spec)
            field.initial = stored.get(spec.name, spec.default)
            self.fields[spec.name] = field
            self.param_field_names.append(spec.name)

    def clean(self) -> dict:
        cleaned = super().clean()
        key = cleaned.get("collector_key")
        if not key:
            return cleaned

        try:
            descriptor = schemas.get_collector(key)
        except schemas.UnknownCollector:
            self.add_error("collector_key", f"Сборщика {key!r} нет в кодовой базе.")
            return cleaned

        # Resolves correctly whether this form shows a `source` field or not: the
        # Config-under-Source inline never displays one (it is implied by the parent page), but
        # Django's inline-formset machinery substitutes an `InlineForeignKeyField` for it, whose
        # own `clean()` returns the parent instance whenever nothing was submitted — exactly
        # this case.
        source = cleaned.get("source")

        # `is_site` gates the pairing before the parameters are even looked at: a site-shaped
        # collector with no `source` is guaranteed to fail later on a missing `domain` anyway,
        # and the reverse (a `source` on a collector that declares no site parameters) would not
        # fail at all — its fields are silently filtered out of `raw_parameters()` — which is
        # exactly why it needs a named error here instead of a silent no-op.
        if descriptor.is_site and source is None:
            self.add_error("source", f"Сборщик {key!r} привязан к сайту — выберите источник.")
            return cleaned
        if not descriptor.is_site and source is not None:
            self.add_error(
                "source",
                f"Сборщик {key!r} не использует параметры сайта — источник не даст эффекта.",
            )
            return cleaned

        # The inline never renders parameter fields at all (`_add_parameter_fields` is a no-op
        # for it) — `param_field_names` is then empty and `parameters` resolves to `{}`, which
        # is exactly right: a profile added that way keeps its collector's defaults until edited
        # on its own change page.
        parameters = {name: cleaned[name] for name in self.param_field_names if name in cleaned}
        cleaned["parameters"] = parameters

        # An unsaved probe: `raw_parameters()` only reads `collector_key`/`source`/`parameters`,
        # none of which need a persisted row, and this keeps the source-merge logic in exactly
        # the one place (`Config.raw_parameters`) that `enqueue` and the admin preview also use.
        probe = Config(collector_key=key, parameters=parameters, source=source)
        try:
            schemas.resolve_parameters(key, probe.raw_parameters())
        except schemas.ParameterError as exc:
            for message in exc.errors:
                # Point at the specific parameter field when the message names one we rendered;
                # otherwise show it on the form as a whole.
                field_name = message.split(":", 1)[0]
                self.add_error(field_name if field_name in self.fields else None, message)
        return cleaned

    def save(self, commit: bool = True) -> Config:
        config = super().save(commit=False)
        config.parameters = self.cleaned_data.get("parameters", {})
        if commit:
            config.save()
        return config
