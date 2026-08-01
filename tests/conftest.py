from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from control.models import Config, Schedule


def make_lot(collection, **overrides) -> dict:
    """Insert a lot document into a mongomock `lots` collection and return it (with `_id` set).

    Shared by `test_lots_service.py` (the service layer, via mongomock directly) and
    `test_dashboard_lots.py` (the HTTP layer, via a monkeypatched `get_lots_collection`) — both
    mirror `test_mongo_lot_sink.py`'s mongomock pattern for a fake `pymongo` collection.
    """
    doc = {
        "source": "bankrupt.centerr.ru",
        "lot_id": "0025093_1",
        "lot_num": "1",
        "status": "Идут торги",
        "is_active": True,
        "price": 270000.0,
        "bidding_deadline": None,
        "debtor": None,
        "lot_url": None,
        "attachments": [],
        "price_schedule": [],
        "extra": {},
    }
    doc.update(overrides)
    doc.setdefault("last_seen_at", timezone.now())
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


VALID_PARAMS = {
    "base_url": "https://api.example.com",
    "path": "/items",
    "page_size": 10,
    "pages": 2,
    "dataset": "orders",
}


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="tester", password="pw", is_staff=True, is_superuser=True
    )


@pytest.fixture
def make_config(db):
    def _make(**overrides) -> Config:
        defaults = {
            "name": "cfg",
            "collector_key": "example_api",
            "parameters": dict(VALID_PARAMS),
            "enabled": True,
        }
        return Config.objects.create(**{**defaults, **overrides})

    return _make


@pytest.fixture
def config(make_config) -> Config:
    return make_config()


@pytest.fixture
def make_schedule(db):
    def _make(config: Config, **overrides) -> Schedule:
        defaults = {"cron": "*/5 * * * *", "timezone": "UTC", "enabled": True}
        return Schedule.objects.create(config=config, **{**defaults, **overrides})

    return _make
