"""Split existing tender Config.parameters into Source rows (ADR 0004 / D22).

Before this migration a "source" was a Config whose `parameters` carried `domain` (and, for some
sites, `listing_path`/`extra_ca_cert`/`skip_tls_verify`) directly. Those four keys move to a
`Source` row, one per distinct domain, and the Config that used to carry them points at it instead
— everything else about the Config (name, collector_key, enabled, ...) is untouched.

Deliberately keyed on "has a `domain` key in `parameters`" rather than on `collector_key` — that
keeps this migration honest about what it is actually moving, without importing the current
collector registry into a migration that must keep working as that registry changes.
"""

from __future__ import annotations

from django.db import migrations

_SITE_KEYS = ("listing_path", "extra_ca_cert", "skip_tls_verify")


def split_domain_into_source(apps, schema_editor) -> None:
    Config = apps.get_model("control", "Config")
    Source = apps.get_model("control", "Source")

    for config in Config.objects.filter(parameters__has_key="domain"):
        parameters = dict(config.parameters)
        domain = parameters.pop("domain", "")
        if not domain:
            continue
        site_fields = {key: parameters.pop(key, "") for key in _SITE_KEYS}
        site_fields["skip_tls_verify"] = bool(site_fields["skip_tls_verify"])

        source, created = Source.objects.get_or_create(
            domain=domain,
            defaults={"name": config.name, **site_fields},
        )
        config.source_id = source.pk
        config.parameters = parameters
        config.save(update_fields=["source", "parameters"])


def noop(apps, schema_editor) -> None:
    """Not reversed: folding a Source back into every Config that once duplicated it would need
    to guess which Config "owns" the site once more than one profile references it — exactly the
    ambiguity this migration exists to remove."""


class Migration(migrations.Migration):
    dependencies = [
        ("control", "0007_source_becomes_a_table"),
    ]

    operations = [
        migrations.RunPython(split_domain_into_source, noop),
    ]
