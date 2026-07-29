"""Resolve `(key, version)` to runnable code.

The **execution-side** half of the registry. It imports runner code, which is why `control` is
forbidden from importing this module: `control` gets its answers from `collectors.schemas`, which
holds no implementations.

The registration table is explicit rather than discovered by scanning the package. A snapshot that
cannot resolve is a broken deploy, and an explicit table makes that a startup-time error you can
read, not an import-order accident.
"""

from __future__ import annotations

from collectors import schemas
from collectors.runners import example_api_v1, example_api_v2, tender_site_v1
from collectors.runners.base import Runner
from collectors.schemas import (
    CollectorDescriptor,
    CollectorVersionSchema,
    UnknownCollector,
    UnknownCollectorVersion,
)

__all__ = [
    "UnknownCollector",
    "UnknownCollectorVersion",
    "all_collectors",
    "check_registry",
    "current_version",
    "known_pairs",
    "resolve",
    "schema",
]

_RUNNERS: dict[tuple[str, str], type[Runner]] = {
    (example_api_v1.KEY, example_api_v1.VERSION): example_api_v1.ExampleApiV1,
    (example_api_v2.KEY, example_api_v2.VERSION): example_api_v2.ExampleApiV2,
    # One per parser family. The four differ only in which engine they crawl with, so they are
    # generated from the same list the schemas are — `check_registry` still holds each of them
    # to the key it declares.
    **tender_site_v1.RUNNERS,
}


def resolve(key: str, version: str) -> Runner:
    """The snapshot's `(key, version)` → an instance ready to `run()`.

    Never falls back to "the closest version". A snapshot means a specific implementation or
    nothing at all.
    """
    try:
        runner_class = _RUNNERS[(key, version)]
    except KeyError:
        if key not in {k for k, _ in _RUNNERS}:
            raise UnknownCollector(f"no runner registered for collector {key!r}") from None
        available = sorted(v for k, v in _RUNNERS if k == key)
        raise UnknownCollectorVersion(
            f"collector {key!r} has no runner for version {version!r} "
            f"(registered: {', '.join(available)})"
        ) from None
    return runner_class()


def known_pairs() -> tuple[tuple[str, str], ...]:
    return tuple(sorted(_RUNNERS))


def schema(key: str, version: str) -> CollectorVersionSchema:
    """Re-exported for symmetry — the schema side is `collectors.schemas`."""
    return schemas.schema(key, version)


def current_version(key: str) -> str:
    return schemas.current_version(key)


def all_collectors() -> tuple[CollectorDescriptor, ...]:
    return schemas.all_collectors()


def check_registry() -> list[str]:
    """Every declared version has a runner, and every runner has a declared version.

    A drift either way breaks the `(key, version)` invariant: a schema without a runner produces
    jobs nothing can execute, a runner without a schema can never be enqueued. Returns the
    problems found so a test or a deploy check can assert emptiness.
    """
    problems: list[str] = []

    declared = {
        (descriptor.key, version.version)
        for descriptor in schemas.all_collectors()
        for version in descriptor.versions
    }
    registered = set(_RUNNERS)

    for key, version in sorted(declared - registered):
        problems.append(f"{key} v{version}: schema declared but no runner registered")
    for key, version in sorted(registered - declared):
        problems.append(f"{key} v{version}: runner registered but no schema declared")

    for (key, version), runner_class in sorted(_RUNNERS.items()):
        if (runner_class.key, runner_class.version) != (key, version):
            problems.append(
                f"{key} v{version}: registered under the wrong key — the class declares "
                f"{runner_class.key} v{runner_class.version}"
            )

    return problems
