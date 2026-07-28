"""`(key, version)` must always resolve to runnable code — the invariant, as a test."""

from __future__ import annotations

import pytest

from collectors import registry, schemas
from collectors.runners.base import Runner


def test_registry_and_schemas_do_not_drift():
    assert registry.check_registry() == []


def test_every_declared_version_resolves_to_a_runner():
    for descriptor in schemas.all_collectors():
        for version in descriptor.versions:
            runner = registry.resolve(descriptor.key, version.version)
            assert isinstance(runner, Runner)
            assert (runner.key, runner.version) == (descriptor.key, version.version)


def test_versions_resolve_to_different_implementations():
    v1 = registry.resolve("example_api", "1.0")
    v2 = registry.resolve("example_api", "2.0")
    assert type(v1) is not type(v2)


def test_resolution_never_falls_back_to_a_near_version():
    with pytest.raises(registry.UnknownCollectorVersion):
        registry.resolve("example_api", "1.5")
    with pytest.raises(registry.UnknownCollector):
        registry.resolve("not_a_collector", "1.0")
