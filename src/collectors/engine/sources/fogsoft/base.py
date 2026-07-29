"""TenderFogsoft — base class for iTender (Fogsoft) platform parsers:
ASP.NET WebForms + UpdatePanel, ViewState pagination, lot listing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from collectors.engine.core.lot import Lot
from collectors.engine.core.parsing import is_active_status, read_only_active
from collectors.engine.core.spider import BaseParser, Request, Response
from collectors.engine.core.storage.contracts import lot_fingerprint
from collectors.engine.sources.fogsoft.inprotect import solve_inprotect
from collectors.engine.sources.fogsoft.parsing.detail import (
    parse_attachments,
    parse_detail_sections,
    parse_price_schedule,
)
from collectors.engine.sources.fogsoft.parsing.tables import (
    ajax_headers,
    find_next_ctl,
    parse_table,
    read_max_pages,
)
from collectors.engine.sources.fogsoft.parsing.viewstate import (
    build_payload,
    extract_initial_tokens,
    extract_tokens,
)

if TYPE_CHECKING:
    from collectors.engine.http.middleware import ResponseHook


class TenderFogsoft(BaseParser):
    """Base parser for iTender (Fogsoft) sites.

    A subclass sets only ``name`` (registry key) and ``DOMAIN`` (site root, e.g.
    ``"https://bankrupt.alfalot.ru"``). ``BASE_URL`` and ``start_urls`` are
    derived automatically in ``__init_subclass__``.

    The inprotect challenge is invisible to the parser — it is handled
    transparently by the ``solve_inprotect`` response hook.
    """

    DOMAIN: ClassVar[str]
    LISTING_PATH: ClassVar[str] = "public/purchases-all/"
    BASE_URL: ClassVar[str]
    # Path (relative to this package) to a PEM file with an extra intermediate
    # certificate the site fails to send in its TLS handshake (see certs/*.pem).
    # None — use the normal CA bundle.
    EXTRA_CA_CERT: ClassVar[str | None] = None
    # True — disable TLS verification entirely (verify=False). Only for sites
    # whose certificate is objectively broken on their side (e.g. expired) and
    # no CA bundle can fix it (see ArbBitLotParser). Disables MITM protection
    # for requests to this site.
    SKIP_TLS_VERIFY: ClassVar[bool] = False
    RESPONSE_HOOKS: ClassVar[tuple[ResponseHook, ...]] = (solve_inprotect,)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "DOMAIN" in cls.__dict__:
            cls.BASE_URL = f"{cls.DOMAIN.rstrip('/')}/{cls.LISTING_PATH}"
            cls.start_urls = [cls.BASE_URL]

    async def parse(self, response: Response) -> AsyncIterator[Request | dict[str, Any]]:
        sel = response.selector()
        items = parse_table(sel, self.name)
        page = response.metadata.get("page", 1)
        self.listing_page_count += 1
        await self.log(
            f"{response.request.method} | {response.status} | page={page} "
            f"| items={len(items)} | total={self.item_count + len(items)}"
        )
        existing_fingerprints: dict[str, str] = {}
        if self.ctx.lot_sink is not None:
            lot_ids = [str(item["lot_id"]) for item in items if item.get("lot_id")]
            if lot_ids:
                existing_fingerprints = await self.ctx.lot_sink.get_fingerprints(self.name, lot_ids)

        only_active = read_only_active(self.ctx.params)
        for item in items:
            # Here a listing row *is* the lot, so the filter drops finished lots
            # outright: we page on through the archive but never pay for it.
            if only_active and not is_active_status(item.get("status")):
                continue
            lot_id = item.get("lot_id")
            needs_dive = (
                self.ctx.lot_sink is not None
                and lot_id is not None
                and existing_fingerprints.get(str(lot_id)) != lot_fingerprint(item)
            )
            if needs_dive and item.get("lot_url"):
                yield self.request(
                    urljoin(response.request.url, str(item["lot_url"])),
                    callback=self.parse_detail,
                    metadata={"item": item},
                )
            elif item.get("lot_id"):
                # An item without a lot_id cannot be validated/upserted — drop it.
                yield Lot.model_validate(item)

        if page == 1:
            cviewstate, eventvalidation = extract_initial_tokens(response.text)
        else:
            cviewstate, eventvalidation = extract_tokens(response.text)

        if not cviewstate or not eventvalidation:
            return

        next_ctl = find_next_ctl(sel, page)
        max_pages = read_max_pages(self.ctx.params)
        if next_ctl and (max_pages is None or page < max_pages):
            yield self.request(
                self.BASE_URL,
                method="POST",
                data=build_payload(next_ctl, cviewstate, eventvalidation),
                headers=ajax_headers(self.BASE_URL),
                metadata={"page": page + 1},
            )

    async def parse_detail(self, response: Response) -> AsyncIterator[Request | dict[str, Any]]:
        """Parse a lot detail page and merge it into the listing item.

        Called only for NEW/CHANGED lots (see ``parse()``) — the decision is by
        fingerprint of the tabular fields. Detail sections go under ``detail``,
        documents under ``attachments``, the price-reduction schedule (only for
        public_offer) under ``price_schedule``.
        """
        item = dict(response.metadata["item"])
        sel = response.selector()
        item["detail"] = parse_detail_sections(sel)
        item["attachments"] = parse_attachments(sel)
        item["price_schedule"] = parse_price_schedule(sel)
        lot_id = item.get("lot_id")
        await self.log(f"{response.request.method} | {response.status} | detail lot_id={lot_id}")
        if lot_id:
            yield Lot.model_validate(item)
