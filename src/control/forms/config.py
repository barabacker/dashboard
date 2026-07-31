"""Authoring form for Config.

Validation here is a *convenience*, not the guarantee: enqueue re-validates against the schema it
actually resolves (§6). Catching a bad parameter set at authoring time is nicer than discovering it
as a failed Job, but a Config's raw parameters can still drift out of step with the code — the
schema is edited in place as requirements change — and that case is meant to fail fast at enqueue,
not to be prevented here.
"""

from __future__ import annotations

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
        fields = [
            "name",
            "collector_key",
            "source",
            "parameters",
            "enabled",
            "archived",
            "tags",
            "owner",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        known = [(d.key, d.display_name) for d in schemas.all_collectors()]
        current = self.initial.get("collector_key") or getattr(self.instance, "collector_key", "")
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
        parameters = cleaned.get("parameters")
        if parameters is None:
            return cleaned
        if not isinstance(parameters, dict):
            self.add_error("parameters", "Параметры должны быть JSON-объектом.")
            return cleaned

        source = cleaned.get("source")
        try:
            descriptor = schemas.get_collector(key)
        except schemas.UnknownCollector:
            self.add_error("collector_key", f"Сборщика {key!r} нет в кодовой базе.")
            return cleaned

        # `is_site` gates the pairing before the parameters even get resolved: a site-shaped
        # collector with no `source` is guaranteed to fail on a missing `domain`, and the reverse
        # (a `source` on a collector that declares no site parameters) would not fail at all — its
        # fields are silently filtered out of `raw_parameters()` — which is exactly why it needs a
        # named error here instead of a silent no-op.
        if descriptor.is_site and source is None:
            self.add_error("source", f"Сборщик {key!r} привязан к сайту — выберите источник.")
            return cleaned
        if not descriptor.is_site and source is not None:
            self.add_error(
                "source",
                f"Сборщик {key!r} не использует параметры сайта — источник не даст эффекта.",
            )
            return cleaned

        # An unsaved probe: `raw_parameters()` only reads `collector_key`/`source`/`parameters`,
        # none of which need a persisted row, and this keeps the source-merge logic in exactly
        # the one place (`Config.raw_parameters`) that `enqueue` and the admin preview also use.
        probe = Config(collector_key=key, parameters=parameters, source=source)
        try:
            schemas.resolve_parameters(key, probe.raw_parameters())
        except schemas.ParameterError as exc:
            for message in exc.errors:
                self.add_error("parameters", message)
        return cleaned
