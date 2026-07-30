"""Parameter resolution is pure — no DB, no Django, no fixtures."""

from __future__ import annotations

import pytest

from collectors import schemas
from collectors.schemas.base import CollectorDescriptor, ParamSpec


def test_unknown_collector_raises():
    with pytest.raises(schemas.UnknownCollector):
        schemas.get_collector("nope")
    with pytest.raises(schemas.UnknownCollector):
        schemas.resolve_parameters("nope", {})


def test_resolve_applies_defaults():
    effective = schemas.resolve_parameters(
        "example_api", {"base_url": "https://x.test", "dataset": "orders"}
    )
    assert effective == {
        "base_url": "https://x.test",
        "dataset": "orders",
        "path": "/items",
        "page_size": 100,
        "pages": 1,
        "credential_ref": "",
        "since": "",
        "page_delay_seconds": 0.0,
    }


def test_resolve_reports_every_problem_at_once():
    with pytest.raises(schemas.ParameterError) as exc_info:
        schemas.resolve_parameters("example_api", {"page_size": 0, "pages": "many", "surprise": 1})
    errors = exc_info.value.errors
    assert any("base_url" in e and "обязательный" in e for e in errors)
    assert any("page_size" in e and ">= 1" in e for e in errors)
    assert any("pages" in e and "ожидается int" in e for e in errors)
    assert any("surprise" in e and "неизвестный параметр" in e for e in errors)
    assert any("dataset" in e and "обязательный" in e for e in errors)


def test_dataset_is_required():
    """The one parameter this reference collector cannot default: it names what to pull."""
    with pytest.raises(schemas.ParameterError) as exc_info:
        schemas.resolve_parameters("example_api", {"base_url": "https://x.test"})
    assert exc_info.value.errors == ["dataset: обязательный параметр"]


def test_bool_is_not_accepted_where_an_int_is_declared():
    spec = ParamSpec(name="n", kind="int")
    assert spec.validate(True) == ["n: ожидается int, получено bool"]
    assert spec.validate(3) == []


def test_int_is_coerced_for_a_float_param():
    descriptor = CollectorDescriptor(
        key="k", display_name="K", params=(ParamSpec(name="ratio", kind="float"),)
    )
    effective = descriptor.resolve({"ratio": 2})
    assert isinstance(effective["ratio"], float)


def test_choices_and_bounds_are_enforced():
    spec = ParamSpec(name="mode", kind="str", choices=("a", "b"))
    assert spec.validate("c")
    assert spec.validate("a") == []


def test_credential_refs_are_declared_not_inlined():
    descriptor = schemas.get_collector("example_api")
    assert descriptor.credential_ref_names == ("credential_ref",)
