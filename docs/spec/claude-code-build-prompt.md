# Claude Code — build prompt: data-collection back office

> Role: senior Django engineer. This is a **frozen spec** — implement it, do not redesign it.
> Work in **phases** (§16); after each phase the app must run, tests pass, and the
> import-linter contracts (§15) are green. Keep commits small. When anything is ambiguous,
> choose the simpler option and record it in `CLAUDE.md`. **Never** add anything from
> §14 (Do-not-build) without asking. **First action:** create `CLAUDE.md` capturing §12
> (invariants), §13 (dependency rules), and §14 — that file is the project's standing memory.

---

## 1. Stack
Python 3.12+, current stable Django (5.2 LTS or newer), PostgreSQL. Django Admin is the
primary UI; a small custom Dashboard with HTMX where needed. Modular monolith, one DB, one
deployment. Tooling: `ruff`, `pytest` + `pytest-django`, `import-linter`, `pre-commit`,
`docker-compose` for local dev (at least `db`; `web`/`worker`/`scheduler` optional). No
Celery, no broker, no Redis.

## 2. Project structure
```
project/
  collectors/            # collector CODE — depends on NOTHING else in the project
    schemas/             #   pure descriptors: key, versions, parameter schema per version
    runners/             #   the run() implementations, one per (key, version)
    registry.py          #   resolve (key, version) -> runner; list schemas/versions
  control/               # everything authored/stored + the admin/dashboard surface
    models.py            #   Collector projection, Config, Schedule, Job  (ALL models here)
    admin.py
    forms/
    dashboard/
    services/            #   enqueue lives here (see §6)
  execution/             # the runtime loop that CONSUMES jobs — owns behavior, no models
    queue/               #   claim + lease (§7)
    worker/              #   worker loop (§9)
    scheduler/           #   scheduler runtime (§10)
    management/commands/ #   run_worker, run_scheduler
```

**Why `collectors/` is its own package (the one deviation from a pure control/execution
split):** enqueue runs in `control` ("Run now" calls it) and needs a collector's parameter
schema to validate input and build the snapshot. That schema "comes from code", but `control`
must not import execution runtime. So collector code lives in a neutral leaf package both
sides may import — `control` reads only `collectors.schemas`, `execution` uses
`collectors.runners`. This is not an abstraction layer; it is where the collector algorithms
physically live. (If you prefer exactly two packages, runner code can instead live in
`control` and be imported by `execution` — but the leaf package is cleaner; default to it.)

## 3. Domain model (frozen)
- **Collector** — code, not data. DB row is a lightweight projection: key, display_name,
  description, enabled. Version + parameter schema come from `collectors/`, never editable in
  the admin. A management command syncs the projection from the registry on deploy.
- **Config** *(aggregate root, primary business object)* — id (stable), name, collector_key,
  parameters (raw authored), enabled, archived, tags, owner, created_by/at, updated_at,
  revision. Plus denormalized `last_status`, `last_run_at`, `last_job_id` (§11).
- **Schedule** *(child of Config)* — cron, timezone, enabled, overlap_policy {skip│queue│
  allow}, catchup_policy {fire-missed│skip-to-now}, last_fired_at (the only produced-state
  echo allowed in control — keep the rest of any cursor out of here).
- **Job** *(separate aggregate; soft-ref to Config + embedded snapshot; NOT a child of
  Config)* — see §4 (immutable snapshot) and §7 (mutable state/lease fields).

Reference semantics: Config→Collector = resolve-by-key (→ concrete version at enqueue);
Config→Schedule = containment; Job→Config = soft-ref + snapshot.

