# Design: `/dashboard/` — Unfold styling + operational functionality

Date: 2026-08-01 · Status: approved, not yet implemented

## Why

`src/control/dashboard/` is a small, hand-rolled HTML+CSS page with its own inline `<style>` block
and its own login screen, sitting next to a Django Admin themed with `django-unfold`. The two
surfaces look nothing alike, and the dashboard's own docstring states its reason to exist: "the two
things a list page is bad at: seeing at a glance what ran, and starting or stopping a run without
leaving the page." Right now it does the first only loosely (33 `Config` rows in one flat table,
no grouping, search, or bulk action) and the second only for starting, not stopping.

This pass fixes both: restyle the page to Unfold's own chrome and components instead of a parallel
design system, and close the functional gaps — family grouping, search/filter, bulk "run selected",
and a "stop" action reachable from the config row itself (not only from the jobs table below it).

## Decisions made during brainstorming

1. **Stay a separate `/dashboard/` page**, not merged into `/admin/`'s own index via
   `UNFOLD["DASHBOARD_CALLBACK"]`. Both were technically viable (the callback only adds to
   `admin/index.html`'s context — it does not remove the app list or touch any other admin page)
   but the user preferred keeping the dashboard as its own page.
2. **Match Unfold by extending its templates**, not by re-implementing its look. `dashboard/base.html`
   extends `unfold/layouts/base.html`; the view functions add `admin.site.each_context(request)` to
   their template context (what `unfold/layouts/base_simple.html` needs for the sidebar/header
   chrome — `is_nav_sidebar_enabled`, branding, theme switch). Views stay plain functions — no
   move to class-based views or `UnfoldSiteViewMixin`, which exists for that style but isn't needed
   here.
3. **No new JS framework.** Grouping is a native `<details open>` per collector family — no
   accordion component, no JS. Search/filter is a plain GET form (page reload), not live/HTMX
   filtering. The project has no JS framework today (HTMX only, for the jobs panel's auto-refresh);
   introducing one (e.g. Alpine.js) for this was considered and rejected as unneeded complexity.
4. **The configs table does not gain HTMX auto-refresh.** Considered, to make a "stopping" job's
   status update live like the jobs panel below it does. Rejected: the existing "plain POST,
   redirect, reload" pattern already shows the correct status the moment the action that changed it
   completes (cancel is synchronous for a pending job; `cancel_requested` flips synchronously for a
   running one), and a 5-second auto-refresh would repeatedly clear the bulk-run checkboxes out from
   under whoever is mid-selection. The jobs panel below keeps its own independent 5s auto-refresh,
   unaffected.
5. **Bulk run only offers "run"**, not "stop selected" — stopping several configs at once was not
   requested and each stop is already one click from its own row.

## What changes

| Area | Change |
|---|---|
| `src/control/templates/dashboard/base.html` | Extends `unfold/layouts/base.html`; drops the entire inline `<style>` block and the hand-rolled `<nav>`/messages markup (Unfold's own `header.html`/`messages.html` partials, pulled in through the layout, take over). |
| `src/control/dashboard/views.py` — `index` | Query gains an `active_job_id` annotation: a `Subquery` over `Job` filtered to `status__in=JobStatus.active()`, latest by `created_at`, per config (replaces the current separate `active_config_ids` set query — the id doubles as "is something active" and as the target of the Stop form). Configs are grouped into an ordered `dict[collector_key, {"label": Collector.display_name, "configs": [...]}]`, ordered by `collector_key`. Two new `GET` params: `q` (name, `icontains`) and `state` (`all` \| `enabled` \| `disabled`), applied to the queryset before annotation. Context passes `admin.site.each_context(request)`. |
| `src/control/dashboard/views.py` — new `run_selected` | `POST`, staff-required. Reads repeated `config_id` fields, calls `enqueue()` per id (skipping ids that don't resolve to a `Config`), tallies successes/refusals into one `messages` summary (e.g. "Поставлено в очередь: 5. Отказано: 2 (уже выключены)."). Redirects to `dashboard:index` preserving `q`/`state` from a hidden form field echoing `request.GET.urlencode`. |
| `src/control/dashboard/urls.py` | New path `configs/run-selected/` → `run_selected`, name `run_selected`. |
| `src/control/templates/dashboard/index.html` | One `<form>` wraps the whole configs section. Per collector family: a `<details open>` with `Collector.display_name` and a count in `<summary>`, containing that family's rows. Table header gains a "select all" checkbox (visible rows only) and a search/state filter bar above it (plain `GET` form). Each row gets a checkbox (`name="config_id"`), disabled when the config is disabled or already has an active job. The action cell shows "Запустить" (as today) when idle, "Остановить" (POSTing to the existing `cancel_job` with `active_job_id`) when active, or a disabled "останавливается…" label when `cancel_requested` is already set on that active job — mirroring `_jobs.html`'s existing treatment of the same state. A "Запустить выбранные (N)" submit button sits above the table. |
| `src/control/templates/dashboard/_jobs.html` | Re-themed with Unfold's table/badge styling; behavior (HTMX 5s auto-refresh, tally, cancel form) unchanged. |
| `tests/test_dashboard.py` | New/extended cases — see Testing below. |

## What does not change

- `dashboard:jobs_panel` and `dashboard:cancel_job` views — reused as-is (`cancel_job` is now also
  the target of the config row's Stop button; no new cancellation logic).
- The "plain POST that redirects" action pattern, and HTMX's role limited to the jobs panel's
  auto-refresh.
- Any model, migration, or the `control`/`execution` import-linter boundary — this is a
  view/template-only change against existing `Config`/`Job`/`Collector` fields.
- `/admin/` itself and every model changelist under it.

## Testing

Extends `tests/test_dashboard.py` (existing fixtures only — `config`, `make_config`, `user`):

- configs from different `collector_key`s render under separate family headings carrying
  `Collector.display_name`;
- `?q=` and `?state=disabled` narrow the rendered rows as expected; a family with no matching
  config does not render its heading;
- `run_selected` with several `config_id`s creates a `pending` `Job` for each enabled config and
  creates none for a disabled one, surfacing its refusal in the response;
- a config with a `pending` or `running` `Job` renders a Stop button targeting that job's id, and
  posting to it behaves exactly as the existing `cancel_job` tests already establish (pending →
  cancelled outright, running → `cancel_requested` only);
- a config whose active job already has `cancel_requested=True` renders the disabled
  "останавливается…" state instead of a clickable Stop button.

No migration is needed. Import-linter contracts are unaffected — `dashboard` still only reaches
into `control.models` and `control.services`.
