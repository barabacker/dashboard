"""Parse the trade listing (/etp/trade/list.html?page=N) on btorg/edoc-ETP sites.

The listing is an HTML ``table.data``; each ``<tr onclick=…>`` is one trade. The
trade's internal purchase id (used to fetch its lots) lives in the row's
``onclick`` (``…general.html?id=NNN…``); the visible columns are number, debtor,
organizer + object description, status, date.
"""

from __future__ import annotations

import re

from parsel import Selector

from collectors.engine.core.parsing import clean, parse_price, read_max_pages

__all__ = ["LOTS_PATH", "clean", "find_next_page", "parse_listing", "parse_price", "read_max_pages"]

_PAGE_RE = re.compile(r"page=(\d+)")
_DIGITS_RE = re.compile(r"\d+")
_ID_RE = re.compile(r"id=(\d+)")

# The AJAX endpoint that returns a trade's lots (with prices).
LOTS_PATH = "/etp/trade/inner-view-lots.html"


def parse_listing(selector: Selector, source: str) -> list[dict[str, object]]:
    """Parse ``table.data`` trade rows into trade dicts."""
    trades: list[dict[str, object]] = []
    for row in selector.xpath('//table[@class="data"]//tr[@onclick]'):
        m = _ID_RE.search(row.xpath("./@onclick").get() or "")
        purchase_id = m.group(1) if m else None
        tds = row.xpath("./td")
        if not purchase_id or len(tds) < 5:
            continue
        number = clean(tds[0].xpath("string(.)").get())
        if not number:
            continue
        dm = _DIGITS_RE.search(number)
        trade_id = dm.group(0) if dm else None
        if not trade_id:
            continue
        parts = number.split("-")
        trade_type = clean(parts[1]) if len(parts) == 2 else None
        trades.append(
            {
                "trade_id": trade_id,
                "trade_number": number,
                "trade_type": trade_type,
                "purchase_id": purchase_id,
                "debtor": clean(tds[1].xpath("string(.)").get()),
                "organizer": clean(tds[2].xpath('.//div[contains(@style, "bold")]//text()').get()),
                "status": clean(tds[3].xpath("string(.)").get()),
                "list_date": clean(tds[4].xpath("string(.)").get()),
                "lots_url": f"{LOTS_PATH}?perspective=inline&id={purchase_id}",
                "_source": source,
            }
        )
    return trades


def find_next_page(selector: Selector, current_page: int) -> int | None:
    """Smallest pager page number greater than ``current_page``, or None."""
    pages: list[int] = []
    for href in selector.xpath('//a[contains(@href, "list.html?page=")]/@href').getall():
        m = _PAGE_RE.search(href)
        if m:
            pages.append(int(m.group(1)))
    nxt = [p for p in pages if p > current_page]
    return min(nxt) if nxt else None
