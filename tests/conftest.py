from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from control.models import Config, Schedule

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
            "archived": False,
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
