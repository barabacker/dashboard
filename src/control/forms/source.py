"""Authoring form for a `Source` — a site's identity: domain, start URL, TLS quirks.

Behaviour (which collector, `max_pages`, `fetch_details`, ...) belongs to a `Config` profile that
references this `Source`, not to the `Source` itself — see `control.forms.ConfigForm` for that
side. `tls_options` is one JSON field, the same shape it is on the model and the same choice
`ConfigForm` makes for `parameters`: validation here is a *convenience* (catches an unknown
certificate name), not the guarantee — `Source.param_value` reads whatever is stored, typo or not.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors.schemas.tender import DEFAULT_LISTING_PATHS, available_certs
from control.models import Source


class SourceForm(forms.ModelForm):
    start_url = forms.CharField(
        label="Путь к листингу",
        max_length=200,
        required=False,
        help_text="Пусто — путь по умолчанию для движка того профиля, который обходит этот сайт: "
        + ", ".join(f"{engine} → {path}" for engine, path in DEFAULT_LISTING_PATHS.items()),
    )

    class Meta:
        model = Source
        fields = ["name", "domain", "start_url", "tls_options"]
        labels = {"name": "Название источника"}
        widgets = {"tls_options": forms.Textarea(attrs={"rows": 4, "cols": 60})}

    def clean_tls_options(self) -> dict[str, Any]:
        # An empty textarea comes back as `None` from the auto-generated JSONField, not `{}` —
        # `tls_options` is `blank=True` at the model level but the column is NOT NULL, so an
        # uncoerced `None` would sail past this form and hit the database instead (see
        # `ConfigForm.clean` for the same coercion on `parameters`).
        value = self.cleaned_data.get("tls_options") or {}
        cert = value.get("extra_ca_cert")
        if cert and cert not in available_certs():
            raise forms.ValidationError(f"{cert!r}: такого файла нет в collectors/certs.")
        return value
