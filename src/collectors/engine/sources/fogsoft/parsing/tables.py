"""Parsing of the lot table and pagination on the iTender (Fogsoft) platform."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from parsel import Selector

from collectors.engine.core.parsing import clean, parse_price, read_max_pages

_NEXT_BLOCK_LABEL = ">>"
_CTL_RE = re.compile(r"ctl\d+")

__all__ = ["ajax_headers", "clean", "find_next_ctl", "parse_price", "parse_table", "read_max_pages"]


def ajax_headers(base_url: str) -> dict[str, str]:
    """Headers for UpdatePanel AJAX pagination POSTs."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "Accept": "*/*",
        "Accept-Language": "ru,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": origin,
        "Referer": base_url,
        "X-MicrosoftAjax": "Delta=true",
        "X-Requested-With": "XMLHttpRequest",
    }


def find_next_ctl(sel: Selector, current_page: int) -> str | None:
    """Pick the ctl-id of the next-page link.

    1) A link whose text is str(current_page + 1) — next page in the current
       pager block.
    2) Otherwise the ">>" link (jump to the next block of 10).
    3) Neither — last page, return None.
    """
    target = str(current_page + 1)
    next_block_ctl: str | None = None

    for a in sel.xpath('(//td[@class="pager"])[1]//a'):
        text = (a.xpath("string(.)").get() or "").strip()
        href = a.xpath("./@href").get() or ""
        matches: list[str] = _CTL_RE.findall(href)
        if not matches:
            continue
        ctl: str = matches[-1]
        if text == target:
            return ctl
        if text == _NEXT_BLOCK_LABEL:
            next_block_ctl = ctl

    return next_block_ctl


def parse_table(selector: Selector, source: str) -> list[dict[str, object]]:
    """Parse the lot table rows (``tr.gridRow``)."""
    rows: list[dict[str, object]] = []
    for tr in selector.xpath('//tr[@class="gridRow"]'):
        trade_id = clean(tr.xpath("./td[1]/a/text()").get())
        lot_num = clean(tr.xpath("./td[3]/a/text()").get())
        price_raw = clean(tr.xpath("string(./td[5])").get())
        rows.append(
            {
                "lot_id": f"{trade_id}_{lot_num}" if trade_id and lot_num else None,
                "trade_id": trade_id,
                "trade_number": trade_id,
                "lot_num": lot_num,
                "debtor": clean(tr.xpath("string(./td[2])").get()),
                "lot_url": clean(tr.xpath("./td[4]/a[@class='tip-lot']/@href").get()),
                "description": clean(tr.xpath("./td[4]/a[@class='tip-lot']/text()").get()),
                "price": parse_price(price_raw),
                "price_raw": price_raw,
                "organizer": clean(tr.xpath("string(./td[6])").get()),
                "bidding_date": clean(tr.xpath("string(./td[7])").get()),
                "event_date": clean(tr.xpath("./td[8]/text()").get()),
                "status": clean(tr.xpath("./td[9]/text()").get()),
                "trade_type": clean(tr.xpath("./td[11]/text()").get()),
                "_source": source,
            }
        )
    return rows
