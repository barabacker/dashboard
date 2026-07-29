# ADR 0002 — Integrating the tender-site parsers

Status: accepted · Date: 2026-07-29

## Context

A temporary project (`barabacker/coll-temp`) grew a working scraping engine for bankruptcy-auction
platforms: an async Spider-style core over `curl_cffi` + `parsel`, four parser families
(fogsoft / kendo / btorg / ruson), and thirty-one live sites. It ran from a CLI, kept its site list
in `platforms.toml`, and wrote collected lots to JSON files. Its decisions were explicitly
provisional.

This back office already had the surrounding machinery the parsers lacked: authored configs,
schedules, a queue, leases, cancellation, job history. What it lacked was anything to collect.

The task was to bring the parsers in without bending either side out of shape.

## Decision

### 1. The engine is vendored into `collectors`, unchanged in substance

`src/collectors/engine/` holds the scraping engine: `core/` (Spider, Lot, parsing helpers, the
`LotSink` protocol), `http/` (client, middleware, TLS) and `sources/` (the four families and their
page extractors). It imports no Django, no `control`, no `execution` — which is exactly the rule
`collectors` already lived by, so it fits the leaf package as-is.

Three things changed on the way in, all at the edges:

* **Cancellation and lease renewal.** `ParserContext` gained two optional callables —
  `should_stop()` (a predicate, polled between requests) and `heartbeat()`. The crawl loop drains
  its queue instead of fetching once a stop is latched. The engine learns nothing about Jobs;
  the runner supplies both callables.
* **Certificates are named, not pathed.** `extra_ca_cert` now names a file shipped in
  `src/collectors/certs/`. The value arrives from a form, and an arbitrary path would let whoever
  fills it splice any readable file into the trusted CA bundle.
* **Counters.** The crawl reports requests and listing pages alongside lots, so a Job carries
  something an operator can read.

### 2. A collector is an **engine**; a site is **data**

Four collector keys ship: `tender_fogsoft`, `tender_kendo`, `tender_btorg`, `tender_ruson`, each
at version `1.0`. A site's domain, listing path and TLS quirks are *parameters* of a Config,
declared by the collector's schema like any other parameter.

`platforms.toml` is gone. The site list lives in the database and is edited in the admin, which is
what the user asked for; `manage.py seed_platforms` carries the thirty-three entries over once as
initial data.

This is not merely a relocation. Had the sites stayed a code-side table, either a Job snapshot
would have to carry a *reference* to a mutable row — and execution would be reading authored state
after enqueue, which the snapshot exists to prevent — or every site would need its own collector
key and its own runner. As parameters, the site's fields are resolved into
`effective_parameters` at enqueue and the invariant holds with nothing added.

### 3. The platform tab is a proxy model, not a table

`control.models.Platform` is a proxy of `Config` with its own admin registration and a form that
asks for a site (domain, listing path, TLS switches) instead of a JSON object. Its manager shows
only Configs whose collector key starts with `tender_`.

A second table would have duplicated the authored intent — a platform *is* "what to collect" — and
would have needed syncing back into the Config that actually runs. A proxy gives the tab and the
form with no new state and no migration beyond the proxy's own.

### 4. Nothing is stored yet

There is no table for collected lots (the user's call, taken with the trade-off stated). A run
crawls for real and reports counts — `rows`, `calls`, `listing_pages` — plus a handful of lot ids
in `Job.result`, and discards the lots.

The engine's `LotSink` protocol is untouched and the runner injects a `CountingSink`, so adding
storage later is writing one sink and passing it in — not reopening this design. `Job.result`
carries `"stored": false` so a finished Job does not imply otherwise.

## Consequences

* Four new collectors, thirty-three platforms, one dependency set (`curl_cffi`, `parsel`,
  `pydantic`, `certifi`, `tenacity`) added to the single deployment.
* `collectors.schemas` must stay pure, or the web process starts importing `lxml` and `curl_cffi`
  through `control`. A fourth import-linter contract enforces it, including on the third-party
  packages by name.
* The engine's own test suite (fixture-driven, no network) came across intact and runs as part of
  `tests/unit/`; the site-registration tests were rewritten against `SiteSpec`.
* **A parsing fix does not bump the version.** For these collectors v1.0 promises a *parameter
  contract*, not a byte-identical extraction: sites change their markup, and a fix that reads a
  renamed column is the same contract finally honoured. A change to what a site must be *told* —
  a new required parameter, a renamed one — is v2.0. This is a deliberate reading of the
  `(key, version)` invariant, recorded because a stricter reading would make every markup fix a
  new module.
* `overlap_policy=queue` remains the known non-guarantee it already was; a per-site crawl is
  exactly the kind of long job that makes it visible. Unchanged by this work.
