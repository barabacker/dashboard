# Control models redesign — design

Status: draft · Date: 2026-07-31

## Context

An audit of the five existing ADRs (`docs/architecture/adr/0001`–`0005`) against the current
code found four of them accurate and one (`0002`, on lot storage) already stale — a later,
undocumented commit (`dc64417`) added a real `Lot` table and `DbLotSink`, contradicting `0002`'s
"nothing is stored yet." Rather than patch that one gap, the decision (confirmed with the user) is
broader: retire the whole ADR set and `CLAUDE.md`'s invariant list, and redesign the `control`
models from scratch around a specific complaint — *too much is wired together at the DB level, and
it shows in the admin*: `Source`↔`Config` revision cascades, a soft/hard reference mix between
`Source`/`Config`/`Job`, and a dynamically-generated admin form (`ConfigForm` building one Django
field per collector `ParamSpec`, with `get_form`/`get_fieldsets` overrides to work around it).

This document is the result of going through every model in `control` one field at a time with the
user and recording what stays, what changes, and what goes. It does not cover `execution` or
`collectors` — nothing discussed here touches the claim/lease queue, the scheduler's transaction/
constraint mechanics, or the collector engine, all of which were confirmed accurate and are staying
as they are.

Since the project has no production data yet, migrations are not written carefully around existing
rows — the database and migration history can be reset rather than data-migrated.

## Decisions, model by model

### Source

| Field | Before | After |
|---|---|---|
| `name` | — | unchanged |
| `domain` | — | unchanged |
| `listing_path` | optional, code-default per engine | renamed to `start_url`, same semantics |
| `extra_ca_cert` + `skip_tls_verify` | two dedicated columns | merged into one JSON field `tls_options` — a bag for rare, growing site-specific quirks |
| `archived` | soft delete | **removed** — real `DELETE`; `Config.source` stays `on_delete=PROTECT`, so a `Source` referenced by any `Config` still cannot be removed |
| `created_at` / `updated_at` | — | unchanged |

`tls_options` merges into a collector's `effective_parameters` the same way the old flat fields
did: by key-name match against whatever the collector's schema declares (`Source.PARAM_FIELDS`-style
filtering), not by any structural typing. The revision-cascade mechanism (`Source.save()` bumping
every referencing `Config.revision`) disappears as a consequence of removing `Config.revision`
(below), not as a separate decision.

Admin: no structural change — same list/fieldset shape, just the renamed/merged fields.

### Config

| Field | Before | After |
|---|---|---|
| `name`, `source`, `collector_key` | — | unchanged |
| `parameters` | JSON, admin renders one Django field per `ParamSpec` (`ConfigForm._add_parameter_fields`, custom `get_form`/`get_fieldsets`, a no-op override for the `ConfigInline` case) | stays JSON storage, but the admin widget becomes a **plain JSON text field** — no per-field generation, no `get_form`/`get_fieldsets` overrides, no `ConfigInlineForm` special case |
| `enabled` | — | unchanged |
| `archived` | soft delete | **removed** — real `DELETE`. Unlike `Source`, there is no FK to protect: `Job.config_id` is already a soft reference, and `JobAdmin.config_link` already renders `"#123 (удалена)"` when the `Config` a `Job` points at is gone. Deleting a `Config` was already safe for `Job` history before this change. |
| `tags` | JSON list, unused in practice | **removed** |
| `revision` | counter bumped on authored-field change (own or cascaded from `Source`), copied into `Job.config_revision` | **removed entirely** — no snapshot-vs-current-state comparison is kept |
| `owner`, `created_by`, `created_at`/`updated_at` | — | unchanged |
| `last_status`, `last_run_at`, `last_job_id` | denormalized cache columns, written by the worker via direct `UPDATE` so the dashboard list is one query | **removed** — the admin/dashboard list computes the latest `Job` status via a subquery/annotation instead of reading a cache column |

`resolved_preview` (the readonly field showing what `raw_parameters()`/`resolve()` would actually
send to a `Job`) is kept in the change form — it is independent of the per-field form generation
being removed.

Consequence: `Job.config_revision` is removed too, since nothing produces a `Config.revision` to
copy from anymore (see Job, below).

### Collector

