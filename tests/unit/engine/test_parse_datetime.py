"""parse_datetime turns the listing/detail date strings into datetimes."""

from __future__ import annotations

from datetime import datetime

from collectors.engine.core.parsing import parse_datetime


def test_all_observed_formats():
    assert parse_datetime("18.08.2026 13:00:00") == datetime(2026, 8, 18, 13, 0, 0)
    assert parse_datetime("29.07.2026 12:00") == datetime(2026, 7, 29, 12, 0)
    assert parse_datetime("28.08.2026 00:00:00") == datetime(2026, 8, 28, 0, 0)
    # centerr appends a "days left" suffix that must be ignored
    assert parse_datetime("26.08.2026 12:30 (33 дн.)") == datetime(2026, 8, 26, 12, 30)
    # date only
    assert parse_datetime("23.07.2026") == datetime(2026, 7, 23, 0, 0)


def test_unparseable_and_empty():
    assert parse_datetime(None) is None
    assert parse_datetime("") is None
    assert parse_datetime("нет даты") is None
    assert parse_datetime("31.02.2026 10:00") is None  # invalid calendar date
