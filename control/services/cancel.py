"""Cancellation request (§8), from the control side.

Two cases, one entry point:

* a **pending** Job is cancelled outright — it must simply never be claimed;
* a **running** Job only gets a *signal*. The runner polls it at its own safe points and stops;
  nothing here kills anything.

The pending case is a conditional UPDATE rather than read-modify-write, because a worker may be
claiming the very same row: the `status='pending'` predicate is what makes the two mutually
exclusive.
"""

from __future__ import annotations

from typing import Literal

from django.utils import timezone

from control.models import Job, JobStatus

CancelOutcome = Literal["cancelled", "signalled", "already_terminal"]


def request_cancel(job: Job) -> CancelOutcome:
    """Ask for `job` to stop. Returns what actually happened."""
    now = timezone.now()

    cancelled = Job.objects.filter(pk=job.pk, status=JobStatus.PENDING).update(
        status=JobStatus.CANCELLED,
        cancel_requested=True,
        finished_at=now,
        updated_at=now,
        structured_error={
            "type": "cancelled",
            "message": "cancelled before it was ever claimed",
            "trace": "",
        },
    )
    if cancelled:
        return "cancelled"

    signalled = Job.objects.filter(pk=job.pk, status=JobStatus.RUNNING).update(
        cancel_requested=True, updated_at=now
    )
    if signalled:
        return "signalled"

    return "already_terminal"
