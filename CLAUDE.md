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

## Repository map

```
Makefile                every routine command; `make help` lists them
pyproject.toml          deps, ruff, pytest, import-linter contracts — one config file
src/
  manage.py             Django entry point, next to the packages it drives
  project/              Django settings/urls/wsgi — framework glue only
  collectors/           collector CODE, pure leaf, depends on NOTHING else in the project
    schemas/              pure descriptors: key, parameter schema — one per collector, no version axis
      tender.py             the four tender-site collectors (one per parser family)
    runners/              run() implementations, one module per collector key
    engine/               the vendored scraping engine — core/ http/ sources/, no framework
    certs/                extra intermediate certificates, named by `extra_ca_cert`
    registry.py           resolve key -> runner  [imports runners — control must not]
  control/              everything authored/stored + admin/dashboard surface. ALL models here.
    models.py             Collector projection, Config, Platform (proxy), Schedule, Job
    services/             the single shared enqueue function
    forms/                authoring forms: Config (JSON) and Platform (a field per site attribute)
    dashboard/            small HTMX dashboard
  execution/            runtime that CONSUMES jobs. Owns behavior, owns NO models.
    queue/                claim + lease + reclaim (one function)
    worker/               worker loop
    scheduler/            scheduler runtime
    management/commands/  run_worker, run_scheduler
tests/                  unit/ is pure (no DB); everything else is DB-backed
docker/                 Dockerfile + compose.yaml
docs/
  agent/                the Architect harness
  architecture/adr/     architecture decisions
  spec/                 the frozen build prompt this repo implements
  architect-bundle/     the Architect Project bundle, kept for reference
```

`src/` is a real src layout: `uv sync` installs the project editable, which is what puts the four
packages on the import path for `manage.py`, `pytest` and `lint-imports` alike. After changing
`[tool.hatch.build.targets.wheel] packages`, re-run `uv sync`.

## Invariants (frozen — §12 of the spec)

- **Snapshot completeness.** A Job runs from its snapshot alone. Execution never reads mutable
  Config state after enqueue.
- **Enqueue preconditions.** Config enabled AND not archived AND raw params valid against the
  collector's current schema.
- **Collector deprecate-not-delete.** Collector rows are a projection of code; they are disabled,
  never deleted.
- **Config editable anytime**; running Jobs are unaffected; deletion is soft (`archived`).
- **A Config whose raw params drift out of step with the collector's schema fails fast** — a
  `failed` Job with `config_invalid`, never a runnable job. (Retired the version axis this used to
  be framed around — see **D21**.)
- **Terminal states are terminal.** `succeeded` / `failed` / `cancelled` are never mutated.
  A retry is a *new Job*, never a mutation of a terminal one.
- **Lease reclaim.** `status='running' AND claimed_until < now` ⇒ claimable again.
- **Every collector key always resolves to runnable code.** One schema, one runner, per key —
  edited in place as requirements change (see **D21**; this replaces the former `(key, version)`
  invariant).
- **Secrets are never snapshotted.** Snapshots carry a credential *reference*; the actual secret
  is resolved at execution time from env/secret store.

### What "reproducible" means here

Same target + same params + the collector's code **as it exists today** — not as it existed when
the Job was created. See **D21**: this is a deliberate narrowing from the original "same version
code forever" guarantee. Rotating credentials are a separate, still-standing exception: the
credential *reference* is snapshotted, the credential *value* is not, so a replay uses whatever
the secret store holds today regardless.

### Reclaim ≠ retry

`attempt_no` counts **executor handoffs**, not collector retries. A reclaim is the same Job
continuing under a new executor after its lease expired (i.e. the previous worker died). A run
that reaches terminal `failed` is *not* auto-re-enqueued. History must let you tell
"the worker died three times" from "the collector failed once".

## Dependency rules (frozen — §13, enforced by import-linter in `pyproject.toml`)

Forbidden:
- `control ↛ execution` — control never imports worker/queue/scheduler runtime.
- `control ↛ collectors.runners`, `control ↛ collectors.registry`, `control ↛ collectors.engine` —
  control may import `collectors.schemas` only. (`registry` is forbidden too because it imports
  runners; letting control import it would smuggle runner code in transitively.)
