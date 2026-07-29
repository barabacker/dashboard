"""parse_lots / parse_main_info / parse_documents against the detail fixture."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector

from collectors.engine.sources.kendo.parsing.detail import (
    parse_documents,
    parse_lots,
    parse_main_info,
    parse_price,
)

FIXTURE = Path(__file__).parent / "fixtures" / "kendo" / "detail_oaof.html"

# parse_lots receives the trade_ctx that base.extract_lots builds: trade_number
# from the listing card, debtor parsed out of its "…, должник X" title tail.
TRADE = {
    "trade_id": "10775",
    "trade_number": "10775–ОАОФ",
    "debtor": "Баранов Виталий Витальевич",
    "trade_type": "ОАОФ",
    "bidding_date": "21.08.2026 17:00:00",
    "event_date": "22.08.2026 12:00:00",
    "_source": "trade_alliance",
}


def _sel() -> Selector:
    return Selector(text=FIXTURE.read_text(encoding="utf-8"))


def test_parse_price():
    assert parse_price("6 721 200.00") == 6721200.0
    assert parse_price("9 000.00") == 9000.0
    assert parse_price(None) is None
    assert parse_price("—") is None


def test_parse_lots_count_and_first_lot():
    lots = parse_lots(_sel(), TRADE)
    assert len(lots) == 2
    first = lots[0]
    assert first["lot_id"] == "10775_5"
    assert first["lot_num"] == "5"
    assert first["price"] == 6721200.0
    assert first["status"] == "Идет прием заявок"
    assert first["lot_url"].endswith("/oaof/10775/lots/3090")
    assert "М7-КРЕДИТ" in first["description"]
    assert first["trade_number"] == TRADE["trade_number"]
    assert first["debtor"] == TRADE["debtor"]
    assert first["bidding_date"] == "21.08.2026 17:00:00"
    assert first["_source"] == "trade_alliance"


def test_parse_lots_second_lot():
    lots = parse_lots(_sel(), TRADE)
    assert lots[1]["lot_id"] == "10775_6"
    assert lots[1]["price"] == 9000.0


def test_parse_main_info():
    info = parse_main_info(_sel())
    assert info.get("Статус торгов") == "идет прием заявок"
    assert len(info) >= 10


def test_parse_documents():
    docs = parse_documents(_sel())
    assert len(docs) == 2
    assert docs[0]["url"].startswith("http")
    assert docs[0]["name"]