## 4. Snapshot contract
When a Job is created it snapshots everything needed to reproduce the run **from the snapshot
alone**: `collector_key`, `collector_version`, `effective_parameters` (raw params **resolved**
through the version's schema — defaults applied, validated), `schema_version`, `config_id`,
`config_revision`.

**External coordinates boundary (decide and encode now):** parameters that define *what was
collected* — target/endpoint/source identifiers — are part of `effective_parameters` and
therefore snapshotted. **Secrets/credentials are NOT snapshotted**: store a credential
*reference* (a key/name) and resolve the actual secret at execution time from env/secret
store. Consequence, stated in `CLAUDE.md`: "reproducible" means *same target + same params +
same version code*, with rotating credentials as the intentional exception.

## 5. Collectors & registry
- Each collector version is a distinct runner implementation under `collectors/runners/`,
  addressed by `(key, version)`; its parameter schema lives under `collectors/schemas/`.
- `registry.resolve(key, version) -> runner` and `registry.schema(key, version)`.
- **Historical versions stay in the codebase.** Deploys introduce new versions; they must
  **never overwrite a historical implementation in place** — the snapshot's `(key, version)`
  must always resolve to runnable code. If keeping every version forever is not acceptable,
  say so and weaken the reproducibility claim explicitly (do not silently break it).
- Ship one example collector with two versions so version resolution is exercised by tests.

## 6. Enqueue (single shared function, in `control/services/`)
One function used by **both** "Run now" and the scheduler. Steps: check Config enabled + not
archived → resolve current collector version → validate raw params against that version's
schema (`collectors.schemas`) → build `effective_parameters` → assemble the snapshot (§4) →
insert a `pending` Job. On invalid params: refuse, or insert a Job that immediately terminates
`failed` with "config invalid for collector vX" — never enqueue a runnable job with mismatched
schema. `control` imports only `collectors.schemas` here, never `collectors.runners`.

## 7. Queue: claim + lease + reclaim
The Job table **is** the queue. Claim in a **short transaction**, execute **outside** it.
- Claim = one `UPDATE ... WHERE (status='pending' AND available_at<=now) OR (status='running'
  AND claimed_until<now) ... FOR UPDATE SKIP LOCKED LIMIT 1`, setting status, claimed_by,
  claimed_until, and **incrementing `attempt_no`**. The expired-lease branch **is** the
  dead-worker reclaim — no separate reaper.
- Long runs renew the lease with a single UPDATE, only if a run can exceed the lease; prefer a
  generous lease over frequent renewal. This is not a heartbeat subsystem.
- **Reclaim ≠ retry (encode the distinction):** a reclaim is *the same Job continuing under a
  new executor* (attempt_no reflects executor handoffs). A run that reaches terminal `failed`
  is **not** auto-re-enqueued (retry is postponed, §14). History must let you tell "the worker
  died N times" from "the collector failed once."
- **Keep the claim query in ONE function.** The stateless→incremental fork (§13/Option B) adds
  a predicate here; isolating it keeps that a localized change, not a hot-path rewrite.

Job mutable/lease fields: status, claimed_by, claimed_until, attempt_no, cancel_requested,
priority, available_at.

## 8. Runner interface & cancellation
Define the runner contract so runners are **not opaque**: a runner receives a context object
and must **cooperatively check for cancellation** at safe points (e.g. `ctx.check_cancelled()`
between steps / batches). Cancelling a `pending` Job = don't claim it / mark `cancelled`.
Cancelling a `running` Job = worker sets the signal, runner polls it and stops. Runner returns
a structured result (status, result payload, structured_error {type, message, trace}, metrics
{rows, bytes, calls, ...}). This shapes the interface — get it right before writing runners.

## 9. Worker (`run_worker` management command)
A plain loop: claim → resolve runner from the snapshot's `(key, version)` → execute on the
snapshot only → on finish write terminal status + result/error/metrics and update the Config
`last_*` cache columns (§11). Worker holds almost no logic; logic lives in runners. Multiple
worker processes just compete for rows.

## 10. Scheduler (`run_scheduler` management command, cron-driven)
Find due schedules → apply overlap_policy (when the previous Job for that Config is still
active) and catchup_policy (after host downtime: fire missed runs vs skip to now) → call the
shared enqueue (§6) → advance `last_fired_at`. **Idempotency:** Job creation and `last_fired_at`
advance happen in one transaction, guarded by a **unique constraint on `(schedule_id,
fire_time)`**, so a duplicate enqueue is impossible even if cron overlaps or the scheduler
crashes/restarts mid-run. The scheduler produces work only; it never executes collectors.

## 11. Dashboard cache columns
Config carries `last_status`, `last_run_at`, `last_job_id`, written by the worker on Job
completion, read by the dashboard/admin list. These are denormalized cache columns — **not**
CQRS, not a read model, no second database. That is the full extent of "projection" allowed.

## 12. Invariants (freeze — put in `CLAUDE.md`)
Snapshot completeness (Job runs from snapshot alone; execution never reads mutable Config
after enqueue) · enqueue preconditions (enabled AND params valid vs resolved schema) ·
Collector deprecate-not-delete · Config editable anytime, running Jobs unaffected, soft-delete
only · schedules survive collector upgrades but a scheduled run with now-invalid params fails
fast · terminal states are terminal (retry = new Job, never mutate a terminal one) · lease
reclaim (`claimed_until < now` ⇒ claimable) · `(key, version)` always resolves to runnable
code · secrets never snapshotted.

## 13. Dependency rules (enforce with import-linter)
`control ↛ execution` (control never imports worker/queue/scheduler runtime) ·
`control ↛ collectors.runners` (control may import `collectors.schemas` only) ·
`collectors ↛ control` and `collectors ↛ execution` (collectors is a pure leaf) ·
allowed: `execution → control` (models), `execution → collectors`, `control → collectors.schemas`.

## 14. Do-not-build (without asking)
distributed locks · retry subsystem · event bus · read databases · CQRS · repository layer ·
service layer beyond the single enqueue function · clean-architecture layers · message broker ·
microservices · heartbeat subsystem. Each waits for a concrete forcing factor.

## 15. Enforcement / definition of done per phase
`manage.py check` clean · migrations present and applied · `ruff` clean · import-linter
contracts (§13) green · phase tests pass · `docker-compose up` brings up the DB and the app
runs.

## 16. Phases
- **P0 — Scaffold.** Django project + the four packages, Postgres settings, docker-compose,
  ruff, pytest, import-linter contracts (§13) wired into pre-commit, `CLAUDE.md`. Prove
  `check` + linter green.
- **P1 — Control models + admin.** Collector projection, Config, Schedule (policies +
  last_fired_at), Job (snapshot + state/lease fields), migrations, admin (inlines, filters,
  search, autocomplete, bulk actions), dashboard skeleton, a `seed` command, a `sync_collectors`
  command (registry → projection).
- **P2 — Collectors + enqueue.** Runner interface + RunContext/RunResult with cancellation
  hook (§8), registry keyed on `(key, version)` (§5), one example collector with two versions
  and schemas, the shared enqueue (§6), and the "Run now" admin/dashboard action calling it.
- **P3 — Execution.** Claim + lease + reclaim in one function (§7), `run_worker` loop (§9),
  runner resolution from snapshot, terminal handling (no auto-retry), cooperative cancel,
  `last_*` cache updates. Tests: claim concurrency, expired-lease reclaim increments attempt_no,
  cancel of pending vs running.
- **P4 — Scheduler.** `run_scheduler` (§10): due detection, overlap/catch-up policies,
  idempotent enqueue via `(schedule_id, fire_time)`, advance last_fired_at. Tests: no double
  enqueue across overlap/crash/restart; catch-up vs skip-to-now.

## 17. Open fork — decide before P2/P3 (default = A)
- **Option A (default): stateless collectors.** No cross-run state; the architecture above is
  complete. Do **not** build the per-stream predicate or CollectionState.
- **Option B: incremental collectors.** Add: `CollectionState` (execution-owned, per Config
  stream, advanced only on successful Jobs) · the invariant **≤1 active Job per stream** as a
  **partial unique index on active jobs** (correctness, not a "lock") · the claim predicate for
  it (§7) · `processed_window` on Job · and amend the snapshot invariant to "execution reads
  the snapshot AND reads/advances the cursor". This changes the claim hot path, so it is not a
  later add-on — confirm A vs B now.

## 18. Interaction protocol
Restate the plan and **confirm Option A vs B** before P2. Build phase by phase to the §15 bar.
Prefer the simpler path; record decisions in `CLAUDE.md`. Never introduce a §14 item without
asking.
