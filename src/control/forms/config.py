"""Authoring form for Config.

`parameters` is one JSON textarea — the collector's schema is not reflected into the form at all.
Validation here is a *convenience*, not the guarantee: enqueue re-validates against the schema it
actually resolves (§6). A Config's raw parameters can still drift out of step with the code — the
schema is edited in place as requirements change — and that case is meant to fail fast at enqueue,
not to be prevented here.

`collector_key` stays a `ChoiceField` of what `schemas.all_collectors()` currently knows about —
unlike `parameters`, a typo here is a name that plain doesn't resolve, so there is no reason to
make someone type it from memory.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors import schemas
from control.models import Config


class ConfigForm(forms.ModelForm):
    collector_key = forms.ChoiceField(
        label="Сборщик",
        help_text="Конкретная версия определяется в момент постановки в очередь.",
    )

    class Meta:
        model = Config
        fields = ["name", "collector_key", "source", "parameters", "enabled", "owner"]
        widgets = {"parameters": forms.Textarea(attrs={"rows": 8, "cols": 60})}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        known = [(d.key, d.display_name) for d in schemas.all_collectors()]
        current = self.instance.collector_key if self.instance.pk else ""
        # A Config may point at a collector that has since been removed from the code. Keep the
        # stale value selectable so editing the rest of the row still works.
        if current and current not in {key for key, _ in known}:
            known.insert(0, (current, f"{current} — больше нет в кодовой базе"))
        self.fields["collector_key"].choices = known

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

        if descriptor.is_site and source is None:
            self.add_error("source", f"Сборщик {key!r} привязан к сайту — выберите источник.")
            return cleaned
        if not descriptor.is_site and source is not None:
            self.add_error(
                "source",
                f"Сборщик {key!r} не использует параметры сайта — источник не даст эффекта.",
            )
            return cleaned

        # An empty textarea comes back as `None` from the auto-generated JSONField, not `{}` —
        # `parameters` is `blank=True` at the model level, so neither this form's own validation
        # nor `Model.full_clean()` treats a `None` here as an error, and the column is NOT NULL.
        # Coercing it to `{}` (never entered, not "must fail") is what the pre-JSON-textarea form
        # did implicitly by starting from an empty dict of per-field values.
        parameters = cleaned.get("parameters")
        if parameters is None:
            parameters = {}
            cleaned["parameters"] = parameters

        # An unsaved probe: `raw_parameters()` only reads `collector_key`/`source`/`parameters`,
        # none of which need a persisted row, and this keeps the source-merge logic in exactly
        # the one place (`Config.raw_parameters`) that `enqueue` and the admin preview also use.
        probe = Config(collector_key=key, parameters=parameters, source=source)
        try:
            schemas.resolve_parameters(key, probe.raw_parameters())
        except schemas.ParameterError as exc:
            self.add_error("parameters", "; ".join(exc.errors))
        return cleaned