- `collectors ↛ control`, `collectors ↛ execution`, `collectors ↛ django` — collectors is a pure
  leaf with no framework dependency.
- `collectors.schemas ↛ collectors.engine` (and not `curl_cffi` / `parsel` / `pydantic`) — the
  schemas are what `control` imports, so anything they import lands in the web process. This is
  what keeps "control gets its answers from schemas" true at run time and not only on paper.

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
| D3 | Layout: everything runnable under `src/` (including `manage.py`), docker under `docker/`, all prose under `docs/`, a `Makefile` as the command surface. | The spec's `project/` box is the repo itself. A src layout keeps the root readable and makes "is this importable?" a property of the install rather than of the working directory. `manage.py` sits in `src/` by the user's explicit call — the usual Django convention puts it at the root, so **invoke it as `python src/manage.py`**, or just use `make`. |
| D4 | Parameter schemas are plain Python descriptors (`ParamSpec` list), not JSON Schema. | Simpler option per the prompt's ambiguity rule; enough to type-check, default and validate, with no extra dependency. |
| D5 | Cron parsing via `croniter`. | Schedules need real cron + timezone semantics and catch-up iteration; hand-rolling that is the complex option. |
| D6 | The queue claim is a single raw-SQL `UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)` in `execution/queue/claim.py::claim_job`. | §7 requires exactly one place for the claim predicate so the A→B fork stays localized. |
| D7 | Cancellation signal is read from the DB (`Job.cancel_requested`) by `RunContext.check_cancelled()`, polled cooperatively by runners. | No signal bus, no heartbeat subsystem. |
| D8 | `sync_collectors` upserts the Collector projection and **disables** rows whose key vanished from the registry. | Deprecate-not-delete. |
| D9 | `available_at` is the scheduling knob for a pending Job; there is no separate retry/backoff machinery. | Retry is postponed (§14). |
| D10 | A Schedule with `last_fired_at IS NULL` is **anchored at now** on its first tick and fires nothing. | "No history" is not "the epoch". Back-filling a cron to 1970 is never the intent. |
| D11 | A Schedule whose Config is disabled or archived advances `last_fired_at` to now without firing. | Otherwise re-enabling a Config would unleash every occurrence that passed while it was off. |
| D12 | Catch-up is capped at `DEFAULT_MAX_CATCHUP = 100` occurrences per schedule per tick. | After a long outage `fire_missed` would otherwise bury the queue. The remainder is picked up by the next tick, so nothing is lost. |
| D13 | `enqueue` refuses an interactive "Run now" with invalid params, but records a born-terminal `failed` Job for a scheduled fire. | §6 allows either. Interactively the user is there to be told; on a schedule nobody is watching, and a silently skipped run is worse than a visible failed one. |
| D14 | The Collector projection's `enabled=False` blocks new enqueues. A collector with no projection row is treated as enabled. | Otherwise the field has no behavior at all. A missing row is a deployment gap (run `sync_collectors`), not a decision to disable. |

