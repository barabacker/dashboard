"""Schemas for the `example_api` collector.

Two versions ship on purpose so version resolution is exercised end to end:

* **v1.0** — the original contract.
* **v2.0** — adds a **required** `dataset` parameter. That makes the "schedules survive collector
  upgrades, but a scheduled run with now-invalid params fails fast" invariant real and testable,
  rather than a sentence in a document.

Historical versions are never edited in place. A change to v1.0's contract would silently
invalidate every Job snapshot that references it.
"""

from __future__ import annotations

from collectors.schemas.base import CollectorDescriptor, CollectorVersionSchema, ParamSpec

KEY = "example_api"

_BASE_URL = ParamSpec(
    name="base_url",
    kind="str",
    required=True,
    description="Root URL of the source API. Part of *what was collected* — snapshotted.",
)
_PATH = ParamSpec(
    name="path",
    kind="str",
    default="/items",
    description="Endpoint path appended to base_url.",
)
_PAGE_SIZE = ParamSpec(
    name="page_size",
    kind="int",
    default=100,
    min_value=1,
    max_value=1000,
    description="Rows requested per page.",
)
_PAGES = ParamSpec(
    name="pages",
    kind="int",
    default=1,
    min_value=1,
    max_value=100,
    description="How many pages to walk. Each page is a cancellation checkpoint.",
)
_CREDENTIAL_REF = ParamSpec(
    name="credential_ref",
    kind="str",
    default="",
    is_credential_ref=True,
    description=(
        "Name of the environment variable holding the API token. The *name* is snapshotted; "
        "the token itself is resolved at execution time and never stored on the Job."
    ),
)

V1 = CollectorVersionSchema(
    key=KEY,
    version="1.0",
    schema_version=1,
    summary="Paginated fetch from a single endpoint.",
    params=(_BASE_URL, _PATH, _PAGE_SIZE, _PAGES, _CREDENTIAL_REF),
)

V2 = CollectorVersionSchema(
    key=KEY,
    version="2.0",
    schema_version=2,
    summary="Adds an explicit dataset selector; rows are tagged with it.",
    params=(
        _BASE_URL,
        _PATH,
        _PAGE_SIZE,
        _PAGES,
        _CREDENTIAL_REF,
        ParamSpec(
            name="dataset",
            kind="str",
            required=True,
            description="Which dataset to pull. Required from v2.0 on.",
        ),
        ParamSpec(
            name="since",
            kind="str",
            default="",
            description="Optional ISO-8601 lower bound passed to the API as a filter.",
        ),
        ParamSpec(
            name="page_delay_seconds",
            kind="float",
            default=0.0,
            min_value=0.0,
            max_value=60.0,
            description="Artificial per-page pause. Exists so cancellation is observable on a "
            "run long enough to catch in the act.",
        ),
    ),
)

DESCRIPTOR = CollectorDescriptor(
    key=KEY,
    display_name="Example API",
    description=(
        "Reference collector used to exercise version resolution, parameter validation and "
        "cooperative cancellation. It fabricates rows instead of doing network I/O so tests stay "
        "deterministic."
    ),
    versions=(V1, V2),
)
