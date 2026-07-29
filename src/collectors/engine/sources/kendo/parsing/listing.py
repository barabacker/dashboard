"""Parse the trade listing (/lots?page=N) on Kendo-ETP sites.

Cards use the class ``block-lot`` (an ``<a>`` per trade on some sites, a
``<div>`` per lot on others). Both variants carry a "Номер торгов" link
(``/{type}/{id}``) — the trade detail URL. We key off that and de-duplicate by
trade id, so both templates reduce to the same set of trades to dive into.
"""

from __future__ import annotations

import re

from parsel import Selector

from collectors.engine.core.parsing import clean, read_max_pages

__all__ = ["clean", "find_next_page", "parse_listing", "read_max_pages"]

_PAGE_RE = re.compile(r"page=(\d+)")
_DIGITS_RE = re.compile(r"\d+")
# "10775–ОАОФ" / "37-ОАОФ": digits then an en-dash or hyphen. Distinguishes the
# trade-number bold from the title bold within a card.
_NUMBER_RE = re.compile(r"^\d+\s*[–-]")


def _date_by_title(card: Selector, title: str) -> str | None:
    return clean(card.xpath(f'.//nobr[i[@title="{title}"]]/text()').get())


def parse_listing(selector: Selector, source: str) -> list[dict[str, object]]:
    """Parse a /lots page into DISTINCT trade dicts.

    Keys off each card's "Номер торгов" link (tag- and colour-agnostic) and
    de-duplicates by trade id. Card fields here are best-effort — authoritative
    trade-level fields are re-derived from the detail page (they are lot-level
    or absent on the per-lot card template).
    """
    trades: list[dict[str, object]] = []
    seen: set[str] = set()
    for card in selector.xpath('//*[contains(@class, "block-lot")]'):
        # Scan the card's ``bold`` elements: the one matching _NUMBER_RE is the
        # trade number ("10775–ОАОФ"); the first other one is the title. The
        # number may be plain text (per-trade <a> card, whose inner anchors lxml
        # strips) or wrap an <a> (per-lot <div> card) — handle both.
        number = num_href = title = None
        for el in card.xpath('.//*[contains(@class, "bold")]'):
            txt = clean(el.xpath("string(.)").get())
            if not txt:
                continue
            if _NUMBER_RE.match(txt):
                number = txt
                num_href = el.xpath(".//a/@href").get()
            elif title is None:
                title = txt
        # detail_url: the card's own href (per-trade <a>) or the number's <a>
        # href (per-lot <div>).
        detail_url = card.xpath("./@href").get() or num_href
        if not number or not detail_url:
            continue
        m = _DIGITS_RE.search(number)
        trade_id = m.group(0) if m else None
        if not trade_id or trade_id in seen:
            continue
        seen.add(trade_id)
        parts = number.split("–")
        trade_type = clean(parts[1]) if len(parts) == 2 else None
        trades.append(
            {
                "trade_id": trade_id,
                "trade_number": number,
                "trade_type": trade_type,
                "trade_title": title,
                "detail_url": detail_url,
                "status": clean(
                    card.xpath('.//span[contains(@class, "competition-status-text")]/text()').get()
                ),
                "start_date": _date_by_title(card, "Начало приема заявок"),
                "bidding_date": _date_by_title(card, "Окончание приема заявок"),
                "event_date": _date_by_title(card, "Подведение итогов"),
                "_source": source,
            }
        )
    return trades


def find_next_page(selector: Selector, current_page: int) -> int | None:
    """Smallest pager page number greater than ``current_page``, or None."""
    pages: list[int] = []
    for href in selector.xpath(
        '//ul[contains(@class, "pagination")]//a[contains(@href, "page=")]/@href'
    ).getall():
        m = _PAGE_RE.search(href)
        if m:
            pages.append(int(m.group(1)))
    nxt = [p for p in pages if p > current_page]
    return min(nxt) if nxt else None
