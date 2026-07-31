"""The one Mongo client this process holds.

Built lazily and cached at module scope: a `motor` client owns its own connection pool and is
meant to be created once per process and reused, not once per sink. Sinks ask for a collection
through `get_lots_collection`; nothing outside this module touches the client directly, so tests
can swap in a fake collection without knowing how the client is constructed.
"""

from __future__ import annotations

from django.conf import settings
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

_client: AsyncIOMotorClient | None = None


def get_lots_collection() -> AsyncIOMotorCollection:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGO_URI, tz_aware=True)
    return _client[settings.MONGO_DB_NAME]["lots"]
