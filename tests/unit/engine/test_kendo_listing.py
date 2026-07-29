"""parse_listing / find_next_page against the committed listing fixture."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector

from collectors.engine.sources.kendo.parsing.listing import (
    find_next_page,
    parse_listing,
    read_max_pages,
)

FIXTURE = Path(__file__).parent / "fixtures" / "kendo" / "listing_page1.html"


def _sel() -> Selector:
    return Selector(text=FIXTURE.read_text(encoding="utf-8"))


def test_parse_listing_card_count():
    trades = parse_listing(_sel(), "trade_alliance")
    assert len(trades) == 15


def test_parse_listing_first_card_fields():
    first = parse_listing(_sel(), "trade_alliance")[0]
    assert first["trade_id"] == "10775"
    assert first["trade_number"] == "10775–ОАОФ"
    assert first["detail_url"] == "/oaof/10775"
    assert first["status"] == "Идет прием заявок"
    assert first["bidding_date"] == "21.08.2026 17:00:00"
    assert first["event_date"] == "22.08.2026 12:00:00"
    assert first["trade_title"].startswith("Открытый аукцион")
    assert first["_source"] == "trade_alliance"


def test_find_next_page():
    assert find_next_page(_sel(), 1) == 2
    assert find_next_page(_sel(), 999) is None


def test_read_max_pages():
    assert read_max_pages({}) is None
    assert read_max_pages({"max_pages": "3"}) == 3
    assert read_max_pages({"max_pages": "x"}) is None
    assert read_max_pages({"max_pages": "0"}) is None
