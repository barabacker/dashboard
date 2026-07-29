"""parse_lots against the rus-on trade_view detail fixture."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector

from collectors.engine.sources.ruson.parsing.detail import parse_lots

FIXTURE = Path(__file__).parent / "fixtures" / "ruson" / "nistp_detail.html"

TRADE = {
    "trade_id": "68240",
    "trade_nid": "484796",
    "trade_number": "68240-ОАОФ",
    "trade_type": "ОАОФ",
    # listing-level debtor/organizer are only a fallback — the detail page's
    # party blocks are authoritative and take precedence when present.
    "debtor": "listing fallback debtor",
    "organizer": "listing fallback organizer",
    "detail_url": "https://nistp.ru/bankrot/trade_view.php?trade_nid=484796",
    "_source": "nistp",
}


def _sel() -> Selector:
    return Selector(text=FIXTURE.read_text(encoding="utf-8"))


def test_parse_lots_first_lot():
    lots = parse_lots(_sel(), TRADE)
    assert lots
    first = lots[0]
    assert first["lot_id"] == "68240_1"
    assert first["lot_num"] == "1"
    assert first["price"] == 1315000.0
    assert first["status"] == "Торги объявлены"
    assert first["bidding_date"] == "28.08.2026 15:00:00"
    assert first["event_date"] == "23.07.2026 15:00:00"
    assert first["trade_number"] == "68240-ОАОФ"
    # debtor/organizer read from the detail "Информация о должнике/об
    # организаторе" blocks, not the listing fallback in TRADE.
    assert first["debtor"] == "Ионов Павел Олегович"
    assert first["organizer"] == "Чахоян Кима Самвеловна"
    assert first["_source"] == "nistp"
    assert first["detail"]


def test_parse_lots_debtor_organizer_from_detail_when_listing_lacks_them():
    """promkonsalt: listing has no clean debtor/organizer, the detail does.

    The debtor block gives "Фамилия Имя Отчество"; the organizer block is
    absent, so the "Контактное лицо организатора торгов" ФИО is used.
    """
    fixture = Path(__file__).parent / "fixtures" / "ruson" / "promkonsalt_detail.html"
    sel = Selector(text=fixture.read_text(encoding="utf-8"))
    trade = {"trade_id": "3179", "trade_number": "3179-ОАОФ", "_source": "promkonsalt"}
    lots = parse_lots(sel, trade)
    assert lots
    assert lots[0]["debtor"] == "Бирюкова Людмила Юрьевна"
    assert lots[0]["organizer"] == "Черный Михаил Васильевич"


def test_parse_lots_falls_back_to_listing_party_fields():
    """With no detail party blocks, debtor/organizer come from the listing."""
    sel = Selector(
        text="<html><body><table><tr><th>Лот № 1</th></tr>"
        "<tr><td>Начальная цена</td><td>100</td></tr></table></body></html>"
    )
    lots = parse_lots(
        sel,
        {
            "trade_id": "1",
            "trade_number": "1-ОАОФ",
            "_source": "s",
            "debtor": "Листинговый Должник",
            "organizer": "Листинговый Организатор",
        },
    )
    assert lots
    assert lots[0]["debtor"] == "Листинговый Должник"
    assert lots[0]["organizer"] == "Листинговый Организатор"


def test_parse_lots_ignores_prose_mentioning_lot_number():
    """Prose ("…задаток, Лот № 1, должник…") must not be taken for a lot header.

    Regression: such a paragraph produced a phantom second lot with the same
    lot_id and no price — the source of the duplicate/null-price rows in the
    collected data.
    """
    fixture = Path(__file__).parent / "fixtures" / "ruson" / "nistp_detail_prose_lot.html"
    sel = Selector(text=fixture.read_text(encoding="utf-8"))
    lots = parse_lots(sel, {"trade_id": "68289", "trade_number": "68289-ОАОФ", "_source": "nistp"})
    assert len(lots) == 1
    assert lots[0]["lot_id"] == "68289_1"
    assert lots[0]["price"] == 140000.0


def test_parse_lots_promkonsalt_variant():
    # promkonsalt: plain <td> label/value (no class="label") and span.lot_title
    # instead of a <th> "Лот №" marker.
    fixture = Path(__file__).parent / "fixtures" / "ruson" / "promkonsalt_detail.html"
    sel = Selector(text=fixture.read_text(encoding="utf-8"))
    trade = {"trade_id": "3179", "trade_number": "3179-ОАОФ", "_source": "promkonsalt"}
    lots = parse_lots(sel, trade)
    assert lots
    first = lots[0]
    assert first["lot_id"] == "3179_1"
    assert first["price"] == 17550000.0
    assert first["status"] == "Торги объявлены"
    assert first["description"]
