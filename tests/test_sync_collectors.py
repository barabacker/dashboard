"""The projection follows code, and only ever in one direction."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from control.models import Collector

pytestmark = pytest.mark.django_db


def test_creates_rows_for_collectors_in_code():
    call_command("sync_collectors")
    row = Collector.objects.get(key="example_api")
    assert row.display_name == "Пример: HTTP API"
    assert row.enabled
    assert row.synced_at is not None


def test_is_idempotent():
    call_command("sync_collectors")
    call_command("sync_collectors")
    assert Collector.objects.count() == 1


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
