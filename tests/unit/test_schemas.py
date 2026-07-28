"""Parameter resolution is pure — no DB, no Django, no fixtures."""

from __future__ import annotations

import pytest

from collectors import schemas
from collectors.schemas.base import CollectorVersionSchema, ParamSpec


def test_current_version_is_the_newest_declared():
    assert schemas.current_version("example_api") == "2.0"
    assert schemas.get_collector("example_api").version_names == ("1.0", "2.0")


def test_unknown_collector_and_version_are_distinguishable():
    with pytest.raises(schemas.UnknownCollector):
        schemas.current_version("nope")
    with pytest.raises(schemas.UnknownCollectorVersion):
        schemas.schema("example_api", "99.0")


def test_resolve_applies_defaults():
    effective = schemas.resolve_parameters("example_api", "1.0", {"base_url": "https://x.test"})
    assert effective == {
        "base_url": "https://x.test",
        "path": "/items",
        "page_size": 100,
        "pages": 1,
        "credential_ref": "",
    }


def test_resolve_reports_every_problem_at_once():
    with pytest.raises(schemas.ParameterError) as exc_info:
        schemas.resolve_parameters(
            "example_api", "1.0", {"page_size": 0, "pages": "many", "surprise": 1}
        )
    errors = exc_info.value.errors
    assert any("base_url" in e and "обязательный" in e for e in errors)
    assert any("page_size" in e and ">= 1" in e for e in errors)
    assert any("pages" in e and "ожидается int" in e for e in errors)
    assert any("surprise" in e and "неизвестный параметр" in e for e in errors)


def test_params_valid_for_v1_can_be_invalid_for_v2():
    """The upgrade case: v2.0 made `dataset` required."""
    v1_params = {"base_url": "https://x.test"}
    assert schemas.resolve_parameters("example_api", "1.0", v1_params)

    with pytest.raises(schemas.ParameterError) as exc_info:
        schemas.resolve_parameters("example_api", "2.0", v1_params)
    assert exc_info.value.errors == ["dataset: обязательный параметр"]


def test_bool_is_not_accepted_where_an_int_is_declared():
    spec = ParamSpec(name="n", kind="int")
    assert spec.validate(True) == ["n: ожидается int, получено bool"]
    assert spec.validate(3) == []


def test_int_is_coerced_for_a_float_param():
    schema = CollectorVersionSchema(
        key="k", version="1", schema_version=1, params=(ParamSpec(name="ratio", kind="float"),)
    )
    effective = schema.resolve({"ratio": 2})
    assert isinstance(effective["ratio"], float)


def test_choices_and_bounds_are_enforced():
    spec = ParamSpec(name="mode", kind="str", choices=("a", "b"))
    assert spec.validate("c")
    assert spec.validate("a") == []


def test_credential_refs_are_declared_not_inlined():
    v2 = schemas.schema("example_api", "2.0")
    assert v2.credential_ref_names == ("credential_ref",)
