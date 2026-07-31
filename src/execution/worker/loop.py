"""The worker (§9).

A plain loop: claim → resolve the runner from the snapshot → execute → write the terminal state
and refresh the Config cache columns. The worker holds almost no logic; the logic lives in
runners. Several worker processes just compete for rows — there is nothing to coordinate.

What the worker does *not* do: retry. A run that reaches terminal `failed` stays failed. Retrying
is creating a new Job, and that is a human's or a schedule's decision.
"""

from __future__ import annotations

import logging
import signal
import time
import traceback
from types import FrameType

from django.conf import settings
from django.db import close_old_connections

from collectors import registry
from collectors.runners.base import Cancelled, RunResult
from control.models import Job
from execution.queue import LeaseLost, claim_job, finish_job
from execution.worker.context import DbRunContext

logger = logging.getLogger(__name__)


class Worker:
    """One worker process. Stateless between iterations; all state is in the Job row."""

    def __init__(
        self,
        *,
        worker_id: str,
        lease_seconds: int | None = None,
        poll_seconds: float | None = None,
        max_jobs: int | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds or settings.WORKER_LEASE_SECONDS
        self.poll_seconds = poll_seconds or settings.WORKER_POLL_SECONDS
        self.max_jobs = max_jobs
        self.jobs_done = 0
        self._stopping = False

    # --- loop -------------------------------------------------------------------------

    def install_signal_handlers(self) -> None:
        """Finish the job in hand, then exit. Stopping mid-run would only force a reclaim."""

        def _stop(signum: int, frame: FrameType | None) -> None:
            logger.info(
                "worker %s: signal %s received, finishing current job", self.worker_id, signum
            )
            self._stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _stop)

    def run_forever(self) -> None:
        logger.info(
            "worker %s: starting (lease=%ss poll=%ss max_jobs=%s)",
            self.worker_id,
            self.lease_seconds,
            self.poll_seconds,
            self.max_jobs if self.max_jobs is not None else "unlimited",
        )
        while not self._stopping:
            # Long-lived processes outlive database connections; drop dead ones each turn.
            close_old_connections()
            did_work = self.run_once()
            if self.max_jobs is not None and self.jobs_done >= self.max_jobs:
                logger.info("worker %s: reached max_jobs=%s", self.worker_id, self.max_jobs)
                break
            if not did_work and not self._stopping:
                time.sleep(self.poll_seconds)
        logger.info("worker %s: stopped after %s job(s)", self.worker_id, self.jobs_done)

    def run_once(self) -> bool:
        """Claim and execute at most one Job. Returns whether there was anything to do."""
        job = claim_job(worker_id=self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return False

        logger.info(
            "worker %s: claimed job %s (%s) attempt %s",
            self.worker_id,
            job.pk,
            job.collector_key,
            job.attempt_no,
        )
        self.execute(job)
        self.jobs_done += 1
        return True

    # --- one job ----------------------------------------------------------------------

    def execute(self, job: Job) -> None:
        """Run one claimed Job to a terminal state.

        Everything the run needs comes off `job`'s snapshot. Nothing here reads the Config.
        """
        # A Job reclaimed after someone asked it to stop: honour the request instead of starting.
        if job.cancel_requested:
            self._finish(job, RunResult.cancelled())
            return

        try:
            runner = registry.resolve(job.collector_key)
        except registry.UnknownCollector as exc:
            # The invariant that every collector key resolves to code was broken by a deploy — a
            # snapshot pointing at code that no longer exists. Fail loudly rather than guessing.
            logger.error("job %s: %s", job.pk, exc)
            self._finish(
                job,
                RunResult.failure(
                    type="runner_unresolved",
                    message=str(exc),
                    metrics={},
                ),
            )
            return

        ctx = DbRunContext(job, worker_id=self.worker_id, lease_seconds=self.lease_seconds)

        try:
            result = runner.run(ctx)
        except Cancelled:
            logger.info("job %s: cancelled at a runner checkpoint", job.pk)
            result = RunResult.cancelled()
        except LeaseLost:
            # Another executor owns this Job now. Anything we write would be a lie, and
            # `finish_job` would refuse it anyway — but returning here keeps that explicit.
            logger.warning("job %s: lease lost mid-run, abandoning without writing", job.pk)
            return
        except Exception as exc:  # noqa: BLE001 — a runner must never take the worker down
            logger.exception("job %s: unhandled error in runner", job.pk)
            result = RunResult.failure(
                type="unhandled",
                message=f"{type(exc).__name__}: {exc}",
                trace=traceback.format_exc(limit=20),
            )

        self._finish(job, result)

    def _finish(self, job: Job, result: RunResult) -> None:
        written = finish_job(
            job_id=job.pk,
            worker_id=self.worker_id,
            status=result.status,
            result=result.result,
            metrics=result.metrics,
            structured_error=result.structured_error,
        )
        if not written:
            # Lost the claim between running and finishing. The reclaiming executor owns the
            # outcome.
            return

        logger.info(
            "job %s: %s (%s)",
            job.pk,
            result.status,
            ", ".join(f"{k}={v}" for k, v in sorted(result.metrics.items())) or "no metrics",
        )
