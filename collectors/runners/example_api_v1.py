"""`example_api` v1.0 — frozen.

This file is history. It is what a Job snapshotted with `("example_api", "1.0")` still runs today,
so it must not be edited to add features or change behavior; a new version gets a new module.

It fabricates rows instead of doing network I/O: the point of the example is to exercise version
resolution, credential references and cooperative cancellation deterministically, not to prove
that HTTP works.
"""

from __future__ import annotations

from collectors.runners.base import CredentialMissing, RunContext, Runner, RunResult

KEY = "example_api"
VERSION = "1.0"


class ExampleApiV1(Runner):
    key = KEY
    version = VERSION

    def run(self, ctx: RunContext) -> RunResult:
        params = ctx.parameters
        base_url: str = params["base_url"]
        path: str = params["path"]
        page_size: int = params["page_size"]
        pages: int = params["pages"]
        credential_ref: str = params.get("credential_ref") or ""

        # Resolved now, from the environment — never from the snapshot.
        token = ""
        if credential_ref:
            try:
                token = ctx.resolve_credential(credential_ref)
            except CredentialMissing as exc:
                return RunResult.failure(
                    type="credential_missing",
                    message=str(exc),
                    metrics={"rows": 0, "calls": 0},
                )

        rows = 0
        calls = 0
        for page in range(1, pages + 1):
            # Safe point: between pages nothing is half-written.
            ctx.check_cancelled()
            ctx.extend_lease()

            calls += 1
            rows += page_size
            ctx.logger.info(
                "example_api v1.0 job=%s page=%s/%s url=%s%s",
                ctx.job_id,
                page,
                pages,
                base_url,
                path,
            )

        return RunResult.success(
            result={
                "endpoint": f"{base_url}{path}",
                "pages": pages,
                "authenticated": bool(token),
            },
            metrics={"rows": rows, "calls": calls, "bytes": rows * 128},
        )
