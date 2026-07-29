"""TenderKendo — base parser for Kendo-ETP bankruptcy-auction sites.

The listing (per-trade or per-lot cards, depending on the site) is reduced to
distinct trade detail URLs; the detail page supplies the authoritative
trade-level fields and every lot. Crawl skeleton lives in ``DiveParser``.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from collectors.engine.core.spider import DiveParser
from collectors.engine.sources.kendo.parsing.detail import (
    parse_documents,
    parse_lots,
    parse_main_info,
)
from collectors.engine.sources.kendo.parsing.listing import find_next_page, parse_listing

_DEBTOR_RE = re.compile(r"должник[аи]?\s+(.+)$", re.IGNORECASE)


class TenderKendo(DiveParser):
    """Base parser for Kendo-ETP sites (server-rendered listing + detail)."""

    LISTING_PATH: ClassVar[str] = "lots"

    def list_trades(self, selector: Any) -> list[dict[str, Any]]:
        return parse_listing(selector, self.name)

    def next_page(self, selector: Any, page: int) -> int | None:
        return find_next_page(selector, page)

    def extract_lots(self, selector: Any, trade: dict[str, Any]) -> list[dict[str, Any]]:
        main = parse_main_info(selector)
        docs = parse_documents(selector)
        organizer = main.get("Наименование")
        # Debtor is the "…, должник X" tail of the listing card title.
        card_title = trade.get("trade_title") or ""
        debtor_m = _DEBTOR_RE.search(card_title)
        # Trade-level fingerprint fields come from the authoritative detail page,
        # not the listing card (which is lot-level on the per-lot template).
        trade_ctx = dict(trade)
        trade_ctx["trade_number"] = trade.get("trade_number")
        trade_ctx["debtor"] = debtor_m.group(1).strip() if debtor_m else None
        trade_ctx["bidding_date"] = main.get("Окончание приема заявок") or trade.get("bidding_date")
        trade_ctx["event_date"] = main.get("Подведение результатов торгов") or trade.get(
            "event_date"
        )

        lots = parse_lots(selector, trade_ctx)
        for item in lots:
            item["organizer"] = organizer
            item["detail"] = main
            item["attachments"] = docs
        return lots
