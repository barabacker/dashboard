"""A crawl can be stopped and can report progress, without the engine knowing what a Job is.

Both hooks are plain callables on `ParserContext`. These tests drive them directly over the
kendo fixtures — the same fake HTTP client the crawl tests use.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from collectors.engine import SiteSpec, build_parser_class
from collectors.engine.core.spider import ParserContext

FIX = Path(__file__).parent / "fixtures" / "kendo"
LISTING = (FIX / "listing_page1.html").read_text(encoding="utf-8")
DETAIL = (FIX / "detail_oaof.html").read_text(encoding="utf-8")

PARSER = build_parser_class(SiteSpec(engine="kendo", domain="https://trade-alliance.ru"))


class _Raw:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")


class _FakeHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _Raw:
        self.calls.append(url)
        if url.endswith("/lots") or "page=" in url:
            return _Raw(LISTING)
        return _Raw(DETAIL)


def _run(**ctx_kwargs: Any):
    http = _FakeHttp()
    parser = PARSER(ParserContext(http=http, params={"max_pages": "1"}, **ctx_kwargs))
    total = asyncio.run(parser.crawl())
    return parser, http, total


def test_a_crawl_nobody_stops_runs_to_completion():
    parser, http, total = _run(should_stop=lambda: False)

    assert parser.cancelled is False
    assert total == 30
    assert parser.listing_page_count == 1
    assert parser.request_count == len(http.calls)


def test_a_stop_request_winds_the_crawl_down():
    """Requests already queued are dropped, not fetched — that is what stopping means."""
    parser, http, total = _run(should_stop=lambda: True)

    assert parser.cancelled is True
    assert total == 0
    assert http.calls == []


def test_a_stop_mid_crawl_keeps_what_was_already_collected():
    calls: list[int] = []

    def should_stop() -> bool:
        # Let the listing page and a few dives through, then stop.
        calls.append(1)
        return len(calls) > 4

    parser, http, total = _run(should_stop=should_stop)

    assert parser.cancelled is True
    assert 0 < total < 30
    assert len(http.calls) < 16


def test_a_latched_stop_is_not_re_asked():
    asked = []

    def should_stop() -> bool:
        asked.append(1)
        return len(asked) > 2

    parser, _http, _total = _run(should_stop=should_stop)

    assert parser.cancelled is True
    # Once latched the predicate is never consulted again — the remaining queue is drained
    # without asking 15 more times.
    before = len(asked)
    assert parser.stop_requested() is True
    assert len(asked) == before


def test_the_heartbeat_fires_once_per_request():
    beats: list[int] = []

    parser, http, _total = _run(heartbeat=lambda: beats.append(1))

    assert len(beats) == parser.request_count == len(http.calls)
