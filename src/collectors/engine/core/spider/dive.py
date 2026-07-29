"""DiveParser — the listing → per-trade dive → per-lot pattern.

Three of the engines (kendo, btorg, ruson) crawl the same way: page through a
listing that enumerates *trades*, dive into each trade once, and emit one item
per lot. Only the extraction functions and a few URL/field names differ, so the
skeleton (pagination, crawl-level de-duplication, dive, emit) lives here and
engines supply the three hooks below.

A subclass sets ``LISTING_PATH`` (and the concrete platform class sets
``DOMAIN``, from which ``BASE_URL``/``start_urls`` are derived).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar
from urllib.parse import urljoin

from collectors.engine.core.lot import Lot
from collectors.engine.core.parsing import is_active_status, read_max_pages, read_only_active
from collectors.engine.core.spider.parser import BaseParser
from collectors.engine.core.spider.request import Request
from collectors.engine.core.spider.response import Response


class DiveParser(BaseParser):
    """Paginated listing of trades; one dive per trade; one item per lot."""

    DOMAIN: ClassVar[str]
    LISTING_PATH: ClassVar[str] = ""
    BASE_URL: ClassVar[str]

    #: trade-dict field that uniquely identifies a trade (de-duplication key)
    TRADE_KEY: ClassVar[str] = "trade_id"
    #: trade-dict field holding the URL to dive into
    DIVE_URL_KEY: ClassVar[str] = "detail_url"
    #: extra headers for the dive request (e.g. an XHR marker)
    DIVE_HEADERS: ClassVar[dict[str, str] | None] = None
    #: query parameter used for pagination
    PAGE_PARAM: ClassVar[str] = "page"

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        # A trade can reappear on a later page (per-lot listings span pages;
        # live re-sorting on trade listings) — dive and emit it only once.
        self._seen_trades: set[object] = set()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Engine bases have no DOMAIN (only the annotation); concrete platform
        # classes do, and that is when the URLs can be derived.
        if getattr(cls, "DOMAIN", None):
            cls.BASE_URL = f"{cls.DOMAIN.rstrip('/')}/{cls.LISTING_PATH}"
            cls.start_urls = [cls.BASE_URL]

    # ── engine hooks ────────────────────────────────────────────────────────

    def list_trades(self, selector: Any) -> list[dict[str, Any]]:
        """Parse a listing page into trade dicts (distinct within the page)."""
        raise NotImplementedError

    def next_page(self, selector: Any, page: int) -> int | None:
        """Next page number from the pager, or None on the last page."""
        raise NotImplementedError

    def extract_lots(self, selector: Any, trade: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse a dived page into finished per-lot item dicts."""
        raise NotImplementedError

    # ── shared skeleton ─────────────────────────────────────────────────────

    async def parse(self, response: Response) -> AsyncIterator[Request | dict[str, Any]]:
        sel = response.selector()
        trades = self.list_trades(sel)
        page = response.metadata.get("page", 1)
        self.listing_page_count += 1
        await self.log(
            f"{response.request.method} | {response.status} | page={page} | trades={len(trades)}"
        )

        only_active = read_only_active(self.ctx.params)
        seen = self._seen_trades
        for trade in trades:
            # Diving is what costs (a request per trade plus the whole detail
            # blob); listing pages are cheap. So page on through the archive but
            # only dive live trades — deep stragglers still get collected.
            if only_active and not is_active_status(trade.get("status")):
                continue
            dive_url = trade.get(self.DIVE_URL_KEY)
            trade_key = trade.get(self.TRADE_KEY)
            if not dive_url or trade_key in seen:
                continue
            seen.add(trade_key)
            yield self.request(
                urljoin(response.request.url, str(dive_url)),
                callback=self.parse_lots_page,
                metadata={"trade": trade},
                headers=self.DIVE_HEADERS,
            )

        next_page = self.next_page(sel, page)
        max_pages = read_max_pages(self.ctx.params)
        if next_page and (max_pages is None or page < max_pages):
            yield self.request(
                f"{self.BASE_URL}?{self.PAGE_PARAM}={next_page}",
                metadata={"page": next_page},
            )

    async def parse_lots_page(self, response: Response) -> AsyncIterator[Request | dict[str, Any]]:
        sel = response.selector()
        trade = response.metadata["trade"]
        lots = self.extract_lots(sel, trade)
        await self.log(
            f"{response.request.method} | {response.status} "
            f"| lots trade={trade.get('trade_id')} | lots={len(lots)}"
        )
        for item in lots:
            # An item without a lot_id cannot be upserted downstream — drop it.
            if item.get("lot_id"):
                yield Lot.model_validate(item)