No changes, in the model or in the admin. `key`/`display_name`/`description`/`enabled`/`synced_at`
stay exactly as they are; `CollectorAdmin`'s read-only list-plus-schema-table view is unchanged.

### Schedule

| Field | Before | After |
|---|---|---|
| `config` (FK, `CASCADE`) | — | unchanged |
| `cron`, `timezone` | validated in `clean()` | unchanged |
| `enabled` | — | unchanged |
| `overlap_policy` (`skip`/`queue`/`allow`) | three choices, but `queue` and `allow` are behaviourally identical today (no per-stream claim predicate exists to make `queue` a real guarantee) | collapsed to a boolean **`skip_if_running`** — this is a judgment call made without strong user preference either way, on the grounds that it should reflect what the code actually does; revisit if it turns out to matter |
| `catchup_policy` (`fire_missed`/`skip_to_now`) | configurable | **removed** — single fixed behavior: skip missed occurrences, wait for the next one (what `skip_to_now` already did) |
| `last_fired_at`, `created_at`/`updated_at` | — | unchanged |

Admin: no structural change (separate page + `ScheduleInline` under `Config`), just the field
rename/removal reflected in it.

### Job

Only one change: **remove `config_revision`**, as a direct consequence of removing
`Config.revision`. Everything else — the immutable snapshot (`collector_key`,
`effective_parameters`, `config_id`), origin fields (`origin`/`schedule_id`/`fire_time`/
`requested_by`), the claim/lease group (`status`/`claimed_by`/`claimed_until`/`attempt_no`/
`cancel_requested`/`priority`/`available_at`), and the outcome group (`started_at`/`finished_at`/
`result`/`structured_error`/`metrics`/audit timestamps) — was reviewed field-by-field and confirmed
unchanged, including the claim/lease locking semantics (`claimed_by` as ownership token,
`claimed_until` as lease expiry, checked together with `status` on every write). A proposed merge
of `claimed_until` into `available_at` (both mean "when this row becomes claimable again") was
considered and **rejected** — kept as two separate fields for clarity over the marginal field-count
saving.

`JobAdmin` is unchanged beyond dropping `config_revision` from the snapshot fieldset.

### Lot

**Out of scope for this pass.** `control.models.Lot` and `execution/worker/lot_sink.py`
(`DbLotSink`) stay exactly as they are — including the fact that `Lot.source` is a plain hostname
string, not a FK to the new `Source` table, which is an inconsistency worth resolving later but not
now. Revisiting lot storage (including whether it should write to a file instead of a table) is
flagged as a separate, larger piece of future work, not part of this redesign.

## What happens to the old documents

- `docs/architecture/adr/0001-architecture-baseline.md` through `0005-config-parameter-fields.md`
  are retired. `0001`'s package-boundary/queue/scheduler material was reconfirmed accurate against
  the code during the audit that preceded this design — that content is not being thrown away for
  being wrong, it is being thrown away because the user wants a fresh set of principles rather than
  an amended legacy set.
- `CLAUDE.md` no longer exists in the tree (removed in a prior commit) but is still referenced from
  `README.md`/`README.ru.md` and from ADR 0003. Those references need to be cleaned up as part of
  landing this redesign.
- A replacement principles document (scope, format, and location to be decided) should be written
  once the model changes above are implemented — describing the system as it exists after this
  redesign, not as a speculative target.

## Out of scope / explicitly deferred

- `execution` and `collectors` packages, the claim/lease SQL, the scheduler's transaction/
  idempotency mechanics — confirmed accurate, untouched.
- `Lot` storage model and `Lot.source`'s relationship to `Source`.
- The shape of the replacement architecture-principles document.
- Data migration care — none needed; the database and migration history can be reset.

## Open questions for the implementation plan

- Migration strategy: reset `control/migrations` to a fresh initial migration, or write a normal
  incremental migration set? (No data to preserve either way — this is a developer-experience
  choice, not a correctness one.)
- Exact shape of the `Config`/dashboard "latest Job status" subquery/annotation that replaces the
  cache columns.
- Whether `skip_if_running` needs a data migration mapping (`skip` → `True`, `queue`/`allow` →
  `False`) or whether existing `Schedule` rows are being reset along with everything else.
