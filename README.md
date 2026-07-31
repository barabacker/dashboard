# Data-collection back office

*Русская версия: [`README.ru.md`](README.ru.md)*

Humans author **what** to collect (`Config`) and optionally **when** (`Schedule`). The system
records **what actually ran** (`Job`). Collector algorithms are code, not data.

Django modular monolith, one PostgreSQL database, one deployment. No broker, no Celery, no Redis —
the Job table *is* the queue.

* Design rationale for `control` (models, forms, admin): [`docs/superpowers/specs/2026-07-31-control-models-redesign-design.md`](docs/superpowers/specs/2026-07-31-control-models-redesign-design.md)
* The original specification: [`docs/spec/claude-code-build-prompt.md`](docs/spec/claude-code-build-prompt.md)

## Layout

```
Makefile             pyproject.toml       uv.lock
src/                 manage.py + the four packages
tests/               unit/ is pure; the rest is DB-backed
docker/              Dockerfile + compose.yaml
docs/                agent harness · architecture ADRs · spec · Architect bundle
```

| Package | Owns | Rule |
|---|---|---|
| `src/collectors/` | collector algorithms, their parameter schemas, and the vendored scraping engine | pure leaf — imports nothing from the project, not even Django |
| `src/control/` | **all** models, admin, dashboard, the single `enqueue` function | never imports the execution runtime or runner code |
| `src/execution/` | claim/lease/reclaim, worker loop, scheduler | **no** models; imports `control` and `collectors` freely |
| `src/project/` | settings, urls, wsgi | framework glue |

Enforced by `import-linter`, not by review discipline:

```bash
make contracts
```

## Running it

Everything routine has a make target. `make` on its own prints the list.

### Docker

```bash
make env && make up
```

`make env` writes `.env` from the example — it sets `COMPOSE_FILE`, which is what lets plain
`docker compose` find `docker/compose.yaml` from the repository root. `make up` starts Postgres,
the web app on http://localhost:8000, a worker and a scheduler. Then:

```bash
make docker-migrate && make docker-seed
```

`seed` creates an `admin` / `admin` superuser, syncs the collector projection and adds three
sample Configs — including one deliberately left invalid for the current collector version, so the
fail-fast path is visible from the first minute.

### Locally

Requires [uv](https://docs.astral.sh/uv/). Postgres can still come from compose.

```bash
make install && make env && make db
```

`make install` runs `uv sync`, which installs the project editable — that is what puts `src/` on
the import path.

```bash
make migrate && make seed && make run
```

Then a worker in one shell and the scheduler in another:

```bash
make worker
```

```bash
make scheduler
```

`make tick` is a single scheduling pass — the intended deployment is system cron every minute.
`make scheduler` (`--loop`) exists for compose and for hosts without cron.

## The surfaces

The UI is in **Russian**; code, logs, stored values and documentation stay English.

* **`/admin/`** — the primary UI. Configs with schedules inline, Job history, and a Collector page
  that shows the parameter schema straight from the code.
* **`/admin/control/source/`** — «Источники»: the trading platforms to crawl. The same Configs,
  asked for as sites — domain, listing path, TLS quirks — instead of as a JSON object.
* **`/dashboard/`** — a small HTMX page: what each Config last did, what is running now, "Run now"
  and "Cancel". Actions are plain form POSTs; HTMX only auto-refreshes the job panel.

Times are rendered in `DJANGO_TIME_ZONE` (default `UTC`; set `Europe/Moscow` in `.env` to read
local times). Storage is always UTC.

## Crawling trading platforms

Four collectors ship for bankruptcy-auction platforms, one per parser family — `tender_fogsoft`,
`tender_kendo`, `tender_btorg`, `tender_ruson`. The engine behind them is vendored under
`src/collectors/engine/` and stays framework-free.

A **collector is the engine; a site is data.** Its domain, listing path and TLS quirks are
ordinary parameters, so adding a source is filling in a form — there is no site list in the
repository. `make sources` carries over the thirty-three sites the parser project already
crawled; after that they live in the admin.

A run crawls for real, honours cancellation between requests and extends its lease as it goes. It
reports what it found — `rows`, `calls`, `listing_pages`, and a few lot ids in `Job.result` — and
stores the lots via `Lot` / `DbLotSink`; `Job.result` carries `"stored": true` (or `false` for the
rare run with no sink attached) so a green Job never overstates what happened.

## Commands

`make help` lists every target. The ones specific to this system:

| Target | Underlying command | What it does |
|---|---|---|
| `make collectors` | `sync_collectors` | Mirror the collector registry into the projection table. Run on deploy. `--dry-run` available. |
| `make seed` | `seed` | Dev data. Idempotent. |
| `make sources` | `seed_sources` | Create the 33 trading platforms carried over from the parser project. Initial data, not a source of truth — after this they are edited in the admin. Idempotent, `--dry-run` available. |
| `make worker` | `run_worker` | Claim and execute Jobs. `--once`, `--max-jobs`, `--lease-seconds`, `--poll-seconds`. Run as many as you like — they compete for rows. |
| `make tick` / `make scheduler` | `run_scheduler` | One scheduling pass, or `--loop`. Also `--interval`, `--max-catchup`. |

To pass flags, call the management command directly — `manage.py` lives in `src/`:

```bash
uv run python src/manage.py run_worker --once
```

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
make verify
```

Django system check, migration drift, ruff, the import contracts and the test suite — the same
gate CI would run.
