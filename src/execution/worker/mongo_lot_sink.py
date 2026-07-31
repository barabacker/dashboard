"""The Mongo implementation of the engine's `LotSink` protocol.

Lots vary in shape by collector family (tender platforms today, other trading data later), which
is exactly what a fixed-column Postgres table fights against — every new attribute is a migration.
Mongo stores each `Lot` close to as-is; `MUTABLE_FIELDS` (see `lot_fields`) is still the contract
that keeps this sink's documents comparable to `DbLotSink`'s rows and to what `fingerprint_of`
hashes, but nothing here needs a schema migration to grow.

**Identity, not history.** Same rule as `DbLotSink`: `(source, lot_id)` is upserted in place, a
crawl converges rather than accumulates, and a lot missing from a pass says nothing about the lot
(see `control.models.Lot`'s docstring). A collector whose items are observations over time — a
price on a given day — needs a different sink, one that inserts rather than upserts; this one is
for lots specifically.
"""

from __future__ import annotations

import weakref
from collections.abc import Sequence
from datetime import datetime

from django.utils import timezone
from pymongo import ReturnDocument

from collectors.engine.core.lot import Lot
from collectors.engine.core.storage.contracts import ChangeStatus, fingerprint_of
from execution.worker.lot_fields import MUTABLE_FIELDS, aware
from execution.worker.mongo import get_lots_collection

#: Per-client set of "db.collection" names already indexed, keyed by `id(client)` rather than the
#: client object itself: some client implementations (mongomock's fake among them) override
#: `__eq__` in ways that make unrelated instances compare equal, which would poison a
#: `WeakKeyDictionary` keyed on the object directly. `weakref.finalize` below drops the entry when
#: the client dies, so a later object reusing that id starts with a clean slate.
_indexed_collections: dict[int, set[str]] = {}


async def _ensure_indexes(collection) -> None:
    """Create the sink's indexes once per collection per client.

    `create_index` is idempotent, so calling it more than once is harmless — this just keeps a warm
    worker from paying the round trip on every save.
    """
    client = collection.database.client
    client_id = id(client)
    if client_id not in _indexed_collections:
        _indexed_collections[client_id] = set()
        weakref.finalize(client, _indexed_collections.pop, client_id, None)
    seen = _indexed_collections[client_id]
    key = f"{collection.database.name}.{collection.name}"
    if key in seen:
        return
    await collection.create_index([("source", 1), ("lot_id", 1)], unique=True, name="uniq_lot")
    await collection.create_index([("source", 1), ("is_active", 1)], name="lot_by_source_active")
    await collection.create_index([("last_seen_at", -1)], name="lot_by_last_seen")
    seen.add(key)


def _document_fields(lot: Lot) -> dict[str, object]:
    """A `Lot` as document fields. Unlike the Postgres sink, `None` stays `None` — Mongo has no
    column to be non-null for."""
    values: dict[str, object] = {}
    for name in MUTABLE_FIELDS:
        value = getattr(lot, name)
        if isinstance(value, datetime):
            value = aware(value)
        values[name] = value
    return values


class MongoLotSink:
    """Upserts lots into the `lots` Mongo collection, one document per `(source, lot_id)`."""

    def __init__(self, *, job_id: int | None = None, collection=None) -> None:
        self.job_id = job_id
        self._collection = collection if collection is not None else get_lots_collection()
        self.new = 0
        self.changed = 0
        self.unchanged = 0

    async def get_fingerprints(self, source: str, lot_ids: Sequence[str]) -> dict[str, str]:
        """Batch-read the fingerprints this site already has stored."""
        if not lot_ids:
            return {}
        await _ensure_indexes(self._collection)
        cursor = self._collection.find(
            {"source": source, "lot_id": {"$in": list(lot_ids)}},
            projection={"_id": False, "lot_id": True, "fingerprint": True},
        )
        return {doc["lot_id"]: doc["fingerprint"] async for doc in cursor}

    async def save(self, item: Lot) -> ChangeStatus:
        """Upsert one lot and report whether it was new, changed, or already known.

        `first_seen_at` is written only through `$setOnInsert`, so an update cannot move it — a lot
        is first seen exactly once.
        """
        await _ensure_indexes(self._collection)
        fingerprint = fingerprint_of(item)
        now = timezone.now()

        before = await self._collection.find_one_and_update(
            {"source": item.source, "lot_id": item.lot_id},
            {
                "$set": {
                    **_document_fields(item),
                    "fingerprint": fingerprint,
                    "last_seen_at": now,
                    "last_job_id": self.job_id,
                },
                "$setOnInsert": {"first_seen_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.BEFORE,
        )
        if before is None:
            self.new += 1
            return ChangeStatus.NEW
        if before.get("fingerprint") == fingerprint:
            self.unchanged += 1
            return ChangeStatus.UNCHANGED
        self.changed += 1
        return ChangeStatus.CHANGED
