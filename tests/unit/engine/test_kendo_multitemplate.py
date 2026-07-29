"""Listing/detail parsing across the two Kendo-ETP card templates.

Kendo sites ship one of two listing card shapes:
  A) a per-trade ``<a class="block-lot" href>`` card (trade_alliance covers the
     variant with anchor title; seltim the variant whose inner anchors lxml
     strips, so number/title are plain ``<span>``s);
  B) a per-lot ``<div class="block-lot">`` card with ``green-text`` links
     (torgi82, vetp), de-duplicated to distinct trades.
This suite locks both against committed fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

from parsel import Selector

from collectors.engine.sources.kendo.parsing.detail import parse_lots
from collectors.engine.sources.kendo.parsing.listing import parse_listing

FIX = Path(__file__).parent / "fixtures" / "kendo"


def _sel(name: str) -> Selector:
    return Selector(text=(FIX / name).read_text(encoding="utf-8"))


def test_seltim_listing_span_title_variant():
    trades = parse_listing(_sel("seltim_listing.html"), "seltim")
    assert len(trades) == 15
    # The whole point: every card yields a non-null trade_id (the old code
    # silently produced None here, giving null lot_ids downstream).
    assert all(t["trade_id"] for t in trades)
    assert trades[0]["trade_id"] == "3126"
    assert trades[0]["detail_url"] == "/oaof/3126"
    assert trades[0]["trade_title"].startswith("Открытый аукцион")


def test_torgi82_listing_per_lot_div_variant():
    trades = parse_listing(_sel("torgi82_listing.html"), "torgi82")
    ids = [t["trade_id"] for t in trades]
    assert ids == ["37", "34"]  # per-lot cards de-duplicated to distinct trades
    # detail URLs are /{type}/{id} with varying type codes (oaof, oacf, otpp, …).
    assert all(re.fullmatch(r"/[a-z]+/\d+", str(t["detail_url"])) for t in trades)


def test_torgi82_detail_div_block_lot():
    lots = parse_lots(_sel("torgi82_detail.html"), {"trade_id": "37", "_source": "torgi82"})
    assert lots
    first = lots[0]
    assert first["lot_id"] == "37_1"
    assert first["price"] == 10950000.0
    assert first["status"] == "Идет прием заявок"
    assert first["lot_url"].endswith("/oaof/37/lots/47")
