"""The concrete `RunContext` a runner receives.

Built from the Job **snapshot** and nothing else. There is deliberately no way to reach the Config
from here: snapshot completeness stops being a rule people have to remember and becomes a shape of
the API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.db import connections

from collectors.runners.base import CredentialMissing, RunContext
from control.models import Job
from execution.queue import LeaseLost, read_cancel_flag, renew_lease
from execution.worker.lot_sink import DbLotSink

logger = logging.getLogger(__name__)

#: Cancellation is polled, not pushed. A runner may call `check_cancelled()` in a tight loop; this
#: floor keeps that from turning into a query storm while still stopping a run promptly.
_CANCEL_POLL_INTERVAL_SECONDS = 1.0


def _query[T](fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run one of this context's queries, even when the caller sits inside an event loop.

    A runner is entitled to own a loop, and the tender collectors do: `crawl_site` is
    `asyncio.run`, and the engine polls cancellation and renews the lease from inside its
    coroutines. Django refuses ORM access from any thread with a running loop, so the query is
    handed to a plain thread, which has none.

    The caller blocks while it runs. That is the intent, not a compromise — a crawl asking whether
    it has been cancelled has nothing better to do until it knows — and the cost is bounded by the
    poll floors above: one query a second, one lease renewal a minute.

    Two properties make this safe rather than clever. The thread closes its own connection, so a
    worker process that runs jobs for days does not accumulate one per call. And that connection
    sees only *committed* rows, which is fine precisely because both callers are single autocommit
    statements outside any transaction of ours — `claim_job` has already committed by the time a
    runner starts (see `execution.queue.claim`).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args, **kwargs)  # An ordinary synchronous runner: no thread, no cost.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="runcontext-db") as pool:
        return pool.submit(_and_close_the_connection, fn, *args, **kwargs).result()


def _and_close_the_connection[T](fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    try:
        return fn(*args, **kwargs)
    finally:
        # `connections` is thread-local, so this closes what this thread opened and nothing else.
        connections.close_all()


class DbRunContext(RunContext):
    def __init__(self, job: Job, *, worker_id: str, lease_seconds: int) -> None:
        super().__init__(
            job_id=job.pk,
            attempt_no=job.attempt_no,
            collector_key=job.collector_key,
            collector_version=job.collector_version,
            schema_version=job.schema_version,
            parameters=job.effective_parameters,
            logger=logging.getLogger(f"collectors.{job.collector_key}"),
        )
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._cancel_cached = job.cancel_requested
        self._cancel_checked_at = 0.0

    def is_cancel_requested(self) -> bool:
        if self._cancel_cached:
            return True
        now = time.monotonic()
        if now - self._cancel_checked_at < _CANCEL_POLL_INTERVAL_SECONDS:
            return False
        self._cancel_checked_at = now
        self._cancel_cached = _query(read_cancel_flag, self.job_id)
        return self._cancel_cached

    def open_lot_sink(self) -> DbLotSink:
        """The database sink. Built here because only `execution` may import models.

        One per run, carrying this Job's id so a stored lot records which run last saw it.
        """
        return DbLotSink(job_id=self.job_id)

    def resolve_credential(self, reference: str) -> str:
        """Secrets come from the environment at execution time, never from the snapshot (§4).

        The consequence, stated plainly: replaying an old Job uses whatever the secret store holds
        *today*. Rotating credentials are the one documented exception to reproducibility.
        """
        value = os.environ.get(reference)
        if not value:
            raise CredentialMissing(
                f"credential reference {reference!r} did not resolve from the environment"
            )
        return value

    def extend_lease(self, seconds: int | None = None) -> None:
        if not _query(
            renew_lease,
            job_id=self.job_id,
            worker_id=self._worker_id,
            lease_seconds=seconds or self._lease_seconds,
        ):
            raise LeaseLost(
                f"job {self.job_id}: lease expired and the Job was reclaimed by another executor"
            )
