"""The runner contract (§8).

Runners are **not opaque**. A runner receives a context and hands back a structured result, so the
worker never has to guess what happened and never has to reach inside a collector.

Two rules shape everything here:

1. **Cooperative cancellation.** A runner must call `ctx.check_cancelled()` at its own safe points
   — between batches, pages, files. Nothing kills a runner from outside; a runner that never
   checks cannot be stopped, and that is a bug in the runner.
2. **No framework.** This module knows nothing about Django, the database, or the Job table.
   `RunContext` is abstract; `execution` supplies the concrete one. That is what keeps
   `collectors` a leaf package.

Secrets never arrive through parameters. Parameters carry a credential *reference* and the runner
asks the context to resolve it at execution time (§4).
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

__all__ = [
    "Cancelled",
    "CredentialMissing",
    "RunContext",
    "RunResult",
    "Runner",
]


class Cancelled(Exception):
    """Raised by `RunContext.check_cancelled()` when a stop was requested.

    A runner may let it propagate (the usual case) or catch it to flush partial work and then
    re-raise. Swallowing it and continuing defeats cancellation.
    """


class CredentialMissing(LookupError):
    """A credential reference did not resolve at execution time.

    This is an environment problem, not a parameter problem: the snapshot is still valid, the
    secret store just does not hold that name right now.
    """


@dataclass(frozen=True, slots=True)
class RunResult:
    """What a run produced. The worker writes these straight onto the Job."""

    status: str
    result: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    structured_error: dict[str, Any] | None = None

    SUCCEEDED: ClassVar[str] = "succeeded"
    FAILED: ClassVar[str] = "failed"
    CANCELLED: ClassVar[str] = "cancelled"

    @classmethod
    def success(
        cls, result: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None
    ) -> RunResult:
        return cls(status=cls.SUCCEEDED, result=result or {}, metrics=metrics or {})

    @classmethod
    def failure(
        cls,
        *,
        type: str,
        message: str,
        trace: str = "",
        result: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> RunResult:
        """A run that failed for a reason the runner understands.

        Prefer this over raising: a returned failure carries partial metrics and a stable error
        `type` the operator can filter on. Raising is for the unexpected — the worker turns it
        into a failure with `type="unhandled"`.
        """
        return cls(
            status=cls.FAILED,
            result=result or {},
            metrics=metrics or {},
            structured_error={"type": type, "message": message, "trace": trace},
        )

    @classmethod
    def cancelled(
        cls, result: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None
    ) -> RunResult:
        return cls(
            status=cls.CANCELLED,
            result=result or {},
            metrics=metrics or {},
            structured_error={"type": "cancelled", "message": "cancelled on request", "trace": ""},
        )


class RunContext(abc.ABC):
    """Everything a run may touch outside itself.

    Constructed from the Job **snapshot** alone. Nothing here can read mutable Config state — that
    is the snapshot-completeness invariant, expressed as an API rather than as a rule people are
    asked to remember.
    """

    def __init__(
        self,
        *,
        job_id: int,
        attempt_no: int,
        collector_key: str,
        parameters: Mapping[str, Any],
        logger: logging.Logger | None = None,
    ) -> None:
        self.job_id = job_id
        self.attempt_no = attempt_no
        self.collector_key = collector_key
        self.parameters: Mapping[str, Any] = dict(parameters)
        self.logger = logger or logging.getLogger(f"collectors.{collector_key}")

    @abc.abstractmethod
    def is_cancel_requested(self) -> bool:
        """Has someone asked this run to stop? Cheap enough to call between batches."""

    @abc.abstractmethod
    def resolve_credential(self, reference: str) -> str:
        """Turn a credential *reference* into the actual secret, now, at execution time.

        Raises `CredentialMissing` when the reference does not resolve.
        """

    @abc.abstractmethod
    def extend_lease(self, seconds: int | None = None) -> None:
        """Push the claim's expiry out — for runs that can legitimately outlive the lease.

        One UPDATE, called rarely. This is not a heartbeat: prefer a generous lease and few calls.
        """

    def open_lot_sink(self) -> Any | None:
        """Storage for the items this run collects, or `None` if the deployment keeps none.

        Deliberately the context's job rather than the runner's. A runner lives in `collectors`,
        which may not import Django, so it cannot build something that writes to a table; only
        `execution` can. Returning `None` is a real answer, not a failure — a run then counts what
        it found and discards it.

        Not abstract on purpose: a collector that stores nothing needs no opinion here.
        """
        return None

    def check_cancelled(self) -> None:
        """The cancellation checkpoint. Call it at every safe point."""
        if self.is_cancel_requested():
            raise Cancelled(f"job {self.job_id} cancelled on request")


class Runner(abc.ABC):
    """One collector's implementation. Exactly one per key — no version axis."""

    key: ClassVar[str]

    @abc.abstractmethod
    def run(self, ctx: RunContext) -> RunResult:
        """Do the collection. Return a `RunResult`; raise only for the genuinely unexpected."""
