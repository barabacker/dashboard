# ADR 0004 — `Site` as a first-class entity, separate from a collection profile

Status: accepted · Date: 2026-07-31

## Context

ADR 0002 built the tender-site collectors on two decisions recorded as D16 and D17: a site's
domain, listing path and TLS quirks are *parameters* of a `Config`, and the «Источники» tab
(`control.models.Source`) is a proxy of `Config` — no second table, because a source *is* "what to
collect" and duplicating it would mean syncing two authored copies of the same intent.

Both decisions implicitly assumed a 1:1 relationship between a site and a `Config` row. Two
forcing factors broke that assumption:

1. **Multiple named collection profiles per site.** The user wants one site (say `cian.ru`) to run
   under several named profiles — `default`, `full`, `fast` — differing only in *behaviour*
   (`max_pages`, `only_active`, `fetch_details`, `concurrency`), not in *identity* (`domain`,
   `listing_path`, TLS quirks). Under D16/D17, each profile would need its own `Config`, and the
   site's identity fields would have to be re-entered — and kept in sync by hand — in every one of
   them.
2. **A genuinely different collector family.** The four tender engines happen to share almost the
   same parameter shape, which is why `SourceForm`'s hardcoded union-of-fields approach (`PARAM_FIELDS`)
   worked. A real-estate collector for `cian.ru` does not share that shape (different attributes
   entirely, likely a credential reference for an API key), which is what exposed that "site" and
   "which engine, with which behaviour" were never really the same axis — they were only ever
   observed to coincide.

Neither forcing factor requires reopening **snapshot completeness** (§ frozen): a Job still needs
to run from a single resolved dict, taken once at enqueue, never re-read afterwards. What it
requires is separating *site identity* (reusable) from *collection profile* (named, one row per
behaviour + engine combination).

## Decision

### 1. `Site` is a new model, not a parameter bag

`control.models.Site`: `name`, `domain`, `listing_path` (optional — see below), `extra_ca_cert`,
`skip_tls_verify`, `archived`, `created_at`/`updated_at`. Human-authored, soft-deleted the same way
`Config` is. This supersedes the "site is a Config parameter" half of **D16**.

### 2. `Config` gains an optional `site` FK; `collector_key` stays put

`Config.site` is `ForeignKey(Site, null=True, on_delete=PROTECT)`. `null=True` so collectors with
no site concept (`example_api`) are untouched. `collector_key` is **not** duplicated onto `Site` —
`Job.collector_key` is a `SNAPSHOT_FIELDS` entry sourced from exactly one place today, and keeping
it that way avoids a polymorphic snapshot field ("read from `Site` for site-shaped configs, from
`Config` for everything else"). The practical effect: creating the first profile for a new site
asks for `collector_key` and the site's identity fields in one form (with an inline "add site"
affordance so the two are one guided step, not two separate admin screens); creating a second
profile for an existing site defaults `collector_key` to what the site's other profiles already
use, as a suggestion, not a hard constraint.

### 3. Resolution merges disjoint key sets, filtered by the target schema

At enqueue, `effective_parameters` is resolved from `{site fields the collector's schema declares}
∪ {config.parameters}`. The two sets are disjoint by construction — a site field and a profile
field never share a name — so there is no override semantics to define, only a union. Site fields
are filtered through `descriptor.param(name) is not None` before merging, so a collector whose
schema does not declare, say, `listing_path` never sees it, instead of `resolve_parameters` failing
on an "unknown parameter" it was never asked about.

### 4. `listing_path` stays authored, with a code default — not hardcoded

`tender.py` already documents that sites *within* one engine family can need a non-default listing
path (`sistematorg`, `promkonsalt` serve `tradelist.php`, not the family's usual
`bankrot/trade_list.php`). Fully hardcoding it into code would have reopened exactly the file-edit-
and-deploy path ADR 0002 removed for site attributes. `listing_path` therefore lives on `Site` as
an optional field, defaulting to `DEFAULT_LISTING_PATHS[engine]` from code when left blank, and
overridable per site — the site is where it belongs conceptually (it is about the domain, not about
which profile of that domain is running), and it keeps the escape hatch the existing exceptions
need.

### 5. `Site.save()` cascades a revision bump onto its Configs

`Config.revision` (via `REVISIONED_FIELDS`) only reacts to changes on `Config` itself. Since
`domain`/`listing_path`/TLS quirks move to `Site`, an edit there would otherwise leave every
profile's `revision` stale relative to what it would actually resolve to. `Site.save()` detects a
change to its own tracked fields and issues `Config.objects.filter(site=self).update(revision=F("revision")
+ 1)` — a direct UPDATE, the same pattern `Config.record_job_outcome` /
`Config.forget_job_outcomes` already use for cascading effects that are not the row's own authored
edit.

### 6. `CollectorDescriptor.is_site: bool = False`

A pure, schema-level flag (no DB, no migration) replacing the `tender_` key-prefix string
`SourceManager` used to filter on. Each schema module sets it at the point where the descriptor is
defined — `tender._descriptor_for` sets `True` for all four engines, `example_api.DESCRIPTOR`
leaves the default `False`. `SourceManager.get_queryset()` filters
`collector_key__in=[d.key for d in schemas.all_collectors() if d.is_site]`. This keeps "is this
collector site-shaped" a fact declared where the collector is defined, not a second list kept in
sync by hand elsewhere.

### 7. `SourceForm` renders per-profile fields from `ParamSpec`, not a hardcoded union

The form builds one Django field per `ParamSpec` of the *selected* collector — a direct mapping
from the closed `kind` set already defined in `collectors/schemas/base.py` — instead of a fixed
`PARAM_FIELDS` tuple assembled by hand from the four tender schemas. Choices (e.g. `extra_ca_cert`)
move into the `ParamSpec` itself (`tender._params_for` passes `choices=available_certs()` directly)
rather than being special-cased in the form. Adding a site-shaped collector whose parameters are
plain `str`/`int`/`float`/`bool` needs no `SourceForm` change at all.

## Consequences

- **D16 is superseded.** "Site is a Config parameter, no site table" no longer holds; see the
  narrower replacement above.
- **D17 is narrowed, not reversed.** «Источники» is still `Source`, a proxy of `Config` with its
  own form — that part stands. What changes is that `Config` is no longer the only new state below
  it: `Site` is a second authored table one level up, referenced rather than duplicated by every
  profile that runs against it.
- **Snapshot completeness is untouched.** `effective_parameters` is still resolved once, at
  enqueue, into a flat dict; execution still never reads `Site` or `Config` again afterwards. This
  ADR does not reopen that invariant — it only changes where the *authored* data before resolution
  lives.
- A migration adds `Site` and `Config.site`. `Config.parameters` for existing tender `Source` rows
  needs a data migration splitting `domain`/`listing_path`/`extra_ca_cert`/`skip_tls_verify` out
  into a new `Site` row per distinct domain, leaving only the behavioural keys in `parameters`.
- `revision` now reflects two kinds of change for a site-attached `Config`: its own authored edit,
  and a cascade from its `Site`. Both bump the same counter; nothing distinguishes them in
  `Job.config_revision` history. Acceptable — the counter's job is "does this Job's snapshot match
  what the Config+Site would resolve to today", not "who edited what."
- `concurrency` stays a profile-level parameter (`Config.parameters`), not a `Site` field and not a
  code constant — deliberately, since it is plausibly a per-profile knob ("fast" vs "full" may want
  to run at different concurrency), not a site-identity fact.
