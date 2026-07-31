"""`tender_<engine>` — crawl one trading platform.

One runner per parser family, all four sharing this implementation: the difference between them
is which engine class the site is crawled with, and that is a single attribute. The site itself
is not code — it arrives in the snapshot as `domain` / `listing_path` / TLS parameters.

The runner is the seam between the job control and the engine. It owns three translations and
nothing else:

* snapshot parameters → a `SiteSpec` plus the engine's own string-keyed params;
* the Job's cancellation flag and lease → the two callables `ParserContext` accepts;
* crawl counts → a `RunResult`.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from curl_cffi.requests.exceptions import RequestException

from collectors.engine import (
    CountingSink,
    CrawlOutcome,
    LotSink,
    SiteSpec,
    UnknownEngine,
    crawl_site,
)
from collectors.runners.base import RunContext, Runner, RunResult
from collectors.schemas.tender import ENGINE_KEYS, UnknownCertificate, collector_key

#: How often the lease is pushed out during a crawl. One UPDATE a minute is nothing next to the
#: HTTP traffic, and it keeps a long crawl from being reclaimed under a generous lease without
#: turning the engine's per-request hook into a query storm (§7: not a heartbeat subsystem).
LEASE_RENEW_INTERVAL_SECONDS = 60.0


class _JobControl:
    """The Job's cancellation flag and lease, exposed as the two callables the engine takes.

    Also the reason a lost lease stops a crawl promptly: `extend_lease` raises from inside an
    engine worker, where an exception would only be collected and the crawl would keep fetching
    pages it can no longer write. Here the failure is latched, `should_stop` starts returning
    True, and the runner re-raises once the crawl has wound down.
    """

    def __init__(self, ctx: RunContext, *, renew_interval: float) -> None:
        self._ctx = ctx
        self._renew_interval = renew_interval
        self._renewed_at = 0.0
        self.failure: BaseException | None = None

    def should_stop(self) -> bool:
        if self.failure is not None:
            return True
        return self._ctx.is_cancel_requested()

    def heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._renewed_at < self._renew_interval:
            return
        self._renewed_at = now
        try:
            self._ctx.extend_lease()
        except Exception as exc:  # noqa: BLE001 — latched and re-raised by the runner
            self.failure = exc


class TenderSiteRunner(Runner):
    """Crawl one site of one parser family. Subclasses set `engine` and `key`."""

    engine: ClassVar[str]

    def run(self, ctx: RunContext) -> RunResult:
        params = ctx.parameters
        try:
            spec = SiteSpec(
                engine=self.engine,
                domain=str(params["domain"]),
                listing_path=str(params.get("start_url") or ""),
                extra_ca_cert=str(params.get("extra_ca_cert") or ""),
                skip_tls_verify=bool(params.get("skip_tls_verify")),
            )
        except (UnknownEngine, ValueError) as exc:
            # The snapshot cannot describe a site. Not a network problem and not worth a
            # traceback — the parameters are simply wrong.
            return RunResult.failure(type="site_invalid", message=str(exc))

        control = _JobControl(ctx, renew_interval=LEASE_RENEW_INTERVAL_SECONDS)

        sink = self._sink(ctx, params)

        try:
            outcome = crawl_site(
                spec,
                params=_engine_params(params),
                sink=sink,
                should_stop=control.should_stop,
                heartbeat=control.heartbeat,
                log=ctx.logger.info,
            )
        except UnknownCertificate as exc:
            return RunResult.failure(type="certificate_missing", message=str(exc))
        except RequestException as exc:
            # The site did not answer after the client's own retries. Expected often enough to
            # deserve a stable type an operator can filter on, rather than "unhandled".
            return RunResult.failure(
                type="site_unreachable",
                message=f"{type(exc).__name__}: {exc}",
                result={"source": spec.source, "start_url": spec.start_url},
            )

        if control.failure is not None:
            # The lease is gone: another executor owns this Job. Let the worker decide what that
            # means — writing an outcome from here would be writing over someone else's run.
            raise control.failure

        return _to_result(outcome, stored=not isinstance(sink, CountingSink) and sink is not None)

    def _sink(self, ctx: RunContext, params: Any) -> LotSink | None:
        """Where the collected lots go: the context's storage, a counting sink, or nowhere.

        `None` is not "collect nothing": it is what tells the fogsoft engine that no stored
        fingerprint can differ, so no listing row is worth a detail request. That check comes
        first for exactly that reason — handing storage to a run that was asked to skip the detail
        pages would undo the saving it was asked for. The dive engines have no such choice, their
        lots only exist on the detail page.

        Failing that, whatever the context offers. A `CountingSink` is the fallback rather than
        `None`, because it answers "nothing known" to every fingerprint query — which is what
        makes a storage-less run a real crawl instead of a truncated one.
        """
        if self.engine == "fogsoft" and not params.get("fetch_details", True):
            return None
        offered = ctx.open_lot_sink()
        return CountingSink() if offered is None else offered


def _engine_params(params: Any) -> dict[str, str]:
    """Typed snapshot parameters → the engine's string-keyed dict.

    The engine reads its params as strings (they used to come from a CLI and from job payloads);
    the schema resolves them as real types. Converting here keeps that boundary in one place.
    """
    engine_params: dict[str, str] = {
        "only_active": "1" if params.get("only_active", True) else "0",
        "concurrency": str(params.get("concurrency") or 1),
    }
    max_pages = params.get("max_pages") or 0
    if max_pages:
        engine_params["max_pages"] = str(max_pages)
    return engine_params


def _to_result(outcome: CrawlOutcome, *, stored: bool) -> RunResult:
    result = {
        "source": outcome.source,
        "start_url": outcome.start_url,
        "sample_lot_ids": list(outcome.sample),
        "stored": stored,
    }
    metrics = {
        "rows": outcome.lots,
        "calls": outcome.requests,
        "listing_pages": outcome.listing_pages,
    }
    if stored:
        # Only meaningful against storage: without it every lot reads as new by definition.
        metrics["new"] = outcome.new
        metrics["changed"] = outcome.changed
    if outcome.cancelled:
        return RunResult.cancelled(result=result, metrics=metrics)
    return RunResult.success(result=result, metrics=metrics)


def _runner_class(engine: str) -> type[TenderSiteRunner]:
    """One concrete implementation per engine.

    Generated rather than hand-written: four classes whose only difference is two strings are
    four chances for a typo, and the registry check in `collectors.registry` verifies each one
    lands under the key it declares.
    """
    return type(
        f"Tender{engine.capitalize()}",
        (TenderSiteRunner,),
        {
            "engine": engine,
            "key": collector_key(engine),
            "__doc__": f"`{collector_key(engine)}` — crawl one {engine} site.",
            "__module__": __name__,
        },
    )


RUNNERS: dict[str, type[TenderSiteRunner]] = {
    collector_key(engine): _runner_class(engine) for engine in ENGINE_KEYS
}