| D15 | The UI is Russian, written **directly in the code** — no gettext, no `.po`/`.mo`. | `LANGUAGE_CODE = "ru"` makes Django's own admin chrome Russian from the locale files it ships. For our own strings there is no `msgfmt`/`xgettext` on the target machine, so `compilemessages` cannot run; a catalogue nobody can compile is worse than plain literals. If a second language is ever needed, wrap the strings listed below in `gettext_lazy` and generate the catalogue then. |
| D16 | The tender-site parsers are **vendored** into `collectors/engine/`, framework-free. A *collector* is a parser family (`tender_fogsoft`, `tender_kendo`, `tender_btorg`, `tender_ruson`); a *site* is authored data — domain, listing path and TLS quirks are ordinary parameters. No `platforms.toml`. | See ADR 0002. Keeping sites as parameters is what preserves snapshot completeness: the site is resolved into `effective_parameters` at enqueue, so execution never reads authored state afterwards. The alternative — a code-side site table — would mean either snapshotting a *reference* to a mutable row or one collector key per site. |
| D17 | The «Площадки» tab is `control.models.Platform`, a **proxy of Config** with its own form, not a table. | A platform *is* "what to collect". A second table would duplicate authored intent and need syncing back into the Config that actually runs. The proxy adds a tab and a per-field form with no new state. |
| D18 | **Collected lots are not stored.** A run crawls for real and reports counts (`rows`, `calls`, `listing_pages`) plus a few lot ids in `Job.result`, which carries `"stored": false`. | The user's call, taken knowingly. The engine's `LotSink` protocol is untouched and the runner injects a `CountingSink`, so adding storage later is writing one sink — a `Lot` model in `control`, its sink in `execution` — not reopening the design. |
| D19 | ~~For the tender collectors, v1.0 promises the parameter contract, not byte-identical extraction. A markup fix lands in place; a change to what a site must be told is v2.0.~~ **Superseded by D21** — there is no v2.0 any more; every parameter-contract change now lands in place. | Kept for history. The reasoning ("what a snapshot must keep meaning is *which site, crawled how*") is still why parameter changes are safe to make in place — it just no longer needs a version bump to say so. |
| D20 | `extra_ca_cert` names a PEM file shipped in `collectors/certs/`, never a path. | The value arrives from an admin form. An arbitrary path would let whoever fills it splice any file the worker can read into the trusted CA bundle. |
| D21 | **Removed the `(key, version)` axis entirely.** `CollectorDescriptor` and `Runner` each carry exactly one schema/implementation per key, edited in place; `Job.collector_version` / `schema_version` are dropped (migration `0005`). Deviates from spec §6, whose `"config invalid for collector vX"` wording presumes a version — the message is now `"config invalid for collector {key}"`. Full narrative: ADR 0003. | User's explicit call, taken knowingly after being walked through the cost: historical Jobs are no longer guaranteed to replay against the exact code that ran them (see the narrowed "reproducible" definition above), and the "schedules survive collector upgrades" scenario is retired along with the upgrade concept itself — `config_invalid` now models a Config's raw params drifting out of step with a schema that changed in place, which needs no version story to stay meaningful or testable. In practice only `example_api` (a demo collector, zero real Configs) and the always-single-version tender collectors were affected; nothing in production data depended on multi-version resolution. |

### What is Russian and what is deliberately not

**Russian** (anything a human reads): model `verbose_name` / `help_text`, all `TextChoices`
labels, admin site header, column headers, fieldset titles, actions and messages, form labels and
errors, parameter-validation errors from `collectors.schemas`, collector display names and
parameter descriptions, dashboard templates, seed sample names.

**English on purpose** (anything a machine or a maintainer reads):

- stored values of every `TextChoices` (`"pending"`, `"skip"`, …) — the claim SQL, the tests and
  this document all match on them;
- `EnqueueRefused.reason` codes (`config_disabled`, `params_invalid`, …) — an API, not a message;
- `structured_error["type"]` codes, and the `"config invalid for collector {key}"` message —
  §6 of the spec names a `vX`-suffixed form; **D21** dropped the version, so this is a deliberate
  deviation from the spec's literal wording, not an oversight;
- log lines, exception text for programmer errors, docstrings, comments, and all documentation.

When adding a user-facing string, put the Russian in the code and keep the machine-readable
identifier next to it in English. Never translate a stored value.

### Known limitation: `overlap_policy=queue` under Option A

`skip` and `allow` are exact. **`queue` is not a mutual-exclusion guarantee.** It enqueues the
occurrence and lets it wait, which serialises correctly with a single worker — but with several
workers the queued Job can be claimed while the previous one is still running.

A real guarantee needs the ≤1-active-Job-per-stream invariant: a partial unique index on active
jobs plus the matching claim predicate. That is Option B (§17), which decision **D1** deferred.
Do not paper over this with a lock (§14). If non-overlap is required, reopen the A/B fork.

## Core working rules

- Prefer minimal, explicit, maintainable changes. Do not broaden scope silently.
- Separate domain logic from transport, persistence, side effects and framework glue.
- Make state, time, ordering and idempotency explicit.
- Add or update tests for changed behavior; run relevant validation.
- Stop and ask if the implementation contradicts the spec or requires a larger refactor.

## Definition of done for any change (§15)

```bash
make verify
```

That is `check` + `lint` + `contracts` + `test`:

```bash
python src/manage.py check && python src/manage.py makemigrations --check --dry-run
ruff check . && ruff format --check .
lint-imports
pytest
```

`make up` must bring up the stack and the app must run against it.
