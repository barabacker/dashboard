"""The scheduler (§10): due detection, policies, and the idempotency guarantee."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from control.models import (
    CatchupPolicy,
    Config,
    Job,
    JobOrigin,
    JobStatus,
    OverlapPolicy,
    Schedule,
)
from control.services import enqueue
from execution.scheduler import due_occurrences, tick

pytestmark = pytest.mark.django_db

UTC = ZoneInfo("UTC")


def at(hour: int, minute: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


class TestDueOccurrences:
    """Pure cron arithmetic — no enqueue, no transaction."""

    def test_a_schedule_that_never_fired_yields_nothing(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *")
        assert schedule.last_fired_at is None
        assert due_occurrences(schedule, now=at(12)) == []

    def test_lists_every_missed_occurrence_under_fire_missed(self, config, make_schedule):
        schedule = make_schedule(
            config,
            cron="0 * * * *",
            catchup_policy=CatchupPolicy.FIRE_MISSED,
            last_fired_at=at(9),
        )
        assert due_occurrences(schedule, now=at(12, 30)) == [at(10), at(11), at(12)]

    def test_keeps_only_the_latest_under_skip_to_now(self, config, make_schedule):
        schedule = make_schedule(
            config,
            cron="0 * * * *",
            catchup_policy=CatchupPolicy.SKIP_TO_NOW,
            last_fired_at=at(9),
        )
        assert due_occurrences(schedule, now=at(12, 30)) == [at(12)]

    def test_nothing_is_due_before_the_next_occurrence(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *", last_fired_at=at(12))
        assert due_occurrences(schedule, now=at(12, 30)) == []

    def test_the_cron_is_evaluated_in_the_schedules_timezone(self, config, make_schedule):
        """02:00 Europe/Berlin in March is 01:00 UTC."""
        schedule = make_schedule(
            config,
            cron="0 2 * * *",
            timezone="Europe/Berlin",
            catchup_policy=CatchupPolicy.FIRE_MISSED,
            last_fired_at=at(0, day=5),
        )
        occurrences = due_occurrences(schedule, now=at(12, day=5))
        assert [o.astimezone(UTC) for o in occurrences] == [at(1, day=5)]

    def test_catch_up_is_capped(self, config, make_schedule):
        schedule = make_schedule(
            config,
            cron="* * * * *",
            catchup_policy=CatchupPolicy.FIRE_MISSED,
            last_fired_at=at(0),
        )
        assert len(due_occurrences(schedule, now=at(12), max_catchup=10)) == 10


class TestTick:
    def test_bootstraps_a_new_schedule_without_firing(self, config, make_schedule):
        schedule = make_schedule(config, cron="* * * * *")

        report = tick(now=at(12))

        assert report.bootstrapped == 1
        assert Job.objects.count() == 0
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(12)

    def test_enqueues_a_due_occurrence_and_advances_the_cursor(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *", last_fired_at=at(9))

        report = tick(now=at(10, 30))

        job = Job.objects.get()
        assert report.enqueued == [job.pk]
        assert job.origin == JobOrigin.SCHEDULE
        assert job.schedule_id == schedule.pk
        assert job.fire_time == at(10)
        assert job.status == JobStatus.PENDING
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(10)

    def test_a_disabled_schedule_is_left_alone(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *", enabled=False, last_fired_at=at(9))

        tick(now=at(12))

        assert Job.objects.count() == 0
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(9)

    def test_a_disabled_config_fires_nothing_and_does_not_build_a_backlog(
        self, make_config, make_schedule
    ):
        config = make_config(enabled=False)
        schedule = make_schedule(config, cron="0 * * * *", last_fired_at=at(9))

        report = tick(now=at(12, 30))

        assert report.skipped_not_runnable == 1
        assert Job.objects.count() == 0
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(12, 30)

    def test_a_stale_config_records_a_failed_job_rather_than_silently_skipping(
        self, make_config, make_schedule
    ):
        """The collector moved to v2.0 and the Config never gained `dataset`."""
        config = make_config(parameters={"base_url": "https://x.test"})
        make_schedule(config, cron="0 * * * *", last_fired_at=at(9))

        tick(now=at(10, 30))

        job = Job.objects.get()
        assert job.status == JobStatus.FAILED
        assert job.structured_error["type"] == "config_invalid"


class TestOverlapPolicy:
    @pytest.fixture
    def busy_config(self, config) -> Config:
        enqueue(config)  # a pending Job — an active run for this Config
        return config

    def test_skip_drops_the_occurrence_but_still_advances(self, busy_config, make_schedule):
        schedule = make_schedule(
            busy_config,
            cron="0 * * * *",
            overlap_policy=OverlapPolicy.SKIP,
            last_fired_at=at(9),
        )

        report = tick(now=at(10, 30))

        assert report.skipped_overlap == 1
        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 0
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(10)

    def test_queue_enqueues_anyway(self, busy_config, make_schedule):
        make_schedule(
            busy_config,
            cron="0 * * * *",
            overlap_policy=OverlapPolicy.QUEUE,
            last_fired_at=at(9),
        )

        tick(now=at(10, 30))

        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 1

    def test_allow_enqueues_without_even_looking(self, busy_config, make_schedule):
        make_schedule(
            busy_config,
            cron="0 * * * *",
            overlap_policy=OverlapPolicy.ALLOW,
            last_fired_at=at(9),
        )

        tick(now=at(10, 30))

        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 1

    def test_skip_only_applies_while_a_run_is_active(self, config, make_schedule):
        job = enqueue(config)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.SUCCEEDED)
        make_schedule(
            config, cron="0 * * * *", overlap_policy=OverlapPolicy.SKIP, last_fired_at=at(9)
        )

        tick(now=at(10, 30))

        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 1


class TestIdempotency:
    """The unique constraint is the mechanism. There is no lock anywhere in this path."""

    def test_two_ticks_at_the_same_instant_enqueue_once(self, config, make_schedule):
        make_schedule(config, cron="0 * * * *", last_fired_at=at(9))

        first = tick(now=at(10, 30))
        second = tick(now=at(10, 30))

        assert len(first.enqueued) == 1
        assert second.enqueued == []
        assert Job.objects.count() == 1

    def test_a_crash_between_insert_and_advance_cannot_double_enqueue(self, config, make_schedule):
        """Simulate the crash: the Job exists, but `last_fired_at` never moved.

        `overlap_policy=allow` on purpose — with `skip` the overlap check would absorb the second
        fire before it ever reached the insert, and this test is about the constraint itself.
        """
        schedule = make_schedule(
            config, cron="0 * * * *", overlap_policy=OverlapPolicy.ALLOW, last_fired_at=at(9)
        )
        tick(now=at(10, 30))
        Schedule.objects.filter(pk=schedule.pk).update(last_fired_at=at(9))

        report = tick(now=at(10, 30))

        assert report.skipped_duplicate == 1
        assert Job.objects.count() == 1
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(10)

    def test_repeated_ticks_over_the_same_window_stay_at_one_job_per_occurrence(
        self, config, make_schedule
    ):
        make_schedule(
            config,
            cron="0 * * * *",
            overlap_policy=OverlapPolicy.ALLOW,
            catchup_policy=CatchupPolicy.FIRE_MISSED,
            last_fired_at=at(9),
        )

        for _ in range(5):
            tick(now=at(12, 30))

        fire_times = sorted(Job.objects.values_list("fire_time", flat=True))
        assert fire_times == [at(10), at(11), at(12)]

    def test_manual_runs_are_untouched_by_the_constraint(self, config, make_schedule):
        make_schedule(config, cron="0 * * * *", last_fired_at=at(9))
        tick(now=at(10, 30))

        enqueue(config)
        enqueue(config)

        assert Job.objects.filter(origin=JobOrigin.MANUAL).count() == 2


class TestCatchupThroughTick:
    def test_fire_missed_enqueues_every_occurrence(self, config, make_schedule):
        make_schedule(
            config,
            cron="0 * * * *",
            overlap_policy=OverlapPolicy.ALLOW,
            catchup_policy=CatchupPolicy.FIRE_MISSED,
            last_fired_at=at(9),
        )

        report = tick(now=at(12, 30))

        assert len(report.enqueued) == 3
        assert sorted(Job.objects.values_list("fire_time", flat=True)) == [at(10), at(11), at(12)]

    def test_skip_to_now_enqueues_only_the_latest(self, config, make_schedule):
        schedule = make_schedule(
            config,
            cron="0 * * * *",
            catchup_policy=CatchupPolicy.SKIP_TO_NOW,
            last_fired_at=at(9),
        )

        report = tick(now=at(12, 30))

        assert len(report.enqueued) == 1
        assert Job.objects.get().fire_time == at(12)
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(12)


def test_the_scheduler_never_executes_anything(config, make_schedule):
    make_schedule(config, cron="0 * * * *", last_fired_at=at(9))

    tick(now=at(10, 30))

    job = Job.objects.get()
    assert job.status == JobStatus.PENDING
    assert job.started_at is None
    assert job.claimed_by == ""


def test_available_at_matches_the_fire_time(config, make_schedule):
    make_schedule(config, cron="0 * * * *", last_fired_at=at(9))
    tick(now=at(10, 30))
    assert Job.objects.get().available_at == at(10)


def test_run_scheduler_command_reports_a_summary(config, make_schedule, capsys):
    from django.core.management import call_command

    make_schedule(config, cron="* * * * *", last_fired_at=timezone.now() - timedelta(minutes=5))
    call_command("run_scheduler")

    assert "enqueued=" in capsys.readouterr().out
