"""The projection follows code, and only ever in one direction."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from collectors import schemas
from control.models import Collector

pytestmark = pytest.mark.django_db


def test_creates_rows_for_collectors_in_code():
    call_command("sync_collectors")
    row = Collector.objects.get(key="example_api")
    assert row.display_name == "Пример: HTTP API"
    assert row.enabled
    assert row.synced_at is not None


def test_projects_every_collector_in_code():
    call_command("sync_collectors")
    assert set(Collector.objects.values_list("key", flat=True)) == {
        d.key for d in schemas.all_collectors()
    }


def test_is_idempotent():
    call_command("sync_collectors")
    once = Collector.objects.count()
    call_command("sync_collectors")
    assert Collector.objects.count() == once


def test_a_key_that_left_the_codebase_is_disabled_not_deleted():
    Collector.objects.create(key="retired", display_name="Retired collector")
    call_command("sync_collectors")

    retired = Collector.objects.get(key="retired")
    assert retired.enabled is False
    assert Collector.objects.filter(key="retired").exists()


def test_manual_edits_to_projected_fields_are_overwritten():
    call_command("sync_collectors")
    Collector.objects.filter(key="example_api").update(display_name="hand-edited")

    call_command("sync_collectors")
    assert Collector.objects.get(key="example_api").display_name == "Пример: HTTP API"


def test_dry_run_writes_nothing():
    call_command("sync_collectors", "--dry-run")
    assert Collector.objects.count() == 0


def test_the_schema_table_renders_on_the_change_page(client, user):
    """Regression: D21 flattened `CollectorDescriptor` (dropped the `versions` axis) and the
    admin's schema table kept iterating `descriptor.versions` — an `AttributeError` on every
    Collector change page nobody had a test to catch."""
    call_command("sync_collectors")
    row = Collector.objects.get(key="tender_kendo")

    client.force_login(user)
    response = client.get(reverse("admin:control_collector_change", args=[row.pk]))

    assert response.status_code == 200
    assert b"domain" in response.content
