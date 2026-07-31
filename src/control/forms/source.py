"""Authoring form for a `Source` — a site's identity: domain, listing path, TLS quirks.

Behaviour (which collector, `max_pages`, `fetch_details`, ...) belongs to a `Config` profile that
references this `Source`, not to the `Source` itself — see `control.forms.ConfigForm` for that
side. Keeping the two forms apart mirrors the model split (`control.models.Source` /
`control.models.Config.source`): a `Source` never carries a `collector_key` and never resolves
against a schema.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors.schemas.tender import DEFAULT_LISTING_PATHS, available_certs
from control.models import Source


class SourceForm(forms.ModelForm):
    extra_ca_cert = forms.ChoiceField(
        label="Доп. сертификат",
        required=False,
        help_text="Имя PEM-файла из collectors/certs с промежуточным сертификатом, который сайт "
        "не отдаёт сам. Пусто — обычный набор корневых сертификатов.",
    )
    listing_path = forms.CharField(
        label="Путь к листингу",
        max_length=200,
        required=False,
        help_text="Пусто — путь по умолчанию для движка того профиля, который обходит этот сайт: "
        + ", ".join(f"{engine} → {path}" for engine, path in DEFAULT_LISTING_PATHS.items()),
    )

    class Meta:
        model = Source
        fields = ["name", "domain", "listing_path", "extra_ca_cert", "skip_tls_verify", "archived"]
        labels = {"name": "Название источника"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["extra_ca_cert"].choices = [("", "— обычный набор корневых —")] + [
            (name, name) for name in available_certs()
        ]
