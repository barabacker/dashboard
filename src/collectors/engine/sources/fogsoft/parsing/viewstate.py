"""ASP.NET ViewState utilities for the iTender (Fogsoft) platform.

The site uses UpdatePanel — paging returns a delta response with refreshed
__CVIEWSTATE and __EVENTVALIDATION tokens.
"""

from __future__ import annotations

import re

from parsel import Selector


def extract_tokens(text: str) -> tuple[str | None, str | None]:
    """Extract __CVIEWSTATE and __EVENTVALIDATION from an UpdatePanel delta."""
    cviewstate = None
    eventvalidation = None

    if m := re.search(r"__CVIEWSTATE\|([^|]+)", text):
        cviewstate = m.group(1)
    if m := re.search(r"__EVENTVALIDATION\|([^|]+)", text):
        eventvalidation = m.group(1)

    return cviewstate, eventvalidation


def extract_initial_tokens(html: str) -> tuple[str | None, str | None]:
    """Extract tokens from the initial HTML page (hidden form fields)."""
    sel = Selector(text=html)
    cviewstate = sel.xpath('//input[@id="__CVIEWSTATE"]/@value').get()
    eventvalidation = sel.xpath('//input[@id="__EVENTVALIDATION"]/@value').get()
    return cviewstate, eventvalidation


def build_payload(ctl_suffix: str, cviewstate: str, eventvalidation: str) -> dict[str, str]:
    """Build the POST body for clicking a pager link.

    ``ctl_suffix`` is the last EVENTTARGET component (e.g. "ctl03"), taken from
    the href of the corresponding pager link.
    """
    target = (
        f"ctl00$ctl00$MainContent$ContentPlaceHolderMiddle$PurchasesSearchResult$ctl01${ctl_suffix}"
    )
    return {
        "ctl00$ctl00$BodyScripts$BodyScripts$scripts": (
            f"ctl00$ctl00$MainContent$ContentPlaceHolderMiddle$UpdatePanel2|{target}"
        ),
        "__EVENTTARGET": target,
        "__CVIEWSTATE": cviewstate,
        "__EVENTVALIDATION": eventvalidation,
    }
