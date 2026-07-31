"""Authoring form for Config.

`parameters` is one JSON textarea — the collector's schema is not reflected into the form at all.
Validation here is a *convenience*, not the guarantee: enqueue re-validates against the schema it
actually resolves (§6). A Config's raw parameters can still drift out of step with the code — the
schema is edited in place as requirements change — and that case is meant to fail fast at enqueue,
not to be prevented here.
"""

from __future__ import annotations

from django import forms

from collectors import schemas
from control.models import Config


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["name", "collector_key", "source", "parameters", "enabled", "owner"]
        widgets = {"parameters": forms.Textarea(attrs={"rows": 8, "cols": 60})}

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

        parameters = cleaned.get("parameters")
        if parameters is None:
            return cleaned

        # An unsaved probe: `raw_parameters()` only reads `collector_key`/`source`/`parameters`,
        # none of which need a persisted row, and this keeps the source-merge logic in exactly
        # the one place (`Config.raw_parameters`) that `enqueue` and the admin preview also use.
        probe = Config(collector_key=key, parameters=parameters, source=source)
        try:
            schemas.resolve_parameters(key, probe.raw_parameters())
        except schemas.ParameterError as exc:
            self.add_error("parameters", "; ".join(exc.errors))
        return cleaned
