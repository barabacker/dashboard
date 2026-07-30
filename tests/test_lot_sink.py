"""Storing collected lots: the Django sink behind the engine's `LotSink` protocol.

The load-bearing test here is the fingerprint round-trip. `lot_fingerprint` is computed by the
listing parser on its **raw** dict (`bidding_date`, `event_date`), while `save()` receives a
normalized `Lot` where those keys no longer exist. If the sink stores a fingerprint derived from
different values, it can never match on the next crawl — every lot reads as changed forever and
the "skip the detail page" optimization silently never fires. Nothing else would fail; the crawl
would just quietly cost several times more.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from asgiref.sync import sync_to_async
from django.db import connections
from django.utils import timezone

from collectors.engine.core.lot import Lot
from collectors.engine.core.storage.contracts import ChangeStatus, lot_fingerprint
from control.models import Lot as LotRow
from execution.worker.lot_sink import SITE_TIMEZONE, DbLotSink


def in_a_loop[T](work: Callable[[], Awaitable[T]]) -> T:
    """Run `work` the way the engine does — inside an event loop.

    Django's async ORM does its queries in an executor thread it keeps alive, so that thread's
    connection outlives `asyncio.run` and would block dropping the test database. Production wants
    exactly that reuse; a test has to hand it back, and the only way to reach that thread is to be
    scheduled onto it.
    """

    async def runner() -> T:
        try:
            return await work()
        finally:
            await sync_to_async(connections.close_all)()

    return asyncio.run(runner())


pytestmark = pytest.mark.django_db(transaction=True)

SOURCE = "bankrupt.centerr.ru"


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


def save_all(sink: DbLotSink, *lots: Lot) -> list[ChangeStatus]:
    """Drive the sink the way the engine does — from inside an event loop."""

    async def run() -> list[ChangeStatus]:
        return [await sink.save(lot) for lot in lots]

    return in_a_loop(run)


class TestTheFingerprintRoundTrip:
    def test_what_the_sink_stores_matches_what_the_listing_computes(self):
        item = raw_item()
        save_all(DbLotSink(job_id=1), Lot.model_validate(item))

        stored = LotRow.objects.get(source=SOURCE, lot_id="0025093_1")
        assert stored.fingerprint == lot_fingerprint(item)

    def test_an_unchanged_lot_is_recognised_on_the_next_crawl(self):
        item = raw_item()
        save_all(DbLotSink(job_id=1), Lot.model_validate(item))

        second = save_all(DbLotSink(job_id=2), Lot.model_validate(item))

        assert second == [ChangeStatus.UNCHANGED]

    def test_a_changed_price_is_recognised(self):
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))

        cheaper = raw_item(price=180000.0, price_raw="180 000,00")
        second = save_all(DbLotSink(job_id=2), Lot.model_validate(cheaper))

        assert second == [ChangeStatus.CHANGED]
        assert LotRow.objects.get(source=SOURCE, lot_id="0025093_1").price == 180000.0


class TestSaving:
    def test_a_new_lot_is_stored_with_its_fields(self):
        statuses = save_all(DbLotSink(job_id=7), Lot.model_validate(raw_item()))

        assert statuses == [ChangeStatus.NEW]
        row = LotRow.objects.get()
        assert (row.source, row.lot_id, row.trade_id) == (SOURCE, "0025093_1", "0025093")
        assert row.price == 270000.0
        assert row.price_raw == "270 000,00"
        assert row.status == "Идут торги"
        assert row.is_active is True
        assert row.last_job_id == 7

    def test_it_keeps_both_the_parsed_date_and_the_raw_string(self):
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))

        row = LotRow.objects.get()
        assert row.bidding_date_raw == "01.08.2026 10:00"
        assert row.bidding_deadline is not None
        assert row.bidding_deadline.year == 2026

    def test_a_site_time_is_read_as_moscow_not_as_utc(self):
        """The sites print civil time with no zone. Reading "10:00" as UTC would move every
        deadline three hours; the assumption has to be visible somewhere."""
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))

        deadline = LotRow.objects.get().bidding_deadline
        assert deadline.utcoffset() is not None, "a naive deadline would be read as UTC"
        assert deadline.astimezone(SITE_TIMEZONE).hour == 10

    def test_saving_twice_updates_rather_than_duplicates(self):
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))
        save_all(DbLotSink(job_id=2), Lot.model_validate(raw_item(status="Торги завершены")))

        assert LotRow.objects.count() == 1
        row = LotRow.objects.get()
        assert row.status == "Торги завершены"
        assert row.is_active is False, "closure comes from the site's own status"

    def test_the_same_lot_id_on_two_sites_is_two_lots(self):
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item(_source="ausib.ru")))

        assert LotRow.objects.count() == 2

    def test_first_seen_survives_but_last_seen_moves(self):
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))
        first = LotRow.objects.get()
        LotRow.objects.filter(pk=first.pk).update(
            first_seen_at=timezone.now() - timezone.timedelta(days=3),
            last_seen_at=timezone.now() - timezone.timedelta(days=3),
        )
        before = LotRow.objects.get()

        save_all(DbLotSink(job_id=2), Lot.model_validate(raw_item()))

        after = LotRow.objects.get()
        assert after.first_seen_at == before.first_seen_at, "a lot is first seen only once"
        assert after.last_seen_at > before.last_seen_at

    def test_a_lot_missing_from_a_crawl_is_left_alone(self):
        """The crawl is truncated by `max_pages`, so absence says nothing about the lot."""
        save_all(DbLotSink(job_id=1), Lot.model_validate(raw_item()))
        untouched = LotRow.objects.get()

        save_all(DbLotSink(job_id=2), Lot.model_validate(raw_item(lot_id="0099999_1")))

        untouched.refresh_from_db()
        assert untouched.is_active is True
        assert LotRow.objects.count() == 2


class TestGetFingerprints:
    def test_it_answers_only_for_the_asked_source_and_ids(self):
        sink = DbLotSink(job_id=1)
        save_all(
            sink,
            Lot.model_validate(raw_item()),
            Lot.model_validate(raw_item(lot_id="0025094_1")),
            Lot.model_validate(raw_item(lot_id="0025095_1", _source="ausib.ru")),
        )

        async def ask() -> dict[str, str]:
            return await sink.get_fingerprints(SOURCE, ["0025093_1", "0025095_1", "0000000_9"])

        answer = in_a_loop(ask)

        assert set(answer) == {"0025093_1"}, "other sources and unknown ids must not appear"
        assert answer["0025093_1"] == lot_fingerprint(raw_item())

    def test_it_answers_empty_when_nothing_is_known(self):
        async def ask() -> dict[str, str]:
            return await DbLotSink(job_id=1).get_fingerprints(SOURCE, ["nope"])

        assert in_a_loop(ask) == {}
