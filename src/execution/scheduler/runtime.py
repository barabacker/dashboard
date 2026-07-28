"""The scheduler (§10).

It produces work and nothing else — it never executes a collector, and it shares the *same*
enqueue function as "Run now". A tick is: find due schedules → apply the overlap and catch-up
policies → enqueue → advance `last_fired_at`.

**Idempotency, and why there is no lock.** Job creation and the `last_fired_at` advance happen in
one transaction, and `(schedule_id, fire_time)` carries a unique constraint. Two schedulers racing,
a cron overlapping itself, a crash between the insert and the advance — every one of those ends in
either a clean insert or an `IntegrityError` that means "someone already realised this occurrence".
Correctness comes from the constraint, not from coordination.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from control.models import Config, Job, JobOrigin, JobStatus, OverlapPolicy, Schedule
from control.services import EnqueueRefused, enqueue
from execution.scheduler.occurrences import DEFAULT_MAX_CATCHUP, due_occurrences

logger = logging.getLogger(__name__)


@dataclass
class TickReport:
    """What one tick did. Returned rather than only logged so tests and operators see the same."""

    considered: int = 0
    enqueued: list[int] = field(default_factory=list)
    skipped_overlap: int = 0
    skipped_duplicate: int = 0
    skipped_not_runnable: int = 0
    bootstrapped: int = 0
    refused: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"schedules={self.considered} enqueued={len(self.enqueued)} "
            f"overlap_skips={self.skipped_overlap} duplicates={self.skipped_duplicate} "
            f"not_runnable={self.skipped_not_runnable} bootstrapped={self.bootstrapped} "
            f"refused={len(self.refused)}"
        )


def tick(*, now: datetime | None = None, max_catchup: int = DEFAULT_MAX_CATCHUP) -> TickReport:
    """One scheduling pass. Safe to run concurrently with itself."""
    now = now or timezone.now()
    report = TickReport()

    schedules = (
        Schedule.objects.filter(enabled=True).select_related("config").order_by("pk").iterator()
    )

    for schedule in schedules:
        report.considered += 1
        _process_schedule(schedule, now=now, max_catchup=max_catchup, report=report)

    logger.info("scheduler tick: %s", report.summary())
    return report


def _process_schedule(
    schedule: Schedule, *, now: datetime, max_catchup: int, report: TickReport
) -> None:
    config = schedule.config

    if schedule.last_fired_at is None:
        # First sight of this schedule. Anchor it at now instead of back-filling from the epoch.
        Schedule.objects.filter(pk=schedule.pk).update(last_fired_at=now)
        report.bootstrapped += 1
        return

    if not config.is_runnable:
        # A disabled or archived Config is an explicit "do not run". Advance the cursor anyway so
        # re-enabling it later does not unleash every occurrence that went by in the meantime.
        Schedule.objects.filter(pk=schedule.pk).update(last_fired_at=now)
        report.skipped_not_runnable += 1
        return

    for fire_time in due_occurrences(schedule, now=now, max_catchup=max_catchup):
        _fire(schedule, config, fire_time=fire_time, report=report)


def _fire(schedule: Schedule, config: Config, *, fire_time: datetime, report: TickReport) -> None:
    # Only `skip` changes what the scheduler does. `queue` and `allow` both enqueue — under
    # Option A they are indistinguishable at runtime, because keeping a queued run from
    # overlapping needs the per-stream claim predicate from Option B. See the "Known limitation"
    # note in CLAUDE.md before treating `queue` as mutual exclusion.
    if schedule.overlap_policy == OverlapPolicy.SKIP and _has_active_job(config):
        # Drop the occurrence, but still move the cursor past it — otherwise it stays "due"
        # forever and fires the moment the current run ends.
        Schedule.objects.filter(pk=schedule.pk).update(last_fired_at=fire_time)
        report.skipped_overlap += 1
        logger.info(
            "schedule %s: occurrence %s skipped, config %s still has an active job",
            schedule.pk,
            fire_time.isoformat(),
            config.pk,
        )
        return

    with transaction.atomic():
        try:
            with transaction.atomic():
                job = enqueue(
                    config,
                    origin=JobOrigin.SCHEDULE,
                    schedule=schedule,
                    fire_time=fire_time,
                    available_at=fire_time,
                )
        except IntegrityError:
            # `(schedule_id, fire_time)` is taken: another scheduler already realised this exact
            # occurrence. Not an error — this is the guarantee working.
            job = None
            report.skipped_duplicate += 1
            logger.info(
                "schedule %s: occurrence %s already enqueued elsewhere",
                schedule.pk,
                fire_time.isoformat(),
            )
        except EnqueueRefused as exc:
            # The Config became unrunnable between the check above and here.
            report.refused.append(f"schedule {schedule.pk}: {exc}")
            job = None

        # In the same transaction as the insert: a crash cannot leave a Job without the advance,
        # and the advance without a Job is exactly what the duplicate branch handles.
        Schedule.objects.filter(pk=schedule.pk).update(last_fired_at=fire_time)

    if job is not None:
        report.enqueued.append(job.pk)
        logger.info(
            "schedule %s: occurrence %s -> job %s (%s)",
            schedule.pk,
            fire_time.isoformat(),
            job.pk,
            job.status,
        )


def _has_active_job(config: Config) -> bool:
    """Is a previous run for this Config still pending or running?

    Job→Config is a soft reference, so this is a plain query on `config_id`.
    """
    return Job.objects.filter(config_id=config.pk, status__in=JobStatus.active()).exists()
