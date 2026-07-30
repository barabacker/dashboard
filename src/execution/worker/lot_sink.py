"""The Django implementation of the engine's `LotSink` protocol.

Lives here, not in `collectors`: the engine must stay framework-free, and every model belongs to
`control`. The engine never learns this class exists — it is handed in through `RunContext`.

**Why per-lot writes and not batches.** A crawl of one site emits a few hundred lots (the largest
seen so far is ~2200) while making 500–1500 HTTP requests that take minutes. Several hundred local
round trips against Postgres cost a fraction of a second next to that, so batching would trade an
exact `ChangeStatus` per lot for a saving nobody can measure. If a site ever emits lots by the
hundred thousand, revisit — until then this is the simple option, not the lazy one.

**Why the async ORM.** `save` and `get_fingerprints` are awaited from inside the engine's event
loop. Django refuses ORM access from a thread with a running loop, so every query here goes
through the `a*` methods, which hand the work to a thread Django manages itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from collectors.engine.core.lot import Lot
from collectors.engine.core.storage.contracts import ChangeStatus, fingerprint_of
from control.models import Lot as LotRow

#: The sites print civil time without a zone, and `parse_datetime` keeps it naive. Storing that
#: under `USE_TZ = True` would silently read it as UTC and move every deadline by three hours, so
#: the assumption is made explicit here: these are Russian trading platforms publishing Moscow
#: time. The raw string is stored next to the parsed value in `*_date_raw`, so a site that turns
#: out to publish local regional time can be reinterpreted without re-crawling.
SITE_TIMEZONE = ZoneInfo("Europe/Moscow")

#: Written on every save; everything else about a lot row is bookkeeping.
_MUTABLE_FIELDS = (
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


_NULLABLE_FIELDS = frozenset({"price", "bidding_deadline", "result_date"})


def _aware(value: datetime) -> datetime:
    """Pin a site's naive civil time to `SITE_TIMEZONE`; leave an aware value alone."""
    if timezone.is_naive(value):
        return value.replace(tzinfo=SITE_TIMEZONE)
    return value


def _row_values(lot: Lot) -> dict[str, object]:
    """A `Lot` as column values. Text columns are non-null, so `None` becomes `""`."""
    values: dict[str, object] = {}
    for name in _MUTABLE_FIELDS:
        value = getattr(lot, name)
        if isinstance(value, datetime):
            value = _aware(value)
        elif value is None and name not in _NULLABLE_FIELDS:
            value = ""
        values[name] = value
    return values


class DbLotSink:
    """Upserts lots into `control.Lot`, one row per `(source, lot_id)`."""

    def __init__(self, *, job_id: int | None = None) -> None:
        self.job_id = job_id
        self.new = 0
        self.changed = 0
        self.unchanged = 0

    async def get_fingerprints(self, source: str, lot_ids: Sequence[str]) -> dict[str, str]:
        """Batch-read the fingerprints this site already has stored.

        One query per listing page, which is what lets the parser decide for a whole page at once
        whether any detail request is worth making.
        """
        if not lot_ids:
            return {}
        known = LotRow.objects.filter(source=source, lot_id__in=list(lot_ids)).values_list(
            "lot_id", "fingerprint"
        )
        return {lot_id: fingerprint async for lot_id, fingerprint in known}

    async def save(self, item: Lot) -> ChangeStatus:
        """Upsert one lot and report whether it was new, changed, or already known.

        `first_seen_at` is only ever written by the insert (`auto_now_add`), so an update cannot
        move it — a lot is first seen exactly once.
        """
        fingerprint = fingerprint_of(item)
        now = timezone.now()

        row, created = await LotRow.objects.aget_or_create(
            source=item.source,
            lot_id=item.lot_id,
            defaults={
                **_row_values(item),
                "fingerprint": fingerprint,
                "last_seen_at": now,
                "last_job_id": self.job_id,
            },
        )
        if created:
            self.new += 1
            return ChangeStatus.NEW

        unchanged = row.fingerprint == fingerprint
        await LotRow.objects.filter(pk=row.pk).aupdate(
            **_row_values(item),
            fingerprint=fingerprint,
            last_seen_at=now,
            last_job_id=self.job_id,
        )
        if unchanged:
            self.unchanged += 1
            return ChangeStatus.UNCHANGED
        self.changed += 1
        return ChangeStatus.CHANGED
