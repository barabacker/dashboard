"""Mirrors `test_lot_sink.py` — same behaviour contract, Mongo backend.

Uses `mongomock-motor` (an in-memory fake with `motor`'s async API) instead of a real MongoDB
server, so this suite runs without any extra service. It is not a substitute for pointing
`MONGO_URI` at a real Mongo once — only that this sink's own logic (fingerprint comparison, upsert
semantics, index creation) is exercised.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from django.utils import timezone
from mongomock_motor import AsyncMongoMockClient

from collectors.engine.core.lot import Lot
from collectors.engine.core.storage.contracts import ChangeStatus, lot_fingerprint
from execution.worker.mongo_lot_sink import MongoLotSink

SOURCE = "bankrupt.centerr.ru"


@pytest.fixture
def collection():
    return AsyncMongoMockClient()["dashboard-test"]["lots"]


def raw_item(**overrides) -> dict[str, object]:
    """A listing row shaped the way `parse_table` produces one."""
    item = {
        "lot_id": "0025093_1",
        "trade_id": "0025093",
        "trade_number": "0025093",
        "lot_num": "1",
        "debtor": "ООО «Должник»",
        "lot_url": "/public/purchases/view/12345",
        "description": "Право требования",
        "price": 270000.0,
        "price_raw": "270 000,00",
        "organizer": "Организатор",
        "bidding_date": "01.08.2026 10:00",
        "event_date": "15.08.2026",
        "status": "Идут торги",
        "trade_type": "Аукцион",
        "_source": SOURCE,
    }
    item.update(overrides)
    return item


def save_all(sink: MongoLotSink, *lots: Lot) -> list[ChangeStatus]:
    async def run() -> list[ChangeStatus]:
        return [await sink.save(lot) for lot in lots]

    return asyncio.run(run())


def get_one(collection, source: str = SOURCE, lot_id: str = "0025093_1") -> dict:
    async def run() -> dict:
        return await collection.find_one({"source": source, "lot_id": lot_id})

    return asyncio.run(run())


def count(collection) -> int:
    async def run() -> int:
        return await collection.count_documents({})

    return asyncio.run(run())


class TestTheFingerprintRoundTrip:
    def test_what_the_sink_stores_matches_what_the_listing_computes(self, collection):
        item = raw_item()
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(item))

        stored = get_one(collection)
        assert stored["fingerprint"] == lot_fingerprint(item)

    def test_an_unchanged_lot_is_recognised_on_the_next_crawl(self, collection):
        item = raw_item()
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(item))

        second = save_all(MongoLotSink(job_id=2, collection=collection), Lot.model_validate(item))

        assert second == [ChangeStatus.UNCHANGED]

    def test_a_changed_price_is_recognised(self, collection):
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))

        cheaper = raw_item(price=180000.0, price_raw="180 000,00")
        second = save_all(
            MongoLotSink(job_id=2, collection=collection), Lot.model_validate(cheaper)
        )

        assert second == [ChangeStatus.CHANGED]
        assert get_one(collection)["price"] == 180000.0


class TestSaving:
    def test_a_new_lot_is_stored_with_its_fields(self, collection):
        sink = MongoLotSink(job_id=7, collection=collection)
        statuses = save_all(sink, Lot.model_validate(raw_item()))

        assert statuses == [ChangeStatus.NEW]
        assert sink.new == 1
        doc = get_one(collection)
        assert (doc["source"], doc["lot_id"], doc["trade_id"]) == (SOURCE, "0025093_1", "0025093")
        assert doc["price"] == 270000.0
        assert doc["price_raw"] == "270 000,00"
        assert doc["status"] == "Идут торги"
        assert doc["is_active"] is True
        assert doc["last_job_id"] == 7

    def test_it_keeps_both_the_parsed_date_and_the_raw_string(self, collection):
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))

        doc = get_one(collection)
        assert doc["bidding_date_raw"] == "01.08.2026 10:00"
        assert doc["bidding_deadline"] is not None
        assert doc["bidding_deadline"].year == 2026

    def test_a_site_time_is_read_as_moscow_not_as_utc(self, collection):
        """The sites print civil time with no zone. Storing "10:00" as-is (UTC, Mongo's only
        wire format) would move every deadline three hours if the Moscow offset were dropped."""
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))

        deadline = get_one(collection)["bidding_deadline"]
        assert deadline.hour == 7, "10:00 Moscow (UTC+3) must be stored as 07:00 UTC"

    def test_saving_twice_updates_rather_than_duplicates(self, collection):
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))
        save_all(
            MongoLotSink(job_id=2, collection=collection),
            Lot.model_validate(raw_item(status="Торги завершены")),
        )

        assert count(collection) == 1
        doc = get_one(collection)
        assert doc["status"] == "Торги завершены"
        assert doc["is_active"] is False, "closure comes from the site's own status"

    def test_the_same_lot_id_on_two_sites_is_two_lots(self, collection):
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))
        save_all(
            MongoLotSink(job_id=1, collection=collection),
            Lot.model_validate(raw_item(_source="ausib.ru")),
        )

        assert count(collection) == 2

    def test_first_seen_survives_but_last_seen_moves(self, collection):
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))

        async def backdate() -> None:
            three_days_ago = timezone.now() - timedelta(days=3)
            await collection.update_one(
                {"source": SOURCE, "lot_id": "0025093_1"},
                {"$set": {"first_seen_at": three_days_ago, "last_seen_at": three_days_ago}},
            )

        asyncio.run(backdate())
        before = get_one(collection)

        save_all(MongoLotSink(job_id=2, collection=collection), Lot.model_validate(raw_item()))

        after = get_one(collection)
        assert after["first_seen_at"] == before["first_seen_at"], "a lot is first seen only once"
        assert after["last_seen_at"] > before["last_seen_at"]

    def test_a_lot_missing_from_a_crawl_is_left_alone(self, collection):
        """The crawl is truncated by `max_pages`, so absence says nothing about the lot."""
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))

        save_all(
            MongoLotSink(job_id=2, collection=collection),
            Lot.model_validate(raw_item(lot_id="0099999_1")),
        )

        untouched = get_one(collection)
        assert untouched["is_active"] is True
        assert count(collection) == 2

    def test_the_unique_index_matches_the_upsert_identity(self, collection):
        save_all(MongoLotSink(job_id=1, collection=collection), Lot.model_validate(raw_item()))

        async def indexes() -> dict:
            return await collection.index_information()

        info = asyncio.run(indexes())
        assert info["uniq_lot"]["unique"] is True
        assert info["uniq_lot"]["key"] == [("source", 1), ("lot_id", 1)]


class TestGetFingerprints:
    def test_it_answers_only_for_the_asked_source_and_ids(self, collection):
        sink = MongoLotSink(job_id=1, collection=collection)
        save_all(
            sink,
            Lot.model_validate(raw_item()),
            Lot.model_validate(raw_item(lot_id="0025094_1")),
            Lot.model_validate(raw_item(lot_id="0025095_1", _source="ausib.ru")),
        )

        async def ask() -> dict[str, str]:
            return await sink.get_fingerprints(SOURCE, ["0025093_1", "0025095_1", "0000000_9"])

        answer = asyncio.run(ask())

        assert set(answer) == {"0025093_1"}, "other sources and unknown ids must not appear"
        assert answer["0025093_1"] == lot_fingerprint(raw_item())

    def test_it_answers_empty_when_nothing_is_known(self, collection):
        async def ask() -> dict[str, str]:
            return await MongoLotSink(job_id=1, collection=collection).get_fingerprints(
                SOURCE, ["nope"]
            )

        assert asyncio.run(ask()) == {}
