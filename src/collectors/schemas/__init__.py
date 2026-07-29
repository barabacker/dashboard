"""The schema side of the collector registry — the only part of `collectors` that `control` may
import.

It answers three questions and nothing else:

* which collectors exist (for the projection sync and the admin dropdown),
* what is a collector's current version (for enqueue),
* what does `(key, version)` accept (for validation and `effective_parameters`).

Runner code is deliberately absent here; see `collectors/registry.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from collectors.schemas import example_api, tender
from collectors.schemas.base import (
    CollectorDescriptor,
    CollectorVersionSchema,
    ParameterError,
    ParamSpec,
    UnknownCollector,
    UnknownCollectorVersion,
)

__all__ = [
    "CollectorDescriptor",
    "CollectorVersionSchema",
    "ParamSpec",
    "ParameterError",
    "UnknownCollector",
    "UnknownCollectorVersion",
    "all_collectors",
    "current_version",
    "get_collector",
    "resolve_parameters",
    "schema",
]

_DESCRIPTORS: tuple[CollectorDescriptor, ...] = (example_api.DESCRIPTOR, *tender.DESCRIPTORS)

_BY_KEY: dict[str, CollectorDescriptor] = {d.key: d for d in _DESCRIPTORS}


def all_collectors() -> tuple[CollectorDescriptor, ...]:
    """Every collector known to the code, ordered by key."""
    return tuple(sorted(_DESCRIPTORS, key=lambda d: d.key))


def get_collector(key: str) -> CollectorDescriptor:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise UnknownCollector(f"no collector registered under key {key!r}") from None


def current_version(key: str) -> str:
    """The version a *new* Job would run. Resolved at enqueue, then frozen in the snapshot."""
    return get_collector(key).current_version


def schema(key: str, version: str) -> CollectorVersionSchema:
    return get_collector(key).schema(version)


def resolve_parameters(key: str, version: str, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Raw authored params → `effective_parameters` (defaults applied, validated).

    Raises `ParameterError` if they do not satisfy the version's contract.
    """
    return schema(key, version).resolve(raw)
