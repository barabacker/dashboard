"""Model-level invariants: revisions, snapshot immutability, terminal states."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from control.models import Config, Job, JobStatus, Schedule

pytestmark = pytest.mark.django_db


def _job(config: Config, **overrides) -> Job:
    defaults = {
        "collector_key": config.collector_key,
        "effective_parameters": {"base_url": "https://x.test"},
        "config_id": config.pk,
    }
    return Job.objects.create(**{**defaults, **overrides})


class TestJobInvariants:
    def test_snapshot_fields_cannot_be_rewritten(self, config):
        job = _job(config)
        reloaded = Job.objects.get(pk=job.pk)
        reloaded.collector_key = "something_else"
        with pytest.raises(ValueError, match="snapshot fields are immutable"):
            reloaded.save()

    def test_effective_parameters_cannot_be_rewritten(self, config):
        job = _job(config)
        reloaded = Job.objects.get(pk=job.pk)
        reloaded.effective_parameters["base_url"] = "https://elsewhere.test"
        with pytest.raises(ValueError, match="snapshot fields are immutable"):
            reloaded.save()

    @pytest.mark.parametrize(
        "terminal", [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED]
    )
    def test_a_terminal_job_never_transitions_again(self, config, terminal):
        job = _job(config, status=terminal)
        reloaded = Job.objects.get(pk=job.pk)
        reloaded.status = JobStatus.PENDING
        with pytest.raises(ValueError, match="terminal"):
            reloaded.save()

    def test_execution_state_stays_writable_while_active(self, config):
        job = _job(config)
        job.status = JobStatus.RUNNING
        job.claimed_by = "worker-1"
        job.save()
        assert Job.objects.get(pk=job.pk).status == JobStatus.RUNNING

    def test_two_jobs_cannot_realise_the_same_scheduled_occurrence(self, config, make_schedule):
        from django.db import IntegrityError, transaction

        schedule = make_schedule(config)
        fire_time = timezone.now().replace(microsecond=0)
        _job(config, schedule_id=schedule.pk, fire_time=fire_time)

        with pytest.raises(IntegrityError), transaction.atomic():
            _job(config, schedule_id=schedule.pk, fire_time=fire_time)

    def test_manual_jobs_are_exempt_from_the_uniqueness_constraint(self, config):
        _job(config)
        _job(config)
        assert Job.objects.filter(config_id=config.pk).count() == 2


class TestSchedule:
    def test_rejects_an_invalid_cron(self, config):
        schedule = Schedule(config=config, cron="not a cron", timezone="UTC")
        with pytest.raises(ValidationError) as exc_info:
            schedule.full_clean()
        assert "cron" in exc_info.value.message_dict

    def test_rejects_an_unknown_timezone(self, config):
        schedule = Schedule(config=config, cron="0 * * * *", timezone="Mars/Olympus")
        with pytest.raises(ValidationError) as exc_info:
            schedule.full_clean()
        assert "timezone" in exc_info.value.message_dict

    def test_is_deleted_with_its_config(self, config, make_schedule):
        make_schedule(config)
        config.delete()
        assert Schedule.objects.count() == 0
