# ADR 0001 — Architecture baseline

Status: accepted · Date: 2026-07-28

## Context

A back office for **data collection**: humans author *what to collect* (Config), optionally *when*
(Schedule), and the system produces *what actually ran* (Job). Collector algorithms are code, not
data. The operational surface is Django Admin plus a small dashboard.

The spec (`claude-code-build-prompt.md`) is frozen. This ADR records the style chosen and why it
is enough, not a re-derivation of the spec.

## Decision

A **modular monolith**: one Django project, one PostgreSQL database, one deployment, with three
internal packages whose boundaries are enforced mechanically by `import-linter`.

| Package | Responsibility | Owns |
|---|---|---|
| `collectors` | Collector algorithms + their parameter schemas. Pure leaf: imports nothing from the project and not even Django. | no state |
| `control` | Authoring and storage surface: models, admin, dashboard, the single `enqueue` use case. | **all** models |
| `execution` | The runtime that consumes jobs: claim/lease/reclaim, worker loop, scheduler. | **no** models, all runtime behavior |

`collectors` exists as a third package for one concrete reason: `enqueue` lives in `control`
("Run now" calls it) and needs a collector's parameter schema to validate input and build the
snapshot — but `control` must not import the execution runtime. A neutral leaf package that both
sides may import is the cheapest way to satisfy both. It is not an abstraction layer; it is where
the collector algorithms physically live.

## Why this style is enough

- One team, one deployment, one data owner. None of the usual forcing factors for splitting
  services (independent scaling, separate ownership, separate failure boundary) are present.
- The **Job table is the queue**. Postgres `FOR UPDATE SKIP LOCKED` gives competing consumers
  with no broker, and an expired-lease predicate gives dead-worker recovery with no reaper
  process. Adding Celery/Redis would add two operational components to solve a problem one SQL
  statement already solves.
- Cross-package coupling that would erode the design is caught by CI, not by review discipline.

## Data ownership and source of truth

- **Config / Schedule** — authored by humans in `control`; source of truth for *intent*.
- **Job** — produced; source of truth for *what happened*. It is a separate aggregate holding an
  immutable snapshot plus mutable execution state, deliberately **not** a child of Config, so
  editing or archiving a Config never rewrites history.
- **Collector** — source of truth is the **code** in `collectors/`. The DB row is a projection
  synced by `manage.py sync_collectors`; version and parameter schema are never editable in the
  admin.
- **Config.last_status / last_run_at / last_job_id** — denormalized cache columns written by the
  worker so the dashboard list is one query. Not CQRS, not a read model.

## States and transitions

```
Job:  pending ──claim──▶ running ──▶ succeeded
        │                   │      ╲──▶ failed
        │                   └─lease expired─▶ (claimable again, attempt_no += 1)
        └──cancel──▶ cancelled            running + cancel_requested ──▶ cancelled
```

Terminal states are terminal. A "retry" is a new Job.

## Invariants

Listed and frozen in `CLAUDE.md` (§12 of the spec). The load-bearing ones:
snapshot completeness · enqueue preconditions · `(key, version)` always resolves ·
secrets never snapshotted · lease reclaim · terminal states immutable.

## Idempotency

The scheduler is the only component that can double-produce. Job creation and the `last_fired_at`
advance happen in **one transaction**, guarded by a unique constraint on
`(schedule_id, fire_time)`. A crashed/restarted/overlapping scheduler therefore cannot create a
duplicate run — the constraint, not a lock, is the correctness mechanism.

## Testing strategy

- Pure unit tests for parameter resolution/validation (`collectors.schemas`) — no DB, no Django.
- DB-backed tests for enqueue preconditions and snapshot contents.
- Concurrency tests for the claim: two claimers get different jobs; an expired lease is reclaimed
  and increments `attempt_no`; a terminal job is never re-claimed.
- Scheduler tests for the idempotency guarantee and the overlap/catch-up policy matrix.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Celery + Redis | Two more operational components; the durability and visibility we need is exactly what a table gives us for free. Job history in Postgres is queryable; broker state is not. |
| Clean-architecture layering (entities/use cases/adapters) | Would triple the file count for a domain with three aggregates. The boundary that actually matters (control vs execution vs collectors) is already enforced. |
| Repository layer over the ORM | Adds indirection without a second persistence target. Django querysets are the repository. |
| Jobs as a child of Config | Editing or archiving a Config would entangle history; a soft reference plus a snapshot keeps the two lifecycles independent. |
| Storing collector versions/schemas in the DB | Code would stop being the source of truth and a snapshot could reference a schema that no runnable code matches. |
| Option B — incremental collectors with `CollectionState` | Deferred by explicit decision (D1). It changes the claim hot path, so it is a re-open of §7, not an add-on. |

## Known risks

- **Version accretion.** Historical runner versions must stay in the tree forever to keep
  `(key, version)` resolvable. Mitigation: versions are small modules; if this ever becomes
  untenable, the reproducibility claim must be weakened *explicitly*, never silently.
- **Long polls.** The worker polls; a busy queue with a long poll interval adds latency. Knob:
  `WORKER_POLL_SECONDS`.
- **Lease sizing.** A lease shorter than a legitimate run causes a spurious reclaim (duplicate
  work, not data loss). Mitigation: a generous default lease plus explicit renewal for runners
  that can exceed it.
- **Cooperative cancellation only.** A runner that never calls `ctx.check_cancelled()` cannot be
  stopped short of killing the process. This is a documented contract, enforced by review.
