# Data-collection back office

Humans author **what** to collect (`Config`) and optionally **when** (`Schedule`). The system
records **what actually ran** (`Job`). Collector algorithms are code, not data.

Django modular monolith, one PostgreSQL database, one deployment. No broker, no Celery, no Redis —
the Job table *is* the queue.

* Architecture and the reasoning behind it: [`docs/architecture/adr/0001-architecture-baseline.md`](docs/architecture/adr/0001-architecture-baseline.md)
* Frozen invariants, dependency rules and decisions: [`CLAUDE.md`](CLAUDE.md)
* The original specification: [`docs/spec/claude-code-build-prompt.md`](docs/spec/claude-code-build-prompt.md)

## Layout

```
manage.py            pyproject.toml       uv.lock
src/                 the four packages
tests/               unit/ is pure; the rest is DB-backed
docker/              Dockerfile + compose.yaml
docs/                agent harness · architecture ADRs · spec · Architect bundle
```

| Package | Owns | Rule |
|---|---|---|
| `src/collectors/` | collector algorithms and their parameter schemas | pure leaf — imports nothing from the project, not even Django |
| `src/control/` | **all** models, admin, dashboard, the single `enqueue` function | never imports the execution runtime or runner code |
| `src/execution/` | claim/lease/reclaim, worker loop, scheduler | **no** models; imports `control` and `collectors` freely |
| `src/project/` | settings, urls, wsgi | framework glue |

Enforced by `import-linter`, not by review discipline:

```bash
lint-imports
```

## Running it

### Docker

The compose file lives in `docker/`. Copy `.env.example` to `.env` first — it sets `COMPOSE_FILE`,
which is what lets you run plain `docker compose` from the repository root:

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

Without a `.env`, point at it explicitly: `docker compose -f docker/compose.yaml up --build`.

That brings up Postgres, the web app on http://localhost:8000, a worker and a scheduler. Then, in
another shell:

```bash
docker compose exec web python manage.py migrate
```

```bash
docker compose exec web python manage.py seed
```

`seed` creates an `admin` / `admin` superuser, syncs the collector projection and adds three
sample Configs — including one deliberately left invalid for the current collector version, so the
fail-fast path is visible from the first minute.

### Locally

Requires [uv](https://docs.astral.sh/uv/). Postgres can still come from compose.

```bash
uv sync
```

`uv sync` installs the project editable, which is what puts `src/` on the import path.

```bash
docker compose up -d db
```

```bash
uv run manage.py migrate && uv run manage.py seed && uv run manage.py runserver
```

Then a worker, and a scheduler tick:

```bash
uv run manage.py run_worker
```

```bash
uv run manage.py run_scheduler
```

`run_scheduler` does one pass and exits — the intended deployment is system cron every minute.
`--loop` exists for compose and for hosts without cron.

## The surfaces

* **`/admin/`** — the primary UI. Configs with schedules inline, Job history, and a Collector page
  that shows the parameter schema straight from the code.
* **`/dashboard/`** — a small HTMX page: what each Config last did, what is running now, "Run now"
  and "Cancel". Actions are plain form POSTs; HTMX only auto-refreshes the job panel.

## Commands

| Command | What it does |
|---|---|
| `manage.py sync_collectors` | Mirror the collector registry into the projection table. Run on deploy. `--dry-run` available. |
| `manage.py seed` | Dev data. Idempotent. |
| `manage.py run_worker` | Claim and execute Jobs. `--once`, `--max-jobs`, `--lease-seconds`, `--poll-seconds`. Run as many as you like — they compete for rows. |
| `manage.py run_scheduler` | One scheduling pass. `--loop`, `--interval`, `--max-catchup`. |

## How it hangs together

**Enqueue is one function**, shared by "Run now" and the scheduler. It checks the Config is
enabled and not archived, resolves the collector's *current* version, validates the authored
parameters against that version's schema, and writes a Job carrying a complete snapshot:
`collector_key`, `collector_version`, `effective_parameters`, `schema_version`, `config_id`,
`config_revision`. A run reproduces from that snapshot alone — execution never reads the Config
again, so editing or archiving one mid-flight changes nothing about a run in progress.

**Secrets are never snapshotted.** Parameters carry a credential *reference* (an env var name);
the value resolves at execution time. "Reproducible" therefore means *same target, same params,
same version code* — rotating credentials are the documented exception.

**The queue is one SQL statement.** `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED
LIMIT 1)`, with an expired-lease disjunct that doubles as the dead-worker reclaim. No reaper
process exists because none is needed.

**Reclaim is not retry.** `attempt_no` counts executor handoffs. A Job that reaches terminal
`failed` is never re-enqueued automatically — a retry is a new Job. History can tell "the worker
died three times" from "the collector failed once".

**Scheduling is idempotent by constraint, not by lock.** Job creation and the `last_fired_at`
advance happen in one transaction, guarded by a unique constraint on `(schedule_id, fire_time)`.
Overlapping cron, two schedulers, a crash mid-run — none of them can double-enqueue.

**Collector versions are forever.** Each `(key, version)` is its own runner module and is never
edited in place; a year-old snapshot still resolves to the code it ran.

## Checks

```bash
uv run manage.py check && uv run manage.py makemigrations --check --dry-run && uv run ruff check . && uv run ruff format --check . && uv run lint-imports && uv run pytest
```
