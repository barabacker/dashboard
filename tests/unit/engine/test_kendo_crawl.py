"""End-to-end kendo crawl over fixtures via a fake HTTP client (no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from collectors.engine.build import SiteSpec, build_parser_class
from collectors.engine.core.lot import Lot
from collectors.engine.core.spider import ParserContext
from collectors.engine.core.storage.contracts import ChangeStatus

FIX = Path(__file__).parent / "fixtures" / "kendo"
LISTING = (FIX / "listing_page1.html").read_text(encoding="utf-8")
DETAIL = (FIX / "detail_oaof.html").read_text(encoding="utf-8")


#: The site under test, built from a snapshot the way a runner builds it.
PARSER = build_parser_class(SiteSpec(engine="kendo", domain="https://trade-alliance.ru"))


class _Raw:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")


class _FakeHttp:
    """Serves the listing fixture for /lots URLs, the detail fixture otherwise."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _Raw:
        self.calls.append(url)
        if url.endswith("/lots") or "page=" in url:
            return _Raw(LISTING)
        return _Raw(DETAIL)


class _Sink:
    def __init__(self) -> None:
        self.items: list[Lot] = []

    async def get_fingerprints(self, source: str, lot_ids: Any) -> dict[str, str]:
        return {}

    async def save(self, item: Lot) -> ChangeStatus:
        self.items.append(item)
        return ChangeStatus.NEW


def test_kendo_crawl_expands_trades_into_lots():
    sink = _Sink()
    http = _FakeHttp()
    ctx = ParserContext(http=http, params={"max_pages": "1"}, lot_sink=sink)
    parser = PARSER(ctx)

    total = asyncio.run(parser.crawl())

    # 15 trades on page 1, each detail fixture has 2 lots -> 30 lot items.
    assert total == 30
    assert len(sink.items) == 30
    # dived into details, and max_pages=1 stopped pagination (no page=2 fetched).
    assert any("/oaof/" in c for c in http.calls)
    assert not any("page=2" in c for c in http.calls)
    # items are fogsoft-shaped: fingerprint keys present and populated.
    first = sink.items[0]
    assert first.lot_id == "10775_5"
    assert first.price == 6721200.0
    assert first.status == "Идет прием заявок"
    # semantic fields flow through the full pipeline (listing card -> detail -> Lot):
    assert first.trade_number == "10775–ОАОФ"
    assert first.debtor == "Баранов Виталий Витальевич"
    assert first.extra and first.attachments


def test_kendo_crawl_is_correct_under_higher_concurrency():
    """Raising in-site concurrency must not change what is collected."""
    sink = _Sink()
    ctx = ParserContext(
        http=_FakeHttp(),
        params={"max_pages": "1", "concurrency": "5"},
        lot_sink=sink,
    )
    total = asyncio.run(PARSER(ctx).crawl())

    assert total == 30
    assert len(sink.items) == 30
    # no duplicates introduced by parallel workers
    assert len({it.lot_id for it in sink.items}) == 30
