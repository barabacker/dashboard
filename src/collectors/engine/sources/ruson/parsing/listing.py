"""Parse the trade listing on rus-on sites (…/trade_list.php or …/tradelist.php).

The rus-on group is heterogeneous: the listing table is ``table.data`` or
``table.node_view``; each row links to a trade either via an ``<a href>`` or a
row ``onclick``; some sites list trades, others list lots (several rows per
trade). What is uniform is the trade detail URL ``trade_view.php?trade_nid=N``,
so the listing is reduced to a de-duplicated set of those trade references — all
trade/lot fields are then read from the (uniform) detail page.
"""

from __future__ import annotations

import re

from parsel import Selector

from collectors.engine.core.parsing import clean, parse_price, pick_status, read_max_pages

__all__ = ["clean", "find_next_page", "parse_listing", "parse_price", "read_max_pages"]

_NID_RE = re.compile(r"trade_view\.php\?trade_nid=(\d+)")
_REF_RE = re.compile(r"(/?[^'\"\s]*trade_view\.php\?trade_nid=\d+)")
_CODE_RE = re.compile(r"(\d+)-[А-Я]{2,}")
_PAGENUM_RE = re.compile(r"pagenum_send\((\d+)\)")


def _header_index(selector: Selector, needle: str) -> int | None:
    """0-based td index whose column header contains ``needle`` (lowered)."""
    for i, th in enumerate(selector.xpath("//tr[th]/th")):
        if needle in (clean(th.xpath("string(.)").get()) or "").lower():
            return i
    return None


def parse_listing(selector: Selector, source: str) -> list[dict[str, object]]:
    """Reduce a listing page to DISTINCT trades (by trade_nid).

    Trade reference comes from a row ``<a href=…trade_view.php…>`` or the row's
    ``onclick``. ``trade_id`` is the visible code's digits when present, else the
    internal nid; ``detail_url`` may be absolute or root-relative (the caller
    resolves it against the page URL). Organizer/debtor are read from the listing
    columns located by their header (their position varies per site); absent a
    header (node_view / lot listings) they are left None.
    """
    trades: list[dict[str, object]] = []
    seen: set[str] = set()
    org_idx = _header_index(selector, "организатор")
    debtor_idx = _header_index(selector, "должник")
    rows = selector.xpath(
        '//tr[.//a[contains(@href, "trade_view.php")]] | //tr[contains(@onclick, "trade_view.php")]'
    )
    for row in rows:
        href = row.xpath('.//a[contains(@href, "trade_view.php")]/@href').get()
        ref = href
        if not ref:
            m = _REF_RE.search(row.xpath("./@onclick").get() or "")
            ref = m.group(1) if m else None
        if not ref:
            continue
        nid = _NID_RE.search(ref)
        if not nid:
            continue
        trade_nid = nid.group(1)
        if trade_nid in seen:
            continue
        seen.add(trade_nid)
        code = _CODE_RE.search(clean(row.xpath("string(.)").get()) or "")
        # The "Состояние" column sits at a different index per site, so pick the
        # cell that reads like a status. Used only to stop paging past the
        # archive; the authoritative status comes from the detail page.
        tds = row.xpath("./td")
        status = pick_status([cell.xpath("string(.)").get() for cell in tds])
        organizer = None
        if org_idx is not None and org_idx < len(tds):
            organizer = clean(tds[org_idx].xpath("string(.)").get())
        debtor = None
        if debtor_idx is not None and debtor_idx < len(tds):
            # cell is "debtor + object"; the debtor name is the first bold span.
            bold = './/span[contains(@style, "bold")][1]/text()'
            debtor = clean(tds[debtor_idx].xpath(bold).get())
        trades.append(
            {
                "trade_nid": trade_nid,
                "trade_id": code.group(1) if code else trade_nid,
                "trade_number": code.group(0) if code else None,
                "trade_type": clean(code.group(0).split("-")[1]) if code else None,
                "detail_url": ref,
                "status": status,
                "organizer": organizer,
                "debtor": debtor,
                "_source": source,
            }
        )
    return trades


def find_next_page(selector: Selector, current_page: int) -> int | None:
    """Next page number from the ``pagenum_send(N)`` pager, or None."""
    pages: list[int] = []
    for onclick in selector.xpath('//ul[contains(@class, "pagination")]//a/@onclick').getall():
        pages.extend(int(n) for n in _PAGENUM_RE.findall(onclick))
    nxt = [p for p in pages if p > current_page]
    return min(nxt) if nxt else None
