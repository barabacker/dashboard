"""End-to-end rus-on crawl over fixtures via a fake HTTP client (no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from parsel import Selector

from collectors.engine.build import SiteSpec, build_parser_class
from collectors.engine.core.lot import Lot
from collectors.engine.core.parsing import is_active_status
from collectors.engine.core.spider import ParserContext
from collectors.engine.core.storage.contracts import ChangeStatus
from collectors.engine.sources.ruson.parsing.listing import parse_listing

FIX = Path(__file__).parent / "fixtures" / "ruson"
LISTING = (FIX / "nistp_listing.html").read_text(encoding="utf-8")
DETAIL = (FIX / "nistp_detail.html").read_text(encoding="utf-8")


#: The site under test, built from a snapshot the way a runner builds it.
PARSER = build_parser_class(SiteSpec(engine="ruson", domain="https://nistp.ru"))


class _Raw:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.content = text.encode("utf-8")


class _FakeHttp:
    """Listing fixture for trade_list URLs, detail fixture for trade_view."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _Raw:
        self.calls.append(url)
        if "trade_view.php" in url:
            return _Raw(DETAIL)
        return _Raw(LISTING)


class _Sink:
    def __init__(self) -> None:
        self.items: list[Lot] = []

    async def get_fingerprints(self, source: str, lot_ids: Any) -> dict[str, str]:
        return {}

    async def save(self, item: Lot) -> ChangeStatus:
        self.items.append(item)
        return ChangeStatus.NEW


def test_ruson_crawl_expands_trades_into_lots():
    sink = _Sink()
    http = _FakeHttp()
    ctx = ParserContext(http=http, params={"max_pages": "1"}, lot_sink=sink)
    parser = PARSER(ctx)

    total = asyncio.run(parser.crawl())

    # 20 distinct trades on page 1, the detail fixture has 1 lot each -> 20 items.
    assert total == 20
    assert len(sink.items) == 20
    assert any("trade_view.php" in c for c in http.calls)  # dived to detail
    assert not any("pagenum=2" in c for c in http.calls)  # max_pages=1 stopped paging
    first = sink.items[0]
    assert first.lot_id == "68240_1"
    assert first.price == 1315000.0
    assert first.status == "Торги объявлены"
    # organizer/debtor are carried from the listing columns through to the Lot.
    assert first.trade_number == "68240-ОАОФ"
    assert first.debtor == "Ионов Павел Олегович"
    assert first.organizer == "Чахоян Кима Самвеловна"
    assert first.extra


def test_ruson_crawl_pages_through_archive_without_diving():
    """Finished trades are not fetched, but paging continues past them.

    Deep pages can still hold the odd live trade (measured on aukcioncenter /
    nistp), so the archive is paged through — only the dive is skipped.
    """

    class _ArchiveHttp(_FakeHttp):
        async def request(self, method: str, url: str, **kwargs: Any) -> _Raw:
            raw = await super().request(method, url, **kwargs)
            if "trade_view.php" not in url:
                return _Raw(raw.text.replace("Торги объявлены", "Торги завершены"))
            return raw

    sink = _Sink()
    http = _ArchiveHttp()
    ctx = ParserContext(http=http, params={"max_pages": "3"}, lot_sink=sink)
    parser = PARSER(ctx)

    asyncio.run(parser.crawl())

    assert not any("trade_view.php" in c for c in http.calls)  # nothing dived
    assert not sink.items
    assert any("pagenum=2" in c for c in http.calls)  # but paging continued


def test_ruson_crawl_collects_live_trades_on_an_archive_page():
    """A lone live trade deep in the archive is still collected."""

    # Mark most rows finished, leaving a handful live among them.
    mostly_archive = LISTING.replace("Торги объявлены", "Торги завершены", 17)
    trades = parse_listing(Selector(text=mostly_archive), "nistp")
    live = [t for t in trades if is_active_status(t.get("status"))]
    assert 0 < len(live) < len(trades)  # the fixture really is a mix

    class _MostlyArchiveHttp(_FakeHttp):
        async def request(self, method: str, url: str, **kwargs: Any) -> _Raw:
            raw = await super().request(method, url, **kwargs)
            return raw if "trade_view.php" in url else _Raw(mostly_archive)

    sink = _Sink()
    http = _MostlyArchiveHttp()
    ctx = ParserContext(http=http, params={"max_pages": "1"}, lot_sink=sink)
    parser = PARSER(ctx)

    asyncio.run(parser.crawl())

    # exactly the live trades were fetched — the finished ones were skipped
    assert len([c for c in http.calls if "trade_view.php" in c]) == len(live)
    assert len(sink.items) == len(live)


def test_ruson_crawl_dedupes_trades_across_pages():
    """The same listing served on pages 1 and 2 must dive each trade once.

    Regression for the cross-page duplicate-lot_id bug (crawl-level _seen_trades).
    """
    sink = _Sink()
    http = _FakeHttp()  # serves the same LISTING for every trade_list URL
    ctx = ParserContext(http=http, params={"max_pages": "2"}, lot_sink=sink)
    parser = PARSER(ctx)

    asyncio.run(parser.crawl())

    detail_calls = [c for c in http.calls if "trade_view.php" in c]
    # 20 distinct trades: dived exactly once even though the pager advanced to
    # page 2 with identical content (without dedup this would be 40).
    assert len(detail_calls) == 20
    assert len(detail_calls) == len(set(detail_calls))
    assert len(sink.items) == 20
    assert any("pagenum=2" in c for c in http.calls)  # page 2 was fetched
