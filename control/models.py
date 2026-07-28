"""All persistence for the whole system lives here.

`execution` owns runtime behavior and no models; it imports these. Keep framework glue thin and
put invariants that must always hold — terminal states, snapshot immutability, revision bumps —
in the model layer, where nothing can route around them.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


def _snapshot_values(names: Iterable[str], values: Sequence[Any]) -> dict[str, Any]:
    """Remember loaded field values for change detection.

    JSON fields are deep-copied: without that, mutating `config.parameters` in place would leave
    the "before" and "after" pointing at the same object and the change would go unnoticed.
    """
    return {
        name: copy.deepcopy(value) if isinstance(value, dict | list) else value
        for name, value in zip(names, values, strict=True)
    }


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"

    @classmethod
    def terminal(cls) -> frozenset[str]:
        return frozenset({cls.SUCCEEDED, cls.FAILED, cls.CANCELLED})

    @classmethod
    def active(cls) -> frozenset[str]:
        return frozenset({cls.PENDING, cls.RUNNING})


class OverlapPolicy(models.TextChoices):
    SKIP = "skip", "Skip — drop this fire if the previous run is still active"
    QUEUE = "queue", "Queue — enqueue anyway, it waits behind the active run"
    ALLOW = "allow", "Allow — enqueue and run concurrently"


class CatchupPolicy(models.TextChoices):
    FIRE_MISSED = "fire_missed", "Fire missed — enqueue every missed occurrence"
    SKIP_TO_NOW = "skip_to_now", "Skip to now — enqueue at most the latest occurrence"


class JobOrigin(models.TextChoices):
    MANUAL = "manual", "Manual"
    SCHEDULE = "schedule", "Schedule"


class Collector(models.Model):
    """A projection of collector *code* into the database.

    Deliberately lightweight: key, label, description, enabled. Version and parameter schema come
    from `collectors/` and are never editable here — storing them would make the DB a second,
    divergent source of truth. `manage.py sync_collectors` maintains these rows; they are
    disabled, never deleted.
    """

    key = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(
        default=True,
        help_text="Disabled collectors keep their history and their Configs; nothing new runs.",
    )
    synced_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.key})"


class Config(models.Model):
    """The primary business object: *what to collect*, authored by a human.

    Editable at any time. Editing never disturbs a running Job — the Job carries its own snapshot.
    Deletion is soft (`archived`) so history keeps referring to something.
    """

    #: Fields whose change means "the authored intent changed" and must bump `revision`.
    REVISIONED_FIELDS = ("name", "collector_key", "parameters", "enabled", "archived", "tags")

    name = models.CharField(max_length=200)
    collector_key = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Resolve-by-key. The concrete version is pinned at enqueue time, not here.",
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw authored parameters. Resolved against the collector version's schema at "
        "enqueue; the resolved form is what the Job snapshots.",
    )
    enabled = models.BooleanField(default=True)
    archived = models.BooleanField(
        default=False, help_text="Soft delete. An archived config never enqueues."
    )
    tags = models.JSONField(default=list, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_configs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_configs",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    revision = models.PositiveIntegerField(default=1, editable=False)

    # --- dashboard cache columns (§11) ------------------------------------------------
    # Written by the worker when a Job reaches a terminal state, read by list views. These are
    # denormalized caches, not a read model: the Job table remains the source of truth.
    last_status = models.CharField(
        max_length=16, choices=JobStatus.choices, blank=True, default="", editable=False
    )
    last_run_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_job_id = models.BigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["archived", "enabled"]),
            models.Index(fields=["collector_key"]),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Bump `revision` when authored intent changes — and only then.

        The worker writes the `last_*` cache columns with `update_fields`; that must not look like
        an edit, or every run would inflate the revision the snapshots are compared against.
        """
        update_fields = kwargs.get("update_fields")
        if self.pk is not None and self._revisioned_changed():
            touches_intent = update_fields is None or bool(
                set(update_fields) & set(self.REVISIONED_FIELDS)
            )
            if touches_intent:
                self.revision += 1
                if update_fields is not None:
                    kwargs["update_fields"] = list(set(update_fields) | {"revision"})
        super().save(*args, **kwargs)
        tracked = (*self.REVISIONED_FIELDS, "revision")
        self._loaded_values = _snapshot_values(tracked, [getattr(self, name) for name in tracked])

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = _snapshot_values(field_names, values)
        return instance

    def _revisioned_changed(self) -> bool:
        loaded = getattr(self, "_loaded_values", None)
        if loaded is None:
            return False
        return any(
            name in loaded and loaded[name] != getattr(self, name)
            for name in self.REVISIONED_FIELDS
        )

    @property
    def is_runnable(self) -> bool:
        """The two enqueue preconditions that live on the Config itself (§6)."""
        return self.enabled and not self.archived

    @classmethod
    def record_job_outcome(
        cls, *, config_id: int, job_id: int, status: str, finished_at: Any
    ) -> None:
        """Refresh the dashboard cache columns (§11) after a Job reached a terminal state.

        A direct UPDATE on purpose. It must not bump `revision` (this is not an authored change)
        and it must not touch `updated_at` (which should keep meaning "last edited"). The
        `last_run_at` guard keeps two concurrent runs from letting the older one win the race.
        """
        cls.objects.filter(pk=config_id).filter(
            Q(last_run_at__isnull=True) | Q(last_run_at__lte=finished_at)
        ).update(last_status=status, last_run_at=finished_at, last_job_id=job_id)


