"""The shape every `LotSink` upserts, shared so the sinks cannot drift apart.

`fingerprint_of` (`collectors.engine.core.storage.contracts`) is computed from a fixed subset of
these values; any sink that stores a differently-shaped `Lot` would silently break the "skip the
detail page" optimisation for whichever backend it writes to. Keeping the field list and the
timezone assumption in one place is what keeps a second sink from reintroducing that bug.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

#: The sites print civil time without a zone, and `parse_datetime` keeps it naive. Storing that
#: under `USE_TZ = True` would silently read it as UTC and move every deadline by three hours, so
#: the assumption is made explicit here: these are Russian trading platforms publishing Moscow
#: time. The raw string is stored next to the parsed value in `*_date_raw`, so a site that turns
#: out to publish local regional time can be reinterpreted without re-crawling.
SITE_TIMEZONE = ZoneInfo("Europe/Moscow")

#: Written on every save; everything else about a stored lot is bookkeeping (identity, fingerprint,
#: first/last seen, last job).
MUTABLE_FIELDS = (
    "trade_id",
    "lot_num",
    "trade_number",
    "trade_type",
    "debtor",
    "organizer",
    "description",
    "lot_url",
    "price",
    "price_raw",
    "status",
    "is_active",
    "bidding_deadline",
    "result_date",
    "bidding_date_raw",
    "event_date_raw",
    "attachments",
    "price_schedule",
    "extra",
)


def aware(value: datetime) -> datetime:
    """Pin a site's naive civil time to `SITE_TIMEZONE`; leave an aware value alone."""
    if timezone.is_naive(value):
        return value.replace(tzinfo=SITE_TIMEZONE)
    return value
