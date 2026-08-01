"""A second Mongo client, for the web process's read path.

`execution.worker.mongo` owns the worker's client, but `control` may not import `execution` (see
the "control does not import execution" contract in `pyproject.toml`) — the web process and the
worker process are separate processes anyway, so this is its own lazily-cached
`pymongo.MongoClient`, mirroring that module's pattern rather than reusing its code.
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
