"""Parse a rus-on trade detail page (trade_view.php?trade_nid=N).

Uniform across all rus-on sites. Trade-level fields (status, application dates)
and each lot are ``<tr><td class="label">LABEL</td><td>VALUE</td></tr>`` pairs;
lots are grouped in tables whose header (``<th>``) contains "Лот № N".
"""

from __future__ import annotations

import re

from parsel import Selector

from collectors.engine.sources.ruson.parsing.listing import clean, parse_price

_LOTNUM_RE = re.compile(r"Лот № ?(\d+)")


def _field(scope: Selector, label: str) -> str | None:
    """Value cell of the label/value row whose first cell contains ``label``.

    Class-agnostic: works whether the label cell is ``<td class="label">`` (most
    sites) or a plain ``<td>`` (e.g. promkonsalt).
    """
    return clean(
        scope.xpath(f'.//tr[td[1][contains(normalize-space(.), "{label}")]]/td[2]')
        .xpath("string(.)")
        .get()
    )


def _block(selector: Selector, header: str) -> Selector:
    """The table enclosing the innermost cell whose text contains ``header``.

    Party info is grouped under section-header rows ("Информация о должнике" /
    "об организаторе"); its fields live as label/value rows in that header's
    enclosing table. The innermost-match guard avoids selecting an outer table.
    """
    node = selector.xpath(
        f'//*[contains(normalize-space(.), "{header}")]'
        f'[not(.//*[contains(normalize-space(.), "{header}")])]'
    )
    return node.xpath("./ancestor::table[1]")


def _debtor(selector: Selector) -> str | None:
    """Debtor name from the "Информация о должнике" block, if present.

    Physical persons: "Фамилия Имя Отчество"; legal entities: their full name.
    """
    block = _block(selector, "Информация о должнике")
    if not block:
        return None
    kind = (_field(block, "Тип должника") or "").lower()
    if "юридич" in kind:
        return _field(block, "Полное наименование") or _field(block, "Наименование должника")
    parts = [_field(block, "Фамилия"), _field(block, "Имя"), _field(block, "Отчество")]
    return " ".join(p for p in parts if p) or None


def _organizer(selector: Selector) -> str | None:
    """Organizer from the "Информация об организаторе" block, else the contact.

    Some sites (e.g. promkonsalt) omit the organiser block and only carry a
    "Контактное лицо организатора" — fall back to that person's ФИО.
    """
    block = _block(selector, "Информация об организаторе")
    org = _field(block, "Наименование") if block else None
    if not org:
        contact = _block(selector, "Контактное лицо организатора")
        org = _field(contact, "ФИО") if contact else None
    return org


def parse_lots(selector: Selector, trade: dict[str, object]) -> list[dict[str, object]]:
    """Expand each "Лот № N" section into a per-lot item dict.

    Trade-level fields (status, dates) are read once from the detail page; the
    price is per lot. Lots are located by the innermost element carrying the
    "Лот № N" marker (a ``<th>`` on some sites, ``span.lot_title`` on others);
    the lot's fields live in that marker's enclosing table.
    """
    trade_id = trade.get("trade_id")
    status = _field(selector, "Статус торгов") or trade.get("status")
    bidding_date = _field(selector, "Дата окончания представления")
    event_date = _field(selector, "Дата начала представления")
    # organizer/debtor: prefer the authoritative detail party blocks; the
    # listing columns are unreliable on some sites (missing, or bleeding the
    # lot list into the cell), so fall back to them only when the detail lacks
    # the block.
    organizer = _organizer(selector) or trade.get("organizer")
    debtor = _debtor(selector) or trade.get("debtor")

    items: list[dict[str, object]] = []
    # Lot headers only: a <th> (most sites) or span.lot_title (promkonsalt), and
    # only the innermost such element. Restricting to headers matters — prose
    # elsewhere on the page ("…задаток, Лот № 1, должник…") also contains the
    # phrase and previously produced a phantom, price-less duplicate lot.
    markers = selector.xpath(
        '//*[(self::th or contains(@class, "lot_title")) and contains(., "Лот №")'
        ' and not(descendant::*[contains(., "Лот №")])]'
    )
    for marker in markers:
        marker_text = clean(marker.xpath("string(.)").get()) or ""
        m = _LOTNUM_RE.search(marker_text)
        lot_num = m.group(1) if m else None
        lot = marker.xpath("./ancestor::table[1]")
        price_raw = _field(lot, "Начальная цена")
        title_desc = marker_text.split(":", 1)[1].strip() if ":" in marker_text else None
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
                "debtor": debtor,
                "lot_url": trade.get("detail_url"),
                "description": _field(lot, "Наименование") or title_desc,
                "price": parse_price(price_raw),
                "price_raw": price_raw,
                "status": status,
                "trade_type": trade.get("trade_type"),
                "organizer": organizer,
                "bidding_date": bidding_date,
                "event_date": event_date,
                "detail": detail,
                "_source": trade.get("_source"),
            }
        )
    return items
