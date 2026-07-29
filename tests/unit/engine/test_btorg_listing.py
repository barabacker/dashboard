"""parse_listing / parse_price / find_next_page against the btorg fixture."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector

from collectors.engine.sources.btorg.parsing.listing import (
    find_next_page,
    parse_listing,
    parse_price,
)

FIXTURE = Path(__file__).parent / "fixtures" / "btorg" / "atctrade_listing.html"


def _sel() -> Selector:
    return Selector(text=FIXTURE.read_text(encoding="utf-8"))


def test_parse_price():
    assert parse_price("280 000,00 руб, НДС не облагается") == 280000.0
    assert parse_price("1 234,56") == 1234.56
    assert parse_price(None) is None
    assert parse_price("нет данных") is None


def test_parse_listing_count():
    trades = parse_listing(_sel(), "atctrade")
    assert len(trades) == 15
    assert all(t["trade_id"] and t["purchase_id"] for t in trades)


def test_parse_listing_first_trade():
    first = parse_listing(_sel(), "atctrade")[0]
    assert first["trade_number"] == "12850-ОАОФ"
    assert first["trade_id"] == "12850"
    assert first["trade_type"] == "ОАОФ"
    assert first["purchase_id"] == "105448698"
    assert first["status"] == "объявлены"
    assert first["lots_url"] == "/etp/trade/inner-view-lots.html?perspective=inline&id=105448698"
    assert first["organizer"].startswith("Серова")
    assert first["debtor"] == "Летовальцева Любовь Николаевна"
    assert first["_source"] == "atctrade"


def test_find_next_page():
    assert find_next_page(_sel(), 1) == 2
    assert find_next_page(_sel(), 999) is None
