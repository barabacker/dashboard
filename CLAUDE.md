# CLAUDE.md — standing memory for this repository

Data-collection back office. Django modular monolith, one DB, one deployment.
This file is authoritative: the invariants, dependency rules and do-not-build list below are
**frozen**. Do not redesign them; if reality forces a change, say so explicitly and ask.

## Required reading

Before non-trivial work, read:

- `docs/agent/engineering_principles.md`
- `docs/agent/plan_act_workflow.md`
- `docs/agent/review_protocol.md`
- `docs/agent/task_continuity.md`
- `docs/agent/new_service_architecture.md` (greenfield work)
- `docs/architecture/adr/0001-architecture-baseline.md`

## Package map

```
project/      Django settings/urls/wsgi — framework glue only
collectors/   collector CODE, pure leaf, depends on NOTHING else in the project
  schemas/      pure descriptors: key, versions, parameter schema per version
  runners/      run() implementations, one module per (key, version)
  registry.py   resolve (key, version) -> runner   [imports runners — control must not touch it]
control/      everything authored/stored + admin/dashboard surface. ALL models live here.
  models.py     Collector projection, Config, Schedule, Job
  services/     the single shared enqueue function
  dashboard/    small HTMX dashboard
execution/    runtime that CONSUMES jobs. Owns behavior, owns NO models.
  queue/        claim + lease + reclaim (one function)
  worker/       worker loop
  scheduler/    scheduler runtime
  management/commands/  run_worker, run_scheduler
```

## Invariants (frozen — §12 of the spec)

- **Snapshot completeness.** A Job runs from its snapshot alone. Execution never reads mutable
  Config state after enqueue.
- **Enqueue preconditions.** Config enabled AND not archived AND raw params valid against the
  resolved collector version's schema.
- **Collector deprecate-not-delete.** Collector rows are a projection of code; they are disabled,
  never deleted.
- **Config editable anytime**; running Jobs are unaffected; deletion is soft (`archived`).
- **Schedules survive collector upgrades**, but a scheduled run whose params became invalid for
  the new version fails fast (a `failed` Job with `config_invalid`, never a runnable job).
- **Terminal states are terminal.** `succeeded` / `failed` / `cancelled` are never mutated.
  A retry is a *new Job*, never a mutation of a terminal one.
- **Lease reclaim.** `status='running' AND claimed_until < now` ⇒ claimable again.
- **`(key, version)` always resolves to runnable code.** Historical runner versions stay in the
  codebase and are never overwritten in place.
- **Secrets are never snapshotted.** Snapshots carry a credential *reference*; the actual secret
  is resolved at execution time from env/secret store.

### What "reproducible" means here

Same target + same params + same version code. Rotating credentials are the intentional
exception: the credential *reference* is snapshotted, the credential *value* is not, so a replay
uses whatever the secret store holds today.

### Reclaim ≠ retry

`attempt_no` counts **executor handoffs**, not collector retries. A reclaim is the same Job
continuing under a new executor after its lease expired (i.e. the previous worker died). A run
that reaches terminal `failed` is *not* auto-re-enqueued. History must let you tell
"the worker died three times" from "the collector failed once".

## Dependency rules (frozen — §13, enforced by import-linter in `pyproject.toml`)

Forbidden:
- `control ↛ execution` — control never imports worker/queue/scheduler runtime.
- `control ↛ collectors.runners` and `control ↛ collectors.registry` — control may import
  `collectors.schemas` only. (`registry` is forbidden too because it imports runners; letting
  control import it would smuggle runner code in transitively.)
- `collectors ↛ control`, `collectors ↛ execution`, `collectors ↛ django` — collectors is a pure
  leaf with no framework dependency.

Allowed:
- `execution → control` (models), `execution → collectors` (registry + runners),
  `control → collectors.schemas`.

Run the contracts with:

```bash
lint-imports
```

## Do-not-build without asking (frozen — §14)

distributed locks · retry subsystem · event bus · read databases · CQRS · repository layer ·
service layer beyond the single enqueue function · clean-architecture layers · message broker ·
microservices · heartbeat subsystem · Celery/Redis/any broker.

Each waits for a concrete forcing factor. The `last_status` / `last_run_at` / `last_job_id`
columns on Config are **denormalized cache columns**, not CQRS and not a read model — that is the
full extent of "projection" allowed.

## Decisions on record

| # | Decision | Why |
|---|----------|-----|
| D1 | **Option A — stateless collectors** (§17). | Confirmed with the user before P2. No `CollectionState`, no `processed_window`, no per-stream partial unique index, no extra claim predicate. Switching to B later is a hot-path change, not an add-on. |
| D2 | Python 3.13 + Django 5.2 LTS, managed with `uv`. | 3.12+ required by the spec; 3.13 is supported by Django 5.2. |
| D3 | Layout: `manage.py` + `project/` (settings) + `collectors/`, `control/`, `execution/` at repo root. | The spec's `project/` box is the repo itself; a nested package of the same name would only add a path segment. |
| D4 | Parameter schemas are plain Python descriptors (`ParamSpec` list), not JSON Schema. | Simpler option per the prompt's ambiguity rule; enough to type-check, default and validate, with no extra dependency. |
| D5 | Cron parsing via `croniter`. | Schedules need real cron + timezone semantics and catch-up iteration; hand-rolling that is the complex option. |
| D6 | The queue claim is a single raw-SQL `UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)` in `execution/queue/claim.py::claim_job`. | §7 requires exactly one place for the claim predicate so the A→B fork stays localized. |
| D7 | Cancellation signal is read from the DB (`Job.cancel_requested`) by `RunContext.check_cancelled()`, polled cooperatively by runners. | No signal bus, no heartbeat subsystem. |
| D8 | `sync_collectors` upserts the Collector projection and **disables** rows whose key vanished from the registry. | Deprecate-not-delete. |
| D9 | `available_at` is the scheduling knob for a pending Job; there is no separate retry/backoff machinery. | Retry is postponed (§14). |

## Core working rules

- Prefer minimal, explicit, maintainable changes. Do not broaden scope silently.
- Separate domain logic from transport, persistence, side effects and framework glue.
- Make state, time, ordering and idempotency explicit.
- Add or update tests for changed behavior; run relevant validation.
- Stop and ask if the implementation contradicts the spec or requires a larger refactor.

## Definition of done for any change (§15)

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check . && ruff format --check .
lint-imports
pytest
```

`docker compose up db` must bring up Postgres and the app must run against it.
