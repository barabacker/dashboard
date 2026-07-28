"""`example_api` v2.0 — the current version.

Differences from v1.0, and why they are a new version rather than an edit:

* `dataset` is **required**. A Config authored against v1.0 no longer resolves, which is exactly
  the "schedules survive collector upgrades, but a run with now-invalid params fails fast" case.
* `since` narrows the pull.
* `page_delay_seconds` exists so cancellation is observable in a running system — a run you can
  actually catch in the act.

v1.0 keeps running unchanged for every Job that snapshotted it.
"""

from __future__ import annotations

import time

from collectors.runners.base import CredentialMissing, RunContext, Runner, RunResult

KEY = "example_api"
VERSION = "2.0"


class ExampleApiV2(Runner):
    key = KEY
    version = VERSION

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
                "example_api v2.0 job=%s dataset=%s page=%s/%s url=%s%s since=%s",
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
