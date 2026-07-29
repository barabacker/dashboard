"""Parsing of the lot detail page on the iTender (Fogsoft) platform.

All sites share one ASP.NET template: ``<fieldset>`` blocks with a ``<legend>``
section title, containing ``td.tdTitle`` / ``td.tdContent`` pairs. The same
label (e.g. "Наименование") appears in different sections with different
meaning (auction header vs the lot itself), so fields are extracted per section
rather than into one flat dict — otherwise values overwrite each other.

The "Интервалы снижения цены" section exists only for public_offer (a
step-by-step price reduction schedule); auction/contest instead carry
"Шаг, %" / "Шаг, руб." in the lot section (already captured by
parse_detail_sections).
"""

from __future__ import annotations

from parsel import Selector

from collectors.engine.core.parsing import clean as _clean


def parse_detail_sections(selector: Selector) -> dict[str, dict[str, str]]:
    """Extract every ``<fieldset>`` section as {legend: {label: value}}."""
    sections: dict[str, dict[str, str]] = {}
    for fieldset in selector.xpath("//fieldset"):
        legend = _clean(fieldset.xpath("./legend//text()").get())
        if not legend:
            continue
        fields: dict[str, str] = {}
        for td_title in fieldset.xpath('.//td[@class="tdTitle"]'):
            label = _clean(td_title.xpath("string(.)").get())
            if not label:
                continue
            label = label.rstrip(":").strip()
            value = _clean(td_title.xpath("following-sibling::td[1]").xpath("string(.)").get())
            if label and value:
                fields[label] = value
        if fields:
            sections[legend] = fields
    return sections


def parse_attachments(selector: Selector) -> list[dict[str, object]]:
    """Extract attached documents: name, link, whether it is e-signed."""
    attachments: list[dict[str, object]] = []
    for row in selector.xpath('//tr[contains(@class, "attachment-grid-row")]'):
        link = row.xpath(".//a[@href]")
        name = _clean(link.xpath("string(.)").get())
        url = link.xpath("./@href").get()
        if not name and not url:
            continue
        signed = bool(row.xpath('.//*[contains(@class, "certOk")]'))
        attachments.append({"name": name, "url": url, "signed": signed})
    return attachments


def parse_price_schedule(selector: Selector) -> list[dict[str, str]]:
    """Extract the price-reduction schedule (public_offer only)."""
    fieldset = selector.xpath('//fieldset[legend[contains(., "Интервалы снижения цены")]]')
    if not fieldset:
        return []
    headers = [
        _clean(td.xpath("string(.)").get()) or ""
        for td in fieldset.xpath('(.//tr[contains(@class, "gridHeader")])[1]/td')
    ]
    if not headers:
        return []
    schedule: list[dict[str, str]] = []
    for row in fieldset.xpath('.//tr[contains(@class, "gridRow")]'):
        cells = [_clean(td.xpath("string(.)").get()) or "" for td in row.xpath("./td")]
        if len(cells) != len(headers):
            continue
        schedule.append(dict(zip(headers, cells, strict=True)))
    return schedule
