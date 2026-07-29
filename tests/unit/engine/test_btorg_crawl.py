"""End-to-end btorg crawl over fixtures via a fake HTTP client (no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from collectors.engine.build import SiteSpec, build_parser_class
from collectors.engine.core.lot import Lot
from collectors.engine.core.spider import ParserContext
from collectors.engine.core.storage.contracts import ChangeStatus

FIX = Path(__file__).parent / "fixtures" / "btorg"
LISTING = (FIX / "atctrade_listing.html").read_text(encoding="utf-8")
LOTS = (FIX / "atctrade_lots.html").read_text(encoding="utf-8")


#: The site under test, built from a snapshot the way a runner builds it.
PARSER = build_parser_class(SiteSpec(engine="btorg", domain="https://atctrade.ru"))


class _Raw:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")


class _FakeHttp:
    """Listing fixture for list.html URLs, lots fixture for inner-view-lots."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _Raw:
        self.calls.append(url)
        if "inner-view-lots" in url:
            return _Raw(LOTS)
        return _Raw(LISTING)


class _Sink:
    def __init__(self) -> None:
        self.items: list[Lot] = []

    async def get_fingerprints(self, source: str, lot_ids: Any) -> dict[str, str]:
        return {}

    async def save(self, item: Lot) -> ChangeStatus:
        self.items.append(item)
        return ChangeStatus.NEW


def test_btorg_crawl_expands_trades_into_lots():
    sink = _Sink()
    http = _FakeHttp()
    ctx = ParserContext(http=http, params={"max_pages": "1"}, lot_sink=sink)
    parser = PARSER(ctx)

    total = asyncio.run(parser.crawl())

    # 15 trades on page 1, the lots fixture has 1 lot each -> 15 items.
    assert total == 15
    assert len(sink.items) == 15
    assert any("inner-view-lots" in c for c in http.calls)  # dived for lots
    assert not any("page=2" in c for c in http.calls)  # max_pages=1 stopped paging
    first = sink.items[0]
    assert first.lot_id == "12850_1"
    assert first.price == 280000.0
    assert first.status == "объявлены"
    assert first.trade_number == "12850-ОАОФ"
    assert first.debtor == "Летовальцева Любовь Николаевна"
    assert first.extra
