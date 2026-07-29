"""parse_listing across the rus-on listing variants + parse_price/find_next_page."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector

from collectors.engine.sources.ruson.parsing.listing import (
    find_next_page,
    parse_listing,
    parse_price,
)

FIX = Path(__file__).parent / "fixtures" / "ruson"


def _sel(name: str) -> Selector:
    return Selector(text=(FIX / name).read_text(encoding="utf-8"))


def test_parse_price():
    assert parse_price("1 315 000.00") == 1315000.0
    assert parse_price("65 750.00") == 65750.0
    assert parse_price(None) is None
    assert parse_price("—") is None


def test_nistp_data_href_variant():
    # table.data, per-trade rows, absolute <a href> detail link.
    trades = parse_listing(_sel("nistp_listing.html"), "nistp")
    assert len(trades) == 20
    first = trades[0]
    assert first["trade_id"] == "68240"
    assert first["trade_nid"] == "484796"
    assert first["trade_number"] == "68240-ОАОФ"
    assert first["detail_url"] == "https://nistp.ru/bankrot/trade_view.php?trade_nid=484796"
    # organizer/debtor located by their column header (positions vary per site);
    # debtor is the first bold span of the "должник + object" cell.
    assert first["organizer"] == "Чахоян Кима Самвеловна"
    assert first["debtor"] == "Ионов Павел Олегович"


def test_sistematorg_onclick_variant():
    # table.data, per-trade rows, detail via row onclick (root-relative URL).
    trades = parse_listing(_sel("sistematorg_listing.html"), "sistematorg")
    assert len(trades) == 20
    first = trades[0]
    assert first["trade_id"] == "19294"
    assert first["trade_nid"] == "63467"
    assert first["detail_url"] == "/trade_view.php?trade_nid=63467"


def test_ruson_nodeview_lotrows_variant():
    # table.node_view, per-lot rows -> de-duplicated to distinct trades.
    trades = parse_listing(_sel("ruson_listing.html"), "rus_on")
    assert trades
    nids = [t["trade_nid"] for t in trades]
    assert len(nids) == len(set(nids))  # distinct
    assert trades[0]["trade_id"] == "14145"
    assert trades[0]["trade_nid"] == "112813"


def test_find_next_page():
    # pagination via pagenum_send(N) onclick handlers.
    assert find_next_page(_sel("nistp_listing.html"), 1) == 2
    assert find_next_page(_sel("nistp_listing.html"), 9999) is None
