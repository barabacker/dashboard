"""ParserContext — parser execution context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collectors.engine.core.storage.sink import LotSink
    from collectors.engine.http.client import HttpClient


@dataclass(slots=True)
class ParserContext:
    """Parser execution context: HTTP client, params, optional lot sink and log.

    `should_stop` and `heartbeat` are how the surrounding job control reaches into a crawl
    without the engine learning anything about it. Both are plain callables supplied by the
    caller:

    * `should_stop()` — a *predicate*, polled between requests. Returning True makes `crawl()`
      wind down and report `cancelled`; it never raises, so the engine needs no exception type
      from the layer above it.
    * `heartbeat()` — called between requests so a long crawl can push out whatever lease the
      caller holds. Throttling is the caller's business; the engine just calls it.
    """

    http: HttpClient
    params: dict[str, str] = field(default_factory=dict)
    lot_sink: LotSink | None = None
    log: Callable[[str], Awaitable[None]] | None = None
    job_name: str | None = None
    should_stop: Callable[[], bool] | None = None
    heartbeat: Callable[[], None] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
