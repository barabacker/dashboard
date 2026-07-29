"""Parse a Kendo-ETP trade detail page (/{type}/{id}).

One server-rendered page holds all tabs. Lots live in ``div#lots`` as repeated
``.block-lot`` blocks (an ``<a>`` or ``<div>`` depending on the site; each: lot
link with ``/lots/`` in its href, "Номер лота", "Статус лота", price in
``span.fs36``). Trade-level key/value fields live in ``div#main-info`` as
``div.table_row`` label/value pairs; documents in ``div#documents``.
"""

from __future__ import annotations

from parsel import Selector

from collectors.engine.core.parsing import clean as _clean
from collectors.engine.core.parsing import parse_price

__all__ = ["parse_documents", "parse_lots", "parse_main_info", "parse_price"]

#: The lot status sits in the text node *after* the label span, not inside it.
_LOT_STATUS_XPATH = './/span[contains(@class, "lot-status")]/following-sibling::text()'


def parse_lots(selector: Selector, trade: dict[str, object]) -> list[dict[str, object]]:
    """Expand ``div#lots > a.block-lot`` into per-lot item dicts.

    Trade-level fields from ``trade`` (title, dates, source) are copied onto each
    lot so ``lot_fingerprint`` (status/price/dates/trade_number) works per lot.
    """
    trade_id = trade.get("trade_id")
    items: list[dict[str, object]] = []
    for block in selector.xpath('//div[@id="lots"]//*[contains(@class, "block-lot")]'):
        link = block.xpath('.//a[contains(@href, "/lots/")][1]')
        lot_num = _clean(block.xpath('.//span[contains(@class, "black-text")]/text()').get())
        price_raw = _clean(block.xpath('string(.//span[contains(@class, "fs36")])').get())
        items.append(
            {
                "lot_id": f"{trade_id}_{lot_num}" if trade_id and lot_num else None,
                "trade_id": trade_id,
                "trade_number": trade.get("trade_number"),
                "lot_num": lot_num,
                "debtor": trade.get("debtor"),
                "lot_url": link.xpath("./@href").get(),
                "description": _clean(link.xpath("string(.)").get()),
                "price": parse_price(price_raw),
                "price_raw": price_raw,
                "status": _clean(block.xpath(_LOT_STATUS_XPATH).get()),
                "trade_type": trade.get("trade_type"),
                "bidding_date": trade.get("bidding_date"),
                "event_date": trade.get("event_date"),
                "organizer": None,
                "_source": trade.get("_source"),
            }
        )
    return items


def parse_main_info(selector: Selector) -> dict[str, str]:
    """Flat {label: value} of the ``#main-info`` table_row pairs.

    Labels repeated across sections collapse (last wins) — acceptable for this
    reference blob, which is not fingerprinted.
    """
    info: dict[str, str] = {}
    for row in selector.xpath('//div[@id="main-info"]//div[contains(@class, "table_row")]'):
        label = _clean(row.xpath('string(./div[contains(@class, "grey-text")][1])').get())
        value = _clean(row.xpath('string(./div[contains(@class, "l9")][1])').get())
        if label and value:
            info[label.rstrip(":").strip()] = value
    return info


def parse_documents(selector: Selector) -> list[dict[str, object]]:
    """Extract downloadable documents (name + http url) from ``#documents``."""
    docs: list[dict[str, object]] = []
    for row in selector.xpath('//div[@id="documents"]//div[contains(@class, "file-row")]'):
        link = row.xpath('.//a[starts-with(@href, "http")][1]')
        url = link.xpath("./@href").get()
        if url:
            docs.append({"name": _clean(link.xpath("string(.)").get()), "url": url})
    return docs
