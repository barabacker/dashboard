# ADR 0003 — Removing the `(key, version)` axis

Status: accepted · Date: 2026-07-30

## Context

ADR 0001 named `(key, version) always resolves to runnable code` as a baseline invariant, and ADR
0002 built the four tender collectors on top of it: each shipped `v1.0`, with the rule that a
parameter-contract change (not a markup fix) forces a new version rather than an in-place edit.

In practice, no collector ever used the mechanism for its stated purpose. The four tender
collectors have shipped exactly one version each since ADR 0002. Only `example_api` — a
demonstration collector with zero real `Config` rows — carried two versions, and it existed
specifically to exercise version resolution end to end (its own docstring said so). The admin
surface built on top (two "current version" columns on the Collector list) surfaced version
plumbing nobody was using.

The user's explicit call, after being walked through the cost: remove the version axis from the
architecture entirely, not just tidy its admin display.

## Decision

A collector key resolves to exactly one schema (`collectors.schemas.base.CollectorDescriptor`,
merged with what used to be the separate `CollectorVersionSchema`) and exactly one runner. Both are
edited in place as requirements change — the same as any other code, with no forked module and no
version string attached.

Concretely:

* `CollectorDescriptor` carries `params` directly; `versions`, `version_names`, `current_version`,
  and `schema(version)` are gone. `UnknownCollectorVersion` is gone with them.
* `collectors.registry` keys `_RUNNERS` by collector key alone. `resolve(key)` is single-argument.
* `Job.collector_version` and `Job.schema_version` are dropped from the model (migration `0005`);
  `RunContext` no longer carries them either.
* `example_api` collapses to one schema and one runner (`ExampleApiV1`/`ExampleApiV2` → a single
  `ExampleApi`, keeping v2's fuller parameter set — `dataset`, `since`, `page_delay_seconds` —
  since it was the strict superset and the more useful demonstration).
* The tender runners lose their `_v1` suffix (`tender_site_v1.py` → `tender_site.py`); nothing
  about their behavior changes, only the version framing around them.
* `structured_error["message"]` for an invalid Config is now `"config invalid for collector
  {key}"`. Spec §6 names a `vX`-suffixed form; this is a deliberate deviation, not an oversight —
  see CLAUDE.md's decision **D21**, which is the authoritative record of this change and its
  consequences. This ADR is the fuller narrative; D21 is what a future reader should trust if the
  two ever appear to disagree.

## Consequences

* **Reproducibility is narrower than ADR 0001 promised.** "Same target + same params + same
  version code, forever" becomes "same target + same params + the collector's code as it exists
  today." A Job snapshot from before a schema or runner change no longer replays against the exact
  code that produced it — it replays against whatever the key resolves to now. This is the real
  cost of this decision, not a side effect of it.
* **`config_invalid` no longer needs a version story.** It now models a Config's raw parameters
  drifting out of step with a schema that was edited in place — the same test coverage
  (`tests/test_enqueue.py::TestInvalidParameters`, `tests/test_scheduler.py`) exercises this by
  constructing a Config missing a required parameter directly, with no version bump involved.
* **The historical-runner-module discipline is gone.** A parser fix or a new required parameter
  both land in the one existing module now; there is no longer a rule distinguishing "fix in
  place" from "new version" (ADR 0002 §84 is superseded).
* Two admin columns (`known_versions`, `current_version` on `Collector`) were removed as
  vestigial — this decision is what made them meaningless, not the other way around.
