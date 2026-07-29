"""The bridge between the async engine and a synchronous caller.

``crawl_site`` is the whole public surface a runner needs: hand it a site, get back counts. It
owns the event loop (``asyncio.run``) and the HTTP client's lifetime, and it takes the two job
control callbacks as plain functions so the engine never learns what a Job is.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from collectors.engine.build import SiteSpec, build_parser_class
from collectors.engine.core.spider import ParserContext
from collectors.engine.core.storage.counting import CountingSink
from collectors.engine.core.storage.sink import LotSink
from collectors.engine.http.factory import build_http_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    """What one crawl of one site produced."""

    source: str
    start_url: str
    lots: int = 0
    new: int = 0
    changed: int = 0
    requests: int = 0
    listing_pages: int = 0
    cancelled: bool = False
    sample: tuple[str, ...] = field(default_factory=tuple)


async def _crawl(
    spec: SiteSpec,
    params: dict[str, str],
    sink: LotSink | None,
    should_stop: Callable[[], bool] | None,
    heartbeat: Callable[[], None] | None,
    log: Callable[[str], object] | None,
) -> CrawlOutcome:
    parser_cls = build_parser_class(spec)

    async def _log(message: str) -> None:
        if log is not None:
            log(message)
        else:
            logger.info("[%s] %s", spec.source, message)

    http = build_http_client(parser_cls)
    async with http:
        ctx = ParserContext(
            http=http,
            params=params,
            lot_sink=sink,
            log=_log,
            job_name=spec.source,
            should_stop=should_stop,
            heartbeat=heartbeat,
        )
        parser = parser_cls(ctx)
        await parser.crawl()

    sample = tuple(sink.sample) if isinstance(sink, CountingSink) else ()
    return CrawlOutcome(
        source=spec.source,
        start_url=spec.start_url,
        lots=parser.item_count,
        new=parser.new_item_count,
        changed=parser.changed_item_count,
        requests=parser.request_count,
        listing_pages=parser.listing_page_count,
        cancelled=parser.cancelled,
        sample=sample,
    )


def crawl_site(
    spec: SiteSpec,
    *,
    params: dict[str, str] | None = None,
    sink: LotSink | None = None,
    should_stop: Callable[[], bool] | None = None,
    heartbeat: Callable[[], None] | None = None,
    log: Callable[[str], object] | None = None,
) -> CrawlOutcome:
    """Crawl one site to completion (or to a requested stop) and report the counts.

    ``sink`` is injected by the caller. ``None`` means "collect nothing and do not dive for
    details"; pass a `CountingSink` for a full crawl that stores nothing.
    """
    return asyncio.run(_crawl(spec, params or {}, sink, should_stop, heartbeat, log))