class Schedule(models.Model):
    """When to run a Config. A containment child: it dies with its Config.

    `last_fired_at` is the *only* produced-state echo allowed in `control`. Anything resembling a
    collection cursor belongs to execution, not here.
    """

    config = models.ForeignKey(Config, on_delete=models.CASCADE, related_name="schedules")
    cron = models.CharField(max_length=100, help_text="Standard 5-field cron expression.")
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text="IANA name. Cron occurrences are computed in this zone, stored in UTC.",
    )
    enabled = models.BooleanField(default=True)
    overlap_policy = models.CharField(
        max_length=16, choices=OverlapPolicy.choices, default=OverlapPolicy.SKIP
    )
    catchup_policy = models.CharField(
        max_length=16, choices=CatchupPolicy.choices, default=CatchupPolicy.SKIP_TO_NOW
    )
    last_fired_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Advanced in the same transaction that creates the Job.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["config__name", "cron"]
        indexes = [models.Index(fields=["enabled"])]

    def __str__(self) -> str:
        return f"{self.cron} [{self.timezone}]"

    def clean(self) -> None:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"timezone": f"unknown timezone {self.timezone!r}"}) from None

        from croniter import croniter

        if not croniter.is_valid(self.cron):
            raise ValidationError({"cron": f"invalid cron expression {self.cron!r}"})


