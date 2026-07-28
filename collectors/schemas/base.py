"""Pure parameter-schema descriptors.

No Django, no I/O, no project imports. `control` reads this module to validate authored
parameters and build the snapshot's `effective_parameters`; `execution` never needs it directly
(the snapshot already carries resolved values).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CollectorDescriptor",
    "CollectorVersionSchema",
    "ParamSpec",
    "ParameterError",
    "UnknownCollector",
    "UnknownCollectorVersion",
]

_MISSING = object()


class ParameterError(ValueError):
    """Authored parameters do not satisfy a collector version's schema.

    Carries every problem found, not just the first: the admin shows them all at once.
    """

    def __init__(self, key: str, version: str, errors: Sequence[str]) -> None:
        self.collector_key = key
        self.collector_version = version
        self.errors = list(errors)
        super().__init__(
            f"config invalid for collector {key} v{version}: " + "; ".join(self.errors)
        )


class UnknownCollector(LookupError):
    """No collector is registered under this key."""


class UnknownCollectorVersion(LookupError):
    """The collector exists but has no such version.

    Raised only for keys/versions that were never shipped. A version that *was* shipped must stay
    resolvable forever — see the `(key, version)` invariant in CLAUDE.md.
    """


# --- parameter kinds ------------------------------------------------------------------
# Deliberately a tiny closed set rather than JSON Schema: enough to type-check, default and
# validate authored parameters, with no extra dependency (decision D4 in CLAUDE.md).

_KIND_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (float, int),
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
}


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One authored parameter of one collector version."""

    name: str
    kind: str
    required: bool = False
    default: Any = None
    choices: tuple[Any, ...] | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None
    description: str = ""
    #: True when the value is a *reference* to a credential (an env var / secret-store key),
    #: never the credential itself. Referenced values are snapshotted; secrets never are (§4).
    is_credential_ref: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _KIND_TYPES:
            raise ValueError(f"{self.name}: unknown kind {self.kind!r}")

    def coerce(self, value: Any) -> Any:
        """Normalise a value that is already of an acceptable type."""
        if self.kind == "float" and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        return value

    def validate(self, value: Any) -> list[str]:
        """Return a list of problems with `value`; empty means valid."""
        expected = _KIND_TYPES[self.kind]
        # bool is a subclass of int in Python — an int param must not silently accept True.
        if self.kind in {"int", "float"} and isinstance(value, bool):
            return [f"{self.name}: expected {self.kind}, got bool"]
        if not isinstance(value, expected):
            return [f"{self.name}: expected {self.kind}, got {type(value).__name__}"]

        problems: list[str] = []
        if self.choices is not None and value not in self.choices:
            problems.append(f"{self.name}: must be one of {list(self.choices)!r}, got {value!r}")
        if self.min_value is not None and value < self.min_value:
            problems.append(f"{self.name}: must be >= {self.min_value}, got {value!r}")
        if self.max_value is not None and value > self.max_value:
            problems.append(f"{self.name}: must be <= {self.max_value}, got {value!r}")
        return problems


@dataclass(frozen=True, slots=True)
class CollectorVersionSchema:
    """The parameter contract of exactly one `(collector_key, version)` pair."""

    key: str
    version: str
    schema_version: int
    params: tuple[ParamSpec, ...] = ()
    summary: str = ""

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.params if p.name == name), None)

    @property
    def credential_ref_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if p.is_credential_ref)

    def resolve(self, raw: Mapping[str, Any] | None) -> dict[str, Any]:
        """Apply defaults and validate — produce `effective_parameters` (§4).

        Raises `ParameterError` listing every problem. The result is what gets snapshotted, so it
        must be complete: every declared parameter is present, unknown keys are rejected rather
        than carried along silently.
        """
        raw = dict(raw or {})
        errors: list[str] = []
        effective: dict[str, Any] = {}

        for spec in self.params:
            value = raw.pop(spec.name, _MISSING)
            if value is _MISSING or value is None:
                if spec.required:
                    errors.append(f"{spec.name}: required")
                    continue
                effective[spec.name] = spec.default
                continue
            problems = spec.validate(value)
            if problems:
                errors.extend(problems)
                continue
            effective[spec.name] = spec.coerce(value)

        for unknown in sorted(raw):
            errors.append(f"{unknown}: unknown parameter for {self.key} v{self.version}")

        if errors:
            raise ParameterError(self.key, self.version, errors)
        return effective


@dataclass(frozen=True, slots=True)
class CollectorDescriptor:
    """What a collector *is*, independent of any version.

    `versions` is ordered oldest → newest; the last entry is the current one. Historical entries
    are never removed: a Job snapshot must keep resolving forever.
    """

    key: str
    display_name: str
    description: str = ""
    versions: tuple[CollectorVersionSchema, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.versions:
            raise ValueError(f"collector {self.key}: at least one version is required")
        for schema in self.versions:
            if schema.key != self.key:
                raise ValueError(f"collector {self.key}: version schema declares key {schema.key}")

    @property
    def version_names(self) -> tuple[str, ...]:
        return tuple(v.version for v in self.versions)

    @property
    def current_version(self) -> str:
        return self.versions[-1].version

    def schema(self, version: str) -> CollectorVersionSchema:
        for candidate in self.versions:
            if candidate.version == version:
                return candidate
        raise UnknownCollectorVersion(
            f"collector {self.key} has no version {version!r} "
            f"(known: {', '.join(self.version_names)})"
        )
