"""The one Mongo client this process holds.

Built lazily and cached at module scope: a `pymongo` client owns its own connection pool and is
meant to be created once per process and reused, not once per sink. Sinks ask for a collection
through `get_lots_collection`; nothing outside this module touches the client directly, so tests
can swap in a fake collection without knowing how the client is constructed.

Plain `pymongo`, not `motor`: `motor`'s cursors bind to the asyncio event loop they were created
against, but a worker process runs one `asyncio.run()` per job (see `collectors.engine.run`), each
with its own loop that is closed when the job ends. A `motor` client reused across jobs works for
exactly one job and then fails every job after with "Event loop is closed". `pymongo`'s client
holds no loop reference at all — only a thread-safe connection pool — so the same client is safe to
reuse from however many separate event loops come and go over the process's life. Sink methods stay
`async def` to satisfy the `LotSink` protocol; they offload the blocking pymongo call with
`asyncio.to_thread` (see `mongo_lot_sink.py`).
"""

from __future__ import annotations

from django.conf import settings
from pymongo import MongoClient
from pymongo.collection import Collection

_client: MongoClient | None = None


def get_lots_collection() -> Collection:
    global _client
    if _client is None:
        _client = MongoClient(settings.MONGO_URI, tz_aware=True)
    return _client[settings.MONGO_DB_NAME]["lots"]
