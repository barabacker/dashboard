"""Unit tests for the read-only lots query layer — mirrors test_mongo_lot_sink.py's use of
mongomock for a fake pymongo collection, but exercises reads instead of the sink's writes."""

from __future__ import annotations

from datetime import timedelta

import mongomock
import pytest
from bson import ObjectId
from django.utils import timezone

import control.services.lots as lots_module
from control.services.lots import get_lot, list_lots


@pytest.fixture
def collection():
    return mongomock.MongoClient()["dashboard-test"]["lots"]


def make_lot(collection, **overrides) -> dict:
    doc = {
        "source": "bankrupt.centerr.ru",
        "lot_id": "0025093_1",
        "lot_num": "1",
        "status": "Идут торги",
        "is_active": True,
        "price": 270000.0,
        "bidding_deadline": None,
        "attachments": [],
        "price_schedule": [],
        "extra": {},
    }
    doc.update(overrides)
    doc.setdefault("last_seen_at", timezone.now())
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


class TestListLots:
    def test_returns_all_lots_when_no_source_filter_is_given(self, collection):
        make_lot(collection, lot_id="a", source="site-a")
        make_lot(collection, lot_id="b", source="site-b")

        page = list_lots(source=None, page=1, collection=collection)

        assert page.total_count == 2
        assert {item["lot_id"] for item in page.items} == {"a", "b"}

    def test_filters_by_source(self, collection):
        make_lot(collection, lot_id="a", source="site-a")
        make_lot(collection, lot_id="b", source="site-b")

        page = list_lots(source="site-a", page=1, collection=collection)

        assert [item["lot_id"] for item in page.items] == ["a"]
        assert page.total_count == 1

    def test_orders_by_last_seen_at_descending(self, collection):
        older = timezone.now() - timedelta(days=1)
        newer = timezone.now()
        make_lot(collection, lot_id="old", last_seen_at=older)
        make_lot(collection, lot_id="new", last_seen_at=newer)

        page = list_lots(source=None, page=1, collection=collection)

        assert [item["lot_id"] for item in page.items] == ["new", "old"]

    def test_paginates_using_the_page_size(self, collection, monkeypatch):
        monkeypatch.setattr(lots_module, "PAGE_SIZE", 2)
        for i in range(5):
            make_lot(
                collection, lot_id=str(i), last_seen_at=timezone.now() + timedelta(seconds=i)
            )

        first = list_lots(source=None, page=1, collection=collection)
        second = list_lots(source=None, page=2, collection=collection)

        assert len(first.items) == 2
        assert len(second.items) == 2
        assert first.total_pages == 3
        first_ids = {item["lot_id"] for item in first.items}
        second_ids = {item["lot_id"] for item in second.items}
        assert first_ids.isdisjoint(second_ids)

    def test_out_of_range_page_clamps_to_the_last_page(self, collection):
        make_lot(collection, lot_id="only")

        page = list_lots(source=None, page=99, collection=collection)

        assert page.page == 1

    def test_lists_distinct_sources_regardless_of_the_active_filter(self, collection):
        make_lot(collection, lot_id="a", source="site-a")
        make_lot(collection, lot_id="b", source="site-b")

        page = list_lots(source="site-a", page=1, collection=collection)

        assert page.sources == ["site-a", "site-b"]


class TestGetLot:
    def test_returns_the_matching_document(self, collection):
        stored = make_lot(collection)

        found = get_lot(str(stored["_id"]), collection=collection)

        assert found["lot_id"] == "0025093_1"

    def test_returns_none_for_an_id_that_does_not_exist(self, collection):
        assert get_lot(str(ObjectId()), collection=collection) is None

    def test_returns_none_for_a_malformed_id(self, collection):
        assert get_lot("not-an-object-id", collection=collection) is None
