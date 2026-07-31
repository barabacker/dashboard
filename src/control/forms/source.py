"""Authoring form for a `Source` — a site's identity: domain, start URL, TLS quirks.

Behaviour (which collector, `max_pages`, `fetch_details`, ...) belongs to a `Config` profile that
references this `Source`, not to the `Source` itself — see `control.forms.ConfigForm` for that
side. `extra_ca_cert`/`skip_tls_verify` are declared here as their own fields even though they are
stored together inside `Source.tls_options`: the split is a database-shape decision, not something
the person filling the form needs to see.
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
    skip_tls_verify = forms.BooleanField(
        label="Не проверять сертификат",
        required=False,
        help_text="Полностью отключить проверку сертификата для этого сайта.",
    )
    start_url = forms.CharField(
        label="Путь к листингу",
        max_length=200,
        required=False,
        help_text="Пусто — путь по умолчанию для движка того профиля, который обходит этот сайт: "
        + ", ".join(f"{engine} → {path}" for engine, path in DEFAULT_LISTING_PATHS.items()),
    )

    class Meta:
        model = Source
        fields = ["name", "domain", "start_url"]
        labels = {"name": "Название источника"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["extra_ca_cert"].choices = [("", "— обычный набор корневых —")] + [
            (name, name) for name in available_certs()
        ]
        if self.instance.pk:
            self.fields["extra_ca_cert"].initial = self.instance.tls_options.get(
                "extra_ca_cert", ""
            )
            self.fields["skip_tls_verify"].initial = self.instance.tls_options.get(
                "skip_tls_verify", False
            )

    def save(self, commit: bool = True) -> Source:
        source = super().save(commit=False)
        source.tls_options = {
            "extra_ca_cert": self.cleaned_data.get("extra_ca_cert", ""),
            "skip_tls_verify": self.cleaned_data.get("skip_tls_verify", False),
        }
        if commit:
            source.save()
        return source
