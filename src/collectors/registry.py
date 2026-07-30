"""Resolve a collector key to runnable code.

The **execution-side** half of the registry. It imports runner code, which is why `control` is
forbidden from importing this module: `control` gets its answers from `collectors.schemas`, which
holds no implementations.

The registration table is explicit rather than discovered by scanning the package. A snapshot that
cannot resolve is a broken deploy, and an explicit table makes that a startup-time error you can
read, not an import-order accident.
"""

from __future__ import annotations

from collectors import schemas
from collectors.runners import example_api, tender_site
from collectors.runners.base import Runner
from collectors.schemas import CollectorDescriptor, UnknownCollector

__all__ = [
    "UnknownCollector",
    "all_collectors",
    "check_registry",
    "known_keys",
    "resolve",
]

_RUNNERS: dict[str, type[Runner]] = {
    example_api.KEY: example_api.ExampleApi,
    # One per parser family. The four differ only in which engine they crawl with, so they are
    # generated from the same list the schemas are — `check_registry` still holds each of them
    # to the key it declares.
    **tender_site.RUNNERS,
}


def resolve(key: str) -> Runner:
    """The snapshot's collector key → an instance ready to `run()`."""
    try:
        runner_class = _RUNNERS[key]
    except KeyError:
        raise UnknownCollector(f"no runner registered for collector {key!r}") from None
    return runner_class()


def known_keys() -> tuple[str, ...]:
    return tuple(sorted(_RUNNERS))


def all_collectors() -> tuple[CollectorDescriptor, ...]:
    return schemas.all_collectors()


def check_registry() -> list[str]:
    """Every declared schema has a runner, and every runner has a declared schema.

    A drift either way breaks the invariant that every collector key resolves to code: a schema
    without a runner produces jobs nothing can execute, a runner without a schema can never be
    enqueued. Returns the problems found so a test or a deploy check can assert emptiness.
    """
    problems: list[str] = []

    declared = {descriptor.key for descriptor in schemas.all_collectors()}
    registered = set(_RUNNERS)

    for key in sorted(declared - registered):
        problems.append(f"{key}: schema declared but no runner registered")
    for key in sorted(registered - declared):
        problems.append(f"{key}: runner registered but no schema declared")

    for key, runner_class in sorted(_RUNNERS.items()):
        if runner_class.key != key:
            problems.append(
                f"{key}: registered under the wrong key — the class declares {runner_class.key}"
            )

    return problems
