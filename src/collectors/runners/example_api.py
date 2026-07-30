"""`example_api` — the reference collector.

Fabricates rows instead of doing network I/O: the point is to exercise credential references,
parameter validation and cooperative cancellation deterministically, not to prove that HTTP works.
"""

from __future__ import annotations

import time

from collectors.runners.base import CredentialMissing, RunContext, Runner, RunResult

KEY = "example_api"


class ExampleApi(Runner):
    key = KEY

    def run(self, ctx: RunContext) -> RunResult:
        params = ctx.parameters
        base_url: str = params["base_url"]
        path: str = params["path"]
        page_size: int = params["page_size"]
        pages: int = params["pages"]
        dataset: str = params["dataset"]
        since: str = params.get("since") or ""
        delay: float = float(params.get("page_delay_seconds") or 0.0)
        credential_ref: str = params.get("credential_ref") or ""

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
            ctx.check_cancelled()
            ctx.extend_lease()

            if delay:
                time.sleep(delay)

            calls += 1
            rows += page_size
            ctx.logger.info(
                "example_api job=%s dataset=%s page=%s/%s url=%s%s since=%s",
                ctx.job_id,
                dataset,
                page,
                pages,
                base_url,
                path,
                since or "-",
            )

        return RunResult.success(
            result={
                "endpoint": f"{base_url}{path}",
                "dataset": dataset,
                "since": since,
                "pages": pages,
                "authenticated": bool(token),
            },
            metrics={"rows": rows, "calls": calls, "bytes": rows * 160},
        )
