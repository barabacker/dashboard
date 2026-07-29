"""Which trade statuses count as live (drives the stop-at-archive rule)."""

from __future__ import annotations

import pytest

from collectors.engine.core.parsing import (
    is_active_status,
    pick_status,
    read_concurrency,
    read_only_active,
)


@pytest.mark.parametrize(
    "status",
    [
        "Торги объявлены",
        "Идет прием заявок",
        "идёт приём заявок",
        "Объявлен",
        "Прием ценовых предложений",
        "На утверждении",
        None,
        "",
        "какой-то новый статус",  # unknown -> live, never truncate on doubt
    ],
)
def test_live_statuses(status):
    assert is_active_status(status) is True


@pytest.mark.parametrize(
    "status",
    [
        "Торги завершены",
        "Прием заявок завершен",  # contains "прием заявок" but is finished
        "Торги отменены",
        "Торги приостановлены",
        "Торги состоялись",
        "Торги не состоялись",
        "Окончен",  # fogsoft's finished status (окончен/окончено/окончены)
        "Окончено",
        "Торги окончены",
        "Прием заявок окончен",
    ],
)
def test_finished_statuses(status):
    assert is_active_status(status) is False


def test_okonchanie_in_a_live_status_is_not_treated_as_finished():
    # "окончание приёма заявок" (a live cell) must not match the "окончен" marker.
    assert is_active_status("Окончание приёма заявок 28.08.2026") is True


def test_pick_status_finds_the_status_cell():
    cells = [
        "68240-ОАОФ",
        "Чахоян Кима Самвеловна",
        "Очень длинное описание предмета торгов, которое статусом не является "
        "и потому должно быть пропущено",
        "Торги объявлены",
    ]
    assert pick_status(cells) == "Торги объявлены"
    assert pick_status(["12345-ОАОФ", "Иванов И.И."]) is None


def test_read_only_active_defaults_on_and_can_be_disabled():
    assert read_only_active({}) is True
    assert read_only_active({"only_active": "1"}) is True
    assert read_only_active({"only_active": "0"}) is False
    assert read_only_active({"only_active": "false"}) is False


def test_read_concurrency_falls_back_to_default():
    assert read_concurrency({}, 1) == 1
    assert read_concurrency({}, 4) == 4
    assert read_concurrency({"concurrency": ""}, 2) == 2
    assert read_concurrency({"concurrency": "8"}, 1) == 8
    assert read_concurrency({"concurrency": "0"}, 3) == 3  # non-positive -> default
    assert read_concurrency({"concurrency": "oops"}, 5) == 5  # invalid -> default
