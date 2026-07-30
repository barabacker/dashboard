"""The schema side of the collector registry — the only part of `collectors` that `control` may
import.

It answers two questions and nothing else:

* which collectors exist (for the projection sync and the admin dropdown),
* what does a collector's schema accept (for validation and `effective_parameters`).

Runner code is deliberately absent here; see `collectors/registry.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from collectors.schemas import example_api, tender
from collectors.schemas.base import (
    CollectorDescriptor,
    ParameterError,
    ParamSpec,
    UnknownCollector,
)

__all__ = [
    "CollectorDescriptor",
    "ParamSpec",
    "ParameterError",
    "UnknownCollector",
    "all_collectors",
    "get_collector",
    "resolve_parameters",
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


def resolve_parameters(key: str, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Raw authored params → `effective_parameters` (defaults applied, validated).

    Raises `ParameterError` if they do not satisfy the collector's contract.
    """
    return get_collector(key).resolve(raw)
