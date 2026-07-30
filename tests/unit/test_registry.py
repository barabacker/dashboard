"""Every collector key must resolve to runnable code — the invariant, as a test."""

from __future__ import annotations

import pytest

from collectors import registry, schemas
from collectors.runners.base import Runner


def test_registry_and_schemas_do_not_drift():
    assert registry.check_registry() == []


def test_every_declared_collector_resolves_to_a_runner():
    for descriptor in schemas.all_collectors():
        runner = registry.resolve(descriptor.key)
        assert isinstance(runner, Runner)
        assert runner.key == descriptor.key


def test_resolution_never_falls_back_to_a_near_key():
    with pytest.raises(registry.UnknownCollector):
        registry.resolve("not_a_collector")
