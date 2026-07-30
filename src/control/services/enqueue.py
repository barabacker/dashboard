"""The single shared enqueue function (§6).

Both "Run now" and the scheduler come through here. That is the point: there is exactly one place
where a Config becomes a Job, so the preconditions and the snapshot contract cannot drift apart.

`control` may import `collectors.schemas` and nothing else from `collectors` — resolving a runner
is execution's business, and importing `collectors.runners` here would drag runner code into the
web process. The import-linter contract in `pyproject.toml` enforces it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

from collectors import schemas
from control.models import Collector, Config, Job, JobOrigin, JobStatus, Schedule


class InvalidParamsPolicy(Enum):
    """What to do when the Config's raw parameters do not satisfy the collector's schema.

    §6 allows either. Which one is right depends on who asked:

    * ``REFUSE`` — an interactive "Run now". The user is right there; tell them and change
      nothing.
    * ``RECORD_FAILURE`` — a scheduled fire. Nobody is watching, and a silently skipped run is
      worse than a visible failed one. This is what makes "a Config drifting out of step with the
      code fails fast, rather than silently" observable.

    Neither ever enqueues a *runnable* job with a mismatched schema.
    """

    REFUSE = "refuse"
    RECORD_FAILURE = "record_failure"


class EnqueueRefused(Exception):
    """No Job was created, and the caller is expected to surface why."""

    def __init__(self, reason: str, message: str, errors: Sequence[str] = ()) -> None:
        self.reason = reason
        self.errors = list(errors)
        super().__init__(message)


def enqueue(
    config: Config,
    *,
    origin: str = JobOrigin.MANUAL,
    requested_by: AbstractBaseUser | None = None,
    schedule: Schedule | None = None,
    fire_time: datetime | None = None,
    priority: int = 0,
    available_at: datetime | None = None,
    on_invalid_params: InvalidParamsPolicy | None = None,
) -> Job:
    """Turn a Config into a pending Job, snapshotting everything the run will need.

    Raises `EnqueueRefused` when the Config must not run at all, or — under
    `RECORD_FAILURE` — returns an already-`failed` Job when only the parameters are wrong.

    May raise `IntegrityError` when `(schedule, fire_time)` was already enqueued; that collision
    is the scheduler's idempotency guarantee, so the caller wraps this in a savepoint rather than
    checking first.
    """
    if on_invalid_params is None:
        on_invalid_params = (
            InvalidParamsPolicy.RECORD_FAILURE
            if origin == JobOrigin.SCHEDULE
            else InvalidParamsPolicy.REFUSE
        )

    # --- precondition 1: the Config is allowed to run at all --------------------------
    # `reason` stays an English code — it is an API, matched in tests and in CLAUDE.md. Only the
    # message is Russian, because only the message reaches a human.
    if config.archived:
        raise EnqueueRefused(
            "config_archived", f"Конфигурация {config.name!r} в архиве — запуск невозможен."
        )
    if not config.enabled:
        raise EnqueueRefused(
            "config_disabled", f"Конфигурация {config.name!r} отключена — запуск невозможен."
        )

    # --- precondition 2: the collector exists in code and is not deprecated ------------
    try:
        descriptor = schemas.get_collector(config.collector_key)
    except schemas.UnknownCollector:
        raise EnqueueRefused(
            "collector_unknown",
            f"Сборщика {config.collector_key!r} нет в кодовой базе — запускать нечего.",
        ) from None

    if not _collector_enabled(config.collector_key):
        raise EnqueueRefused(
            "collector_disabled",
            f"Сборщик {config.collector_key!r} выключен — новые задачи для него не создаются.",
        )

    # --- precondition 3: params are valid for the collector's current schema -----------
    try:
        effective = descriptor.resolve(config.parameters)
    except schemas.ParameterError as exc:
        if on_invalid_params is InvalidParamsPolicy.REFUSE:
            raise EnqueueRefused(
                "params_invalid",
                "параметры не подходят схеме сборщика",
                exc.errors,
            ) from None
        return _record_invalid_config_job(
            config=config,
            errors=exc.errors,
            origin=origin,
            requested_by=requested_by,
            schedule=schedule,
            fire_time=fire_time,
            priority=priority,
        )

    return Job.objects.create(
        # snapshot (§4): everything needed to reproduce the run from this row alone
        collector_key=config.collector_key,
        effective_parameters=effective,
        config_id=config.pk,
        config_revision=config.revision,
        # origin
        origin=origin,
        schedule_id=schedule.pk if schedule else None,
        fire_time=fire_time,
        requested_by=requested_by if getattr(requested_by, "pk", None) else None,
        # queue state
        status=JobStatus.PENDING,
        priority=priority,
        available_at=available_at or timezone.now(),
    )


def _collector_enabled(key: str) -> bool:
    """The projection's `enabled` flag is the operator's kill switch for a collector.

    A row that has not been synced yet is treated as enabled: the code is the source of truth and
    a missing projection row is a deployment gap, not a decision to disable.
    """
    return not Collector.objects.filter(key=key, enabled=False).exists()


def _record_invalid_config_job(
    *,
    config: Config,
    errors: Sequence[str],
    origin: str,
    requested_by: AbstractBaseUser | None,
    schedule: Schedule | None,
    fire_time: datetime | None,
    priority: int,
) -> Job:
    """A Job that is born terminal.

    It is never claimable (it is created `failed`, not `pending`), so no worker can run a
    mismatched schema. It exists so the failure is visible in history next to the runs that
    worked, and so `(schedule, fire_time)` is consumed — a broken schedule does not retry itself
    into a storm on the next tick.

    `effective_parameters` is empty on purpose: there is no valid resolution. The raw authored
    values are kept in `result` for diagnosis.
    """
    now = timezone.now()
    job = Job.objects.create(
        collector_key=config.collector_key,
        effective_parameters={},
        config_id=config.pk,
        config_revision=config.revision,
        origin=origin,
        schedule_id=schedule.pk if schedule else None,
        fire_time=fire_time,
        requested_by=requested_by if getattr(requested_by, "pk", None) else None,
        status=JobStatus.FAILED,
        priority=priority,
        available_at=now,
        started_at=now,
        finished_at=now,
        result={"raw_parameters": config.parameters},
        structured_error={
            "type": "config_invalid",
            "message": f"config invalid for collector {config.collector_key}",
            "trace": "",
            "errors": list(errors),
        },
    )
    # This Job is born terminal, so nothing downstream will ever refresh the cache columns.
    Config.record_job_outcome(
        config_id=config.pk, job_id=job.pk, status=job.status, finished_at=now
    )
    return job
