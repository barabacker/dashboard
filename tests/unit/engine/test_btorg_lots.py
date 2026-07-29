"""parse_lots against the btorg inner-view-lots fixture."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector

from collectors.engine.sources.btorg.parsing.lots import parse_lots

FIXTURE = Path(__file__).parent / "fixtures" / "btorg" / "atctrade_lots.html"

TRADE = {
    "trade_id": "12850",
    "trade_number": "12850-ОАОФ",
    "trade_type": "ОАОФ",
    "status": "объявлены",
    "list_date": "23.07.2026 00:00",
    "debtor": "Иванов Иван Иванович",
    "organizer": "Серова Любовь Хабировна",
    "lots_url": "/etp/trade/inner-view-lots.html?perspective=inline&id=105448698",
    "_source": "atctrade",
}


def _sel() -> Selector:
    return Selector(text=FIXTURE.read_text(encoding="utf-8"))


def test_parse_lots_first_lot():
    lots = parse_lots(_sel(), TRADE)
    assert lots
    first = lots[0]
    assert first["lot_id"] == "12850_1"
    assert first["lot_num"] == "1"
    assert first["price"] == 280000.0
    assert first["status"] == "объявлены"
    assert first["trade_number"] == "12850-ОАОФ"
    assert first["debtor"] == "Иванов Иван Иванович"
    assert first["bidding_date"] == "23.07.2026 00:00"
    assert first["description"]
    assert first["_source"] == "atctrade"
    # the label/value blob captured the starting price row:
    assert any("Начальная цена" in k for k in first["detail"])
