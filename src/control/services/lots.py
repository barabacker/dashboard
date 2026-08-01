"""Read-only queries against the `lots` Mongo collection, for the dashboard's lots page.

Nothing here writes — `execution.worker.mongo_lot_sink.MongoLotSink` owns that. `collection` is an
optional injected `pymongo.collection.Collection`, the same dependency-injection shape
`MongoLotSink.__init__` already uses, so tests can pass a `mongomock` collection directly instead of
monkeypatching `get_lots_collection`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.collection import Collection

from control.services.mongo import get_lots_collection

#: Fixed page size for the lots list — no UI to change it, so a plain module constant.
PAGE_SIZE = 50


@dataclass
class LotsPage:
    items: list[dict]
    page: int
    total_pages: int
    total_count: int
    sources: list[str]

    @property
    def page_range(self) -> range:
        return range(1, self.total_pages + 1)


def list_lots(
    *, source: str | None, page: int, collection: Collection | None = None
) -> LotsPage:
    collection = collection if collection is not None else get_lots_collection()
    query: dict[str, object] = {"source": source} if source else {}

    total_count = collection.count_documents(query)
    total_pages = max(1, ceil(total_count / PAGE_SIZE))
    page = min(max(page, 1), total_pages)

    items = list(
        collection.find(query)
        .sort("last_seen_at", -1)
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    sources = sorted(collection.distinct("source"))

    return LotsPage(
        items=items,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        sources=sources,
    )


def get_lot(id: str, *, collection: Collection | None = None) -> dict | None:
    collection = collection if collection is not None else get_lots_collection()
    try:
        object_id = ObjectId(id)
    except InvalidId:
        return None
    return collection.find_one({"_id": object_id})
