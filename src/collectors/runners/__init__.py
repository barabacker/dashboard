"""Runner implementations, one module per `(key, version)`.

`control` must never import this package — it would drag collector execution code into the web
process. The import-linter contract in `pyproject.toml` enforces that.
"""

from collectors.runners.base import (
    Cancelled,
    CredentialMissing,
    RunContext,
    Runner,
    RunResult,
)

__all__ = ["Cancelled", "CredentialMissing", "RunContext", "RunResult", "Runner"]
