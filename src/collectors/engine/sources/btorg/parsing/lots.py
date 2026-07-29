"""Parse the btorg/edoc-ETP lots fragment (inner-view-lots.html).

The AJAX endpoint returns one ``table.data`` per lot, keyed ``id="lotNumberN"``,
whose rows are label/value pairs (subject, description, classifier, starting
price, deposit, status, documents). Trade-level fields come from the listing row
(``trade``) so ``lot_fingerprint`` works per lot.
"""

from __future__ import annotations

import re

from parsel import Selector

from collectors.engine.sources.btorg.parsing.listing import clean, parse_price

_LOTNUM_RE = re.compile(r"lotNumber(\d+)")


def _field(lot: Selector, label: str) -> str | None:
    """Value cell of the label/value row whose first cell contains ``label``."""
    row = f'.//tr[td[1][contains(normalize-space(.), "{label}")]]/td[2]'
    return clean(lot.xpath(row).xpath("string(.)").get())


def parse_lots(selector: Selector, trade: dict[str, object]) -> list[dict[str, object]]:
    """Expand ``table.data#lotNumberN`` into per-lot item dicts."""
    trade_id = trade.get("trade_id")
    items: list[dict[str, object]] = []
    for lot in selector.xpath('//table[contains(@id, "lotNumber")]'):
        m = _LOTNUM_RE.search(lot.xpath("./@id").get() or "")
        lot_num = m.group(1) if m else None
        price_raw = _field(lot, "Начальная цена продажи")
        detail: dict[str, str] = {}
        for tr in lot.xpath(".//tr[td[2]]"):
            key = clean(tr.xpath("./td[1]").xpath("string(.)").get())
            val = clean(tr.xpath("./td[2]").xpath("string(.)").get())
            if key and val:
                detail[key.rstrip(":").strip()] = val
        items.append(
            {
                "lot_id": f"{trade_id}_{lot_num}" if trade_id and lot_num else None,
                "trade_id": trade_id,
                "trade_number": trade.get("trade_number"),
                "lot_num": lot_num,
                "debtor": trade.get("debtor"),
                "lot_url": trade.get("lots_url"),
                "description": _field(lot, "Предмет торгов"),
                "price": parse_price(price_raw),
                "price_raw": price_raw,
                "status": _field(lot, "Статус торгов") or trade.get("status"),
                "trade_type": trade.get("trade_type"),
                "organizer": trade.get("organizer"),
                "bidding_date": trade.get("list_date"),
                "event_date": None,
                "detail": detail,
                "_source": trade.get("_source"),
            }
        )
    return items
