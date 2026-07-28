"""Claim, lease, reclaim (§7).

Three ideas, and they are all in the SQL:

**The claim is one statement.** `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)`
picks exactly one row and marks it taken atomically. Competing workers skip each other's locked
rows instead of queueing behind them, so N workers do N times the work rather than serialising.

**The expired-lease branch is the dead-worker reclaim.** A row that is `running` with
`claimed_until < now` is claimable again. There is no reaper process to deploy, monitor or debug —
recovery is a disjunct in the WHERE clause.

**Reclaim is not retry.** `attempt_no` counts executor handoffs. A Job that reaches terminal
`failed` is never re-enqueued here; a retry is a new Job. That distinction is why history can tell
"the worker died three times" from "the collector failed once".

The claim predicate lives in exactly one function on purpose. If Option B (incremental collectors,
§17) is ever taken, its per-stream predicate is an edit to `_CLAIM_SQL` — not a rewrite of the hot
path scattered across the worker.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db import connection
from django.utils import timezone

from control.models import Job, JobStatus

logger = logging.getLogger(__name__)

_TABLE = Job._meta.db_table


class LeaseLost(RuntimeError):
    """This worker no longer owns the Job — someone reclaimed it after the lease expired.

    Whatever this process is doing is now duplicate work. It must stop and, above all, must not
    write a terminal state over the new executor's run.
    """


# One statement. Read it as: "take the best claimable row nobody else has locked, and mark it
# mine." The two disjuncts are the two ways a row becomes claimable.
_CLAIM_SQL = f"""
UPDATE {_TABLE} AS j
   SET status         = %(running)s,
       claimed_by     = %(worker_id)s,
       claimed_until  = %(lease_until)s,
       attempt_no     = j.attempt_no + 1,
       started_at     = %(now)s,
       updated_at     = %(now)s
 WHERE j.id = (
       SELECT c.id
         FROM {_TABLE} AS c
        WHERE (
                  c.status = %(pending)s
              AND c.available_at <= %(now)s
              AND c.cancel_requested = false
              )
           OR (
                  c.status = %(running)s
              AND c.claimed_until < %(now)s
              )
        ORDER BY c.priority DESC, c.available_at ASC, c.id ASC
          FOR UPDATE SKIP LOCKED
        LIMIT 1
       )
RETURNING j.id
"""


def claim_job(*, worker_id: str, lease_seconds: int) -> Job | None:
    """Take ownership of one Job, or return None if there is nothing to do.

    Runs in its own short transaction (a single autocommit statement) — execution happens well
    outside it, so a long collector never holds a row lock.

    `started_at` is reset on every claim: it marks when *this* attempt began, which is what makes
    the recorded duration describe the run that actually produced the result.
    """
    now = timezone.now()
    params = {
        "pending": JobStatus.PENDING,
        "running": JobStatus.RUNNING,
        "worker_id": worker_id,
        "lease_until": now + timedelta(seconds=lease_seconds),
        "now": now,
    }

    with connection.cursor() as cursor:
        cursor.execute(_CLAIM_SQL, params)
        row = cursor.fetchone()

    if row is None:
        return None
    return Job.objects.get(pk=row[0])


def renew_lease(*, job_id: int, worker_id: str, lease_seconds: int) -> bool:
    """Push the lease out. One UPDATE, guarded by ownership.

    Returns False when this worker no longer holds the claim. That is not an error condition to
    retry — it means another executor already took the Job over.
    """
    updated = Job.objects.filter(pk=job_id, claimed_by=worker_id, status=JobStatus.RUNNING).update(
        claimed_until=timezone.now() + timedelta(seconds=lease_seconds)
    )
    return bool(updated)


def read_cancel_flag(job_id: int) -> bool:
    """The cancellation signal, read straight from the row.

    Deliberately a plain SELECT rather than a signal bus or a heartbeat channel: cancellation is
    rare, cooperative, and polled at the runner's own safe points.
    """
    return Job.objects.filter(pk=job_id).values_list("cancel_requested", flat=True).first() or False


def finish_job(
    *,
    job_id: int,
    worker_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    structured_error: dict[str, Any] | None = None,
) -> bool:
    """Write the terminal state — but only if this worker still owns the Job.

    The ownership predicate is the whole point. A worker whose lease quietly expired mid-run is
    still holding a `Job` object and a result; without this guard it would stamp its outcome over
    the executor that legitimately reclaimed the row. Returns False in that case, and the caller
    discards its result.

    Terminal states are terminal: the `status='running'` predicate means this can never overwrite
    an outcome that was already recorded.
    """
    now = timezone.now()
    updated = Job.objects.filter(pk=job_id, claimed_by=worker_id, status=JobStatus.RUNNING).update(
        status=status,
        finished_at=now,
        updated_at=now,
        result=result or {},
        metrics=metrics or {},
        structured_error=structured_error,
        claimed_until=None,
    )
    if not updated:
        logger.warning(
            "job %s: refusing to write %s — worker %s no longer owns the claim",
            job_id,
            status,
            worker_id,
        )
    return bool(updated)
