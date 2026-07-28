"""The concrete `RunContext` a runner receives.

Built from the Job **snapshot** and nothing else. There is deliberately no way to reach the Config
from here: snapshot completeness stops being a rule people have to remember and becomes a shape of
the API.
"""

from __future__ import annotations

import logging
import os
import time

from collectors.runners.base import CredentialMissing, RunContext
from control.models import Job
from execution.queue import LeaseLost, read_cancel_flag, renew_lease

logger = logging.getLogger(__name__)

#: Cancellation is polled, not pushed. A runner may call `check_cancelled()` in a tight loop; this
#: floor keeps that from turning into a query storm while still stopping a run promptly.
_CANCEL_POLL_INTERVAL_SECONDS = 1.0


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
        self._cancel_cached = read_cancel_flag(self.job_id)
        return self._cancel_cached

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
        if not renew_lease(
            job_id=self.job_id,
            worker_id=self._worker_id,
            lease_seconds=seconds or self._lease_seconds,
        ):
            raise LeaseLost(
                f"job {self.job_id}: lease expired and the Job was reclaimed by another executor"
            )