class Job(models.Model):
    """One execution attempt of one Config, and the queue row that drives it.

    A separate aggregate, not a child of Config: it holds an immutable **snapshot** (§4) plus
    mutable execution state (§7). Everything a run needs is in the snapshot, so a Config edit —
    or an archive — mid-flight changes nothing about a run already in progress.

    The table *is* the queue. See `execution.queue.claim`.
    """

    #: Immutable once the row exists. Guarded in `save()`.
    SNAPSHOT_FIELDS = (
        "collector_key",
        "collector_version",
        "effective_parameters",
        "schema_version",
        "config_id",
        "config_revision",
    )

    # --- snapshot (§4) ----------------------------------------------------------------
    collector_key = models.CharField(max_length=100, editable=False)
    collector_version = models.CharField(max_length=32, editable=False)
    effective_parameters = models.JSONField(
        default=dict,
        editable=False,
        help_text="Raw params resolved through the version's schema: defaults applied, validated. "
        "Credential *references* only — never credential values.",
    )
    schema_version = models.IntegerField(default=0, editable=False)
    config_id = models.BigIntegerField(
        db_index=True,
        editable=False,
        help_text="Soft reference. No FK on purpose: Job history outlives Config lifecycle.",
    )
    config_revision = models.PositiveIntegerField(default=0, editable=False)

    # --- origin -----------------------------------------------------------------------
    origin = models.CharField(max_length=16, choices=JobOrigin.choices, default=JobOrigin.MANUAL)
    schedule_id = models.BigIntegerField(null=True, blank=True, editable=False)
    fire_time = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text="The scheduled occurrence this Job realises. Unique per schedule — that "
        "constraint, not a lock, is what makes scheduling idempotent.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_jobs",
        editable=False,
    )

    # --- mutable state / lease (§7) ---------------------------------------------------
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.PENDING)
    claimed_by = models.CharField(max_length=200, blank=True, default="")
    claimed_until = models.DateTimeField(null=True, blank=True)
    attempt_no = models.PositiveIntegerField(
        default=0,
        help_text="Executor handoffs, not collector retries. Incremented by every claim, "
        "including a reclaim after a lease expired.",
    )
    cancel_requested = models.BooleanField(default=False)
    priority = models.IntegerField(default=0, help_text="Higher runs first.")
    available_at = models.DateTimeField(default=timezone.now, db_index=True)

    # --- outcome (§8) -----------------------------------------------------------------
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    structured_error = models.JSONField(null=True, blank=True, help_text="{type, message, trace}")
    metrics = models.JSONField(default=dict, blank=True, help_text="{rows, bytes, calls, ...}")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule_id", "fire_time"],
                condition=Q(schedule_id__isnull=False),
                name="uniq_job_per_schedule_fire_time",
            ),
        ]
        indexes = [
            # The claim's pending branch.
            models.Index(
                fields=["-priority", "available_at"],
                condition=Q(status="pending"),
                name="job_claimable_pending_idx",
            ),
            # The claim's expired-lease branch — the dead-worker reclaim.
            models.Index(
                fields=["claimed_until"],
                condition=Q(status="running"),
                name="job_expired_lease_idx",
            ),
            models.Index(fields=["config_id", "-created_at"], name="job_by_config_idx"),
            models.Index(fields=["status", "-created_at"], name="job_by_status_idx"),
        ]

    def __str__(self) -> str:
        return f"Job #{self.pk} {self.collector_key} v{self.collector_version} [{self.status}]"

    def save(self, *args: Any, **kwargs: Any) -> None:
        loaded = getattr(self, "_loaded_values", None)
        if self.pk is not None and loaded is not None:
            self._assert_snapshot_unchanged(loaded)
            self._assert_terminal_not_mutated(loaded)
        super().save(*args, **kwargs)
        self._loaded_values = _snapshot_values(
            (*self.SNAPSHOT_FIELDS, "status"),
            [getattr(self, name) for name in (*self.SNAPSHOT_FIELDS, "status")],
        )

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = _snapshot_values(field_names, values)
        return instance

    def _assert_snapshot_unchanged(self, loaded: dict[str, Any]) -> None:
        changed = [
            name
            for name in self.SNAPSHOT_FIELDS
            if name in loaded and loaded[name] != getattr(self, name)
        ]
        if changed:
            raise ValueError(
                f"Job #{self.pk}: snapshot fields are immutable, refusing to change {changed}"
            )

    def _assert_terminal_not_mutated(self, loaded: dict[str, Any]) -> None:
        was = loaded.get("status")
        if was not in JobStatus.terminal():
            return
        if self.status != was:
            raise ValueError(
                f"Job #{self.pk}: {was} is terminal, refusing transition to {self.status}. "
                f"A retry is a new Job."
            )

    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.terminal()

    @property
    def is_active(self) -> bool:
        return self.status in JobStatus.active()

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
