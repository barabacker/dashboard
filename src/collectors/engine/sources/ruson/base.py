"""TenderRuson — base parser for rus-on bankruptcy-auction sites.

The listing markup varies across the group, so it is reduced to distinct
``trade_view.php`` references; that detail page is uniform and supplies the
trade-level fields and every lot. Sites differ in listing path
(``trade_list.php`` vs ``tradelist.php``) — set per platform in platforms.toml.
Crawl skeleton lives in ``DiveParser``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from collectors.engine.core.spider import DiveParser
from collectors.engine.sources.ruson.parsing.detail import parse_lots
from collectors.engine.sources.ruson.parsing.listing import find_next_page, parse_listing


class TenderRuson(DiveParser):
    """Base parser for rus-on sites (heterogeneous listing, uniform detail)."""

    LISTING_PATH: ClassVar[str] = "bankrot/trade_list.php"
    TRADE_KEY: ClassVar[str] = "trade_nid"
    PAGE_PARAM: ClassVar[str] = "pagenum"

    def list_trades(self, selector: Any) -> list[dict[str, Any]]:
        return parse_listing(selector, self.name)

    def next_page(self, selector: Any, page: int) -> int | None:
        return find_next_page(selector, page)

    def extract_lots(self, selector: Any, trade: dict[str, Any]) -> list[dict[str, Any]]:
        return parse_lots(selector, trade)
