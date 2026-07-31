"""The single shared enqueue function (§6) — preconditions and the snapshot contract (§4)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from control.models import Collector, Config, Job, JobOrigin, JobStatus
from control.services import EnqueueRefused, enqueue
from control.services.enqueue import InvalidParamsPolicy

pytestmark = pytest.mark.django_db


class TestPreconditions:
    def test_a_disabled_config_is_refused(self, make_config):
        config = make_config(enabled=False)
        with pytest.raises(EnqueueRefused) as exc_info:
            enqueue(config)
        assert exc_info.value.reason == "config_disabled"
        assert Job.objects.count() == 0

    def test_a_collector_that_left_the_codebase_is_refused(self, make_config):
        config = make_config(collector_key="gone")
        with pytest.raises(EnqueueRefused) as exc_info:
            enqueue(config)
        assert exc_info.value.reason == "collector_unknown"

    def test_a_disabled_collector_projection_stops_new_work(self, config):
        Collector.objects.create(key="example_api", display_name="Example", enabled=False)
        with pytest.raises(EnqueueRefused) as exc_info:
            enqueue(config)
        assert exc_info.value.reason == "collector_disabled"

    def test_a_collector_without_a_projection_row_is_still_runnable(self, config):
        assert Collector.objects.count() == 0
        assert enqueue(config).status == JobStatus.PENDING


class TestSnapshot:
    def test_resolves_parameters_against_the_collectors_schema(self, config):
        job = enqueue(config)

        assert job.config_id == config.pk
        assert job.status == JobStatus.PENDING
        # Defaults applied, nothing left implicit.
        assert job.effective_parameters["since"] == ""
        assert job.effective_parameters["credential_ref"] == ""
        assert job.effective_parameters["page_size"] == 10

    def test_a_later_config_edit_does_not_touch_an_existing_snapshot(self, config):
        job = enqueue(config)
        original = dict(job.effective_parameters)

        config.parameters["base_url"] = "https://changed.test"
        config.save()

        assert Job.objects.get(pk=job.pk).effective_parameters == original

    def test_the_credential_reference_is_snapshotted_but_never_the_secret(self, make_config):
        config = make_config(
            parameters={
                "base_url": "https://x.test",
                "dataset": "orders",
                "credential_ref": "COLLECTOR_SECRET_DEMO_TOKEN",
            }
        )
        job = enqueue(config)
        snapshot = job.effective_parameters
        assert snapshot["credential_ref"] == "COLLECTOR_SECRET_DEMO_TOKEN"
        assert not any(
            "secret" in str(v).lower() and v != "COLLECTOR_SECRET_DEMO_TOKEN"
            for v in snapshot.values()
        )


class TestInvalidParameters:
    """A Config whose raw parameters do not satisfy the collector's schema — edited directly,
    bypassing the admin form's own validation, or predating a field that later became required."""

    @pytest.fixture
    def stale_config(self, make_config) -> Config:
        return make_config(parameters={"base_url": "https://x.test"})

    def test_run_now_refuses_and_creates_nothing(self, stale_config):
        with pytest.raises(EnqueueRefused) as exc_info:
            enqueue(stale_config, origin=JobOrigin.MANUAL)
        assert exc_info.value.reason == "params_invalid"
        assert exc_info.value.errors == ["dataset: обязательный параметр"]
        assert Job.objects.count() == 0

    def test_a_scheduled_fire_records_a_failed_job_instead(self, stale_config):
        job = enqueue(stale_config, origin=JobOrigin.SCHEDULE)

        assert job.status == JobStatus.FAILED
        # The persisted diagnostic stays English — §6 names this exact wording, and it is data,
        # not UI. Only the human-readable parameter errors are translated.
        assert job.structured_error["type"] == "config_invalid"
        assert job.structured_error["message"] == "config invalid for collector example_api"
        assert job.structured_error["errors"] == ["dataset: обязательный параметр"]
        assert job.finished_at is not None

    def test_the_recorded_failure_is_not_claimable(self, stale_config):
        enqueue(stale_config, origin=JobOrigin.SCHEDULE)
        assert Job.objects.filter(status=JobStatus.PENDING).count() == 0

    def test_the_policy_can_be_forced_either_way(self, stale_config):
        job = enqueue(
            stale_config,
            origin=JobOrigin.MANUAL,
            on_invalid_params=InvalidParamsPolicy.RECORD_FAILURE,
        )
        assert job.status == JobStatus.FAILED

        with pytest.raises(EnqueueRefused):
            enqueue(
                stale_config,
                origin=JobOrigin.SCHEDULE,
                on_invalid_params=InvalidParamsPolicy.REFUSE,
            )


class TestQueueFields:
    def test_priority_and_availability_are_carried_through(self, config):
        later = timezone.now() + timezone.timedelta(hours=1)
        job = enqueue(config, priority=5, available_at=later)
        assert job.priority == 5
        assert job.available_at == later

    def test_origin_and_requester_are_recorded(self, config, user):
        job = enqueue(config, origin=JobOrigin.MANUAL, requested_by=user)
        assert job.origin == JobOrigin.MANUAL
        assert job.requested_by_id == user.pk
