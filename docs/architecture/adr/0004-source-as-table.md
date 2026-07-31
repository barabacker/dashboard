# ADR 0004 — `Source` becomes a real table; `Config` references it

Status: accepted · Date: 2026-07-31

## Context

ADR 0002 built the tender-site collectors on two decisions recorded as D16 and D17: a site's
domain, listing path and TLS quirks are *parameters* of a `Config`, and the «Источники» tab
(`control.models.Source`) is a **proxy** of `Config` — the same row, shown and edited differently.
No second table, because a source *is* "what to collect" and duplicating it would mean syncing two
authored copies of the same intent.

Both decisions assumed a 1:1 relationship between a site and a `Config` row. Two forcing factors
broke that assumption:

1. **Multiple named collection profiles per site.** One site (say `cian.ru`) needs to run under
   several named profiles — `default`, `full`, `fast` — differing only in *behaviour*
   (`max_pages`, `only_active`, `fetch_details`, `concurrency`), not in *identity* (`domain`,
   `listing_path`, TLS quirks). Under a proxy, each profile would need its own `Config` row, and
   the site's identity fields would have to be re-entered — and kept in sync by hand — in every
   one of them.
2. **A genuinely different collector family.** The four tender engines share almost the same
   parameter shape, which is why `SourceForm`'s hardcoded union-of-fields approach worked. A
   real-estate collector for `cian.ru` does not share that shape, which is what exposed that "site"
   and "collector profile" were never really the same axis — they only ever were observed to
   coincide.

An earlier draft of this decision proposed introducing a third concept (`Site`) alongside the
existing `Source`/`Config` pair, with `Source` staying a `Config` proxy and the new `Site` holding
identity. That added a term nobody asked for and duplicated what `Source` was already supposed to
mean. The simpler fix: stop treating `Source` and `Config` as the same row. `Source` already *is*
the right word for "a site, authored" in every admin label and every conversation about this
system — it just needs to stop being a proxy and become the table it was always describing.

Neither version of this decision reopens **snapshot completeness** (§ frozen): a Job still runs
from a single resolved dict, taken once at enqueue, never re-read afterwards.

## Decision

### 1. `Source` stops being a `Config` proxy — it becomes its own table

`control.models.Source`: `name`, `domain`, `listing_path` (optional — see below), `extra_ca_cert`,
`skip_tls_verify`, `archived`, `created_at`/`updated_at`. Human-authored, soft-deleted the same way
`Config` is. This supersedes **D16** (site-as-parameter) and **D17** (proxy, no table) together —
neither holds any more.

### 2. `Config` gains an optional `source` FK; `collector_key` stays put

`Config.source` is `ForeignKey(Source, null=True, on_delete=PROTECT, related_name="configs")`.
`null=True` so collectors with no site concept (`example_api`) are untouched. `collector_key` is
**not** duplicated onto `Source` — `Job.collector_key` is a `SNAPSHOT_FIELDS` entry sourced from
exactly one place today, and keeping it that way avoids a polymorphic snapshot field. A `Config`'s
own `name` is now the *profile*'s name ("cian.ru — full"), not the site's name — the site's name
lives on `Source`.

One `Source`, many `Config` rows. Creating the first profile for a new site asks for
`collector_key` and the site's identity fields together (with an inline "add source" affordance so
the two are one guided step); creating a second profile for an existing source defaults
`collector_key` to what the source's other profiles already use, as a suggestion, not a hard
constraint.

### 3. Resolution merges disjoint key sets, filtered by the target schema

At enqueue, `effective_parameters` is resolved from `{source fields the collector's schema
declares} ∪ {config.parameters}`. The two sets are disjoint by construction — a source field and a
profile field never share a name — so there is no override semantics to define, only a union.
Source fields are filtered through `descriptor.param(name) is not None` before merging, so a
collector whose schema does not declare, say, `listing_path` never sees it.

### 4. `listing_path` stays authored, with a code default — not hardcoded

`tender.py` already documents that sites *within* one engine family can need a non-default listing
path (`sistematorg`, `promkonsalt` serve `tradelist.php`, not the family's usual
`bankrot/trade_list.php`). It lives on `Source` as an optional field, defaulting to
`DEFAULT_LISTING_PATHS[engine]` from code when left blank, and overridable per source.

### 5. `Source.save()` cascades a revision bump onto its Configs

`Config.revision` (via `REVISIONED_FIELDS`) only reacts to changes on `Config` itself. Since
`domain`/`listing_path`/TLS quirks move to `Source`, an edit there would otherwise leave every
profile's `revision` stale relative to what it would actually resolve to. `Source.save()` detects a
change to its own tracked fields and issues
`Config.objects.filter(source=self).update(revision=F("revision") + 1)` — the same direct-UPDATE
pattern `Config.record_job_outcome` / `Config.forget_job_outcomes` already use for cascading
effects that are not the row's own authored edit.

### 6. `CollectorDescriptor.is_site: bool = False`

A pure, schema-level flag (no DB, no migration) marking which collectors are site-shaped. Used to
constrain which `collector_key` choices are offered when authoring a `Config` that has a `source`
set — **not** for filtering a queryset the way `SourceManager` used to, because `Source` is no
longer a filtered subset of `Config` rows. `SourceManager` is removed entirely; `Source` is an
ordinary model with the default manager.

### 7. Admin surface

`Source` gets its own top-level `ModelAdmin` — the registry of real sites (domain, listing path,
TLS quirks, nothing about behaviour or engines). `ConfigAdmin` (unchanged model, `control.models.Config`)
gains a `source` field — optional, autocomplete — so a profile can be attached to a registered site
or left standalone (`example_api` and similar). The old `SourceForm`/`SourceAdmin`, built around
"Source is a Config with per-field editing," are replaced rather than extended: there is no proxy
left to subclass a form for.

## Consequences

- **D16 and D17 are both superseded**, not narrowed. "Site is a Config parameter" and "Источники
  is a proxy of Config with no table of its own" no longer hold in any form. The FK direction is
  `Config → Source`, the reverse of how a reader of D17 might expect a "second table" to attach.
- **Snapshot completeness is untouched.** `effective_parameters` is still resolved once, at
  enqueue, into a flat dict; execution still never reads `Source` or `Config` again afterwards.
  This ADR only changes where the *authored* data before resolution lives.
- A migration replaces the old proxy `Source` with a real table and adds `Config.source`. Existing
  tender `Config` rows need a data migration: split `domain`/`listing_path`/`extra_ca_cert`/
  `skip_tls_verify` out of `parameters` into a new `Source` row per distinct domain, point the
  `Config` at it via the new FK, and leave only the behavioural keys (`max_pages`, `only_active`,
  `fetch_details`, `concurrency`) in `parameters`.
- `revision` now reflects two kinds of change for a `Config` with a `source`: its own authored
  edit, and a cascade from the `Source` it references. Both bump the same counter; nothing in
  `Job.config_revision` history distinguishes them. Acceptable — the counter's job is "does this
  Job's snapshot match what the Config+Source would resolve to today," not "who edited what."
- `concurrency` stays a profile-level parameter (`Config.parameters`), not a `Source` field and not
  a code constant — it is plausibly a per-profile knob ("fast" vs "full" may want different
  concurrency), not a site-identity fact.
- Every place that previously treated "a Source" as "a Config filtered by key prefix" — tests,
  `seed_sources`, `SourceForm`, `SourceAdmin`, `SourceManager` — needs rewriting, not extending.
