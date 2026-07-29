"""TenderBtorg — base parser for btorg/edoc-ETP bankruptcy-auction sites.

The ``table.data`` listing has one row per trade and carries no price, so each
trade is dived into the AJAX lots fragment, which is expanded into one item per
lot. Crawl skeleton lives in ``DiveParser``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from collectors.engine.core.spider import DiveParser
from collectors.engine.sources.btorg.parsing.listing import find_next_page, parse_listing
from collectors.engine.sources.btorg.parsing.lots import parse_lots


class TenderBtorg(DiveParser):
    """Base parser for btorg/edoc-ETP sites (HTML table listing + AJAX lots)."""

    LISTING_PATH: ClassVar[str] = "etp/trade/list.html"
    TRADE_KEY: ClassVar[str] = "purchase_id"
    DIVE_URL_KEY: ClassVar[str] = "lots_url"
    DIVE_HEADERS: ClassVar[dict[str, str] | None] = {"X-Requested-With": "XMLHttpRequest"}

    def list_trades(self, selector: Any) -> list[dict[str, Any]]:
        return parse_listing(selector, self.name)

    def next_page(self, selector: Any, page: int) -> int | None:
        return find_next_page(selector, page)

    def extract_lots(self, selector: Any, trade: dict[str, Any]) -> list[dict[str, Any]]:
        return parse_lots(selector, trade)
