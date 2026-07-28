"""Authoring form for Config.

Validation here is a *convenience*, not the guarantee: enqueue re-validates against the version it
actually resolves (§6). Catching a bad parameter set at authoring time is nicer than discovering
it as a failed Job, but a Config authored against v1 can still become invalid when v2 ships — that
case is meant to fail fast at enqueue, not to be prevented here.
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
            "parameters",
            "enabled",
            "archived",
            "tags",
            "owner",
        ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        known = [
            (d.key, f"{d.display_name} — текущая v{d.current_version}")
            for d in schemas.all_collectors()
        ]
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

        try:
            version = schemas.current_version(key)
        except schemas.UnknownCollector:
            self.add_error("collector_key", f"Сборщика {key!r} нет в кодовой базе.")
            return cleaned

        try:
            schemas.resolve_parameters(key, version, parameters)
        except schemas.ParameterError as exc:
            for message in exc.errors:
                self.add_error("parameters", f"v{version}: {message}")
        return cleaned
