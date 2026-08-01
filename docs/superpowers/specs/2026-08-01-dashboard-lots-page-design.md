# Design: `/dashboard/lots/` — read-only lots page

Date: 2026-08-01 · Status: approved, not yet implemented

## Why

Collected lots are written to MongoDB (`execution.worker.mongo_lot_sink.MongoLotSink`), not to the
`control.models.Lot` table — that model's own docstring says it is no longer written to, kept only
so old rows stay queryable. Since the Mongo cutover (`3a588d5`), nothing reads lots back: no admin,
no view, no template touches `get_lots_collection()`. Staff have no way to see what's actually been
collected without querying Mongo by hand. This adds a read-only "Лоты" page to the existing
`control/dashboard/` app, next to the configs/jobs dashboard, in the same Unfold-styled house style.

## Decisions made during brainstorming

1. **Lives in `control/dashboard/`, not `django-admin`'s `ModelAdmin`.** `ModelAdmin` needs a Django
   `QuerySet`; the data is Mongo documents. The dashboard app already exists as a plain-view escape
   hatch styled like admin (see its own docstring: "Django Admin is the primary UI; this exists for
   the two things a list page is bad at") — a Mongo-backed list is a third such case.
2. **`control` gets its own Mongo client, not a reused import from `execution.worker.mongo`.**
   `pyproject.toml`'s import-linter contract forbids `control` from importing `execution`
   (`source_modules = ["control"]`, `forbidden_modules = ["execution"]`). The web process and the
   worker process are separate processes anyway, so a second lazily-cached `pymongo.MongoClient` in
   `control` (same singleton pattern as `execution/worker/mongo.py`, not shared code) is the correct
   fix, not a boundary violation to route around.
3. **List columns: source, lot number, status, price, bidding deadline** (`source`, `lot_num`,
   `status`, `price`, `bidding_deadline`). Everything else (`debtor`, `organizer`, `description`,
   `attachments`, `price_schedule`, `extra`, raw fields, timestamps, `last_job_id`) lives only on the
   detail page.
4. **Filter by `source` only; no text search.** A `<select>` populated from
   `collection.distinct("source")`. No `q` search box — not requested, and `lot_num`/`description`
   aren't indexed for it.
5. **Sort: `last_seen_at` descending**, fixed (no column sorting UI). Matches the existing
   `lot_by_last_seen` index, so no new index is needed.
6. **Pagination: plain `?page=N` links, page reload.** Consistent with the "no JS framework, HTMX
   only for the jobs auto-refresh panel" decision already made for this app
   (`2026-08-01-dashboard-unfold-redesign-design.md`). Implemented by hand (`skip`/`limit` +
   `count_documents`), since Mongo has no `django.core.paginator.Paginator` support.
7. **Detail is its own page (`/dashboard/lots/<id>/`), not a modal.** Simpler, works without JS, and
   a lot can be linked to directly. Keyed by the Mongo `_id` (`ObjectId`), not `(source, lot_id)` —
   one path segment instead of two, and `_id` is already the natural unique handle for a single
   document fetch.
8. **Detail page shows every field**, including `attachments`/`price_schedule`/`extra` as
   pretty-printed JSON, plus a link to `lot_url`.

## What changes

| Area | Change |
|---|---|
| `src/control/services/mongo.py` (new) | Lazily-cached module-level `pymongo.MongoClient` built from `settings.MONGO_URI`, mirroring `execution/worker/mongo.py`'s pattern as a separate instance — `control` cannot import `execution` (import-linter). `get_lots_collection()` returns `client[settings.MONGO_DB_NAME]["lots"]`. |
| `src/control/services/lots.py` (new) | `list_lots(*, source: str \| None, page: int, page_size: int = 50) -> LotsPage` — filters by `source` if given, sorts `-last_seen_at`, applies `skip`/`limit`, returns items + `total_count` + `distinct sources` list. `get_lot(id: str) -> dict \| None` — fetch by `ObjectId(id)`; returns `None` on a malformed id or a miss (view turns that into 404). |
| `src/control/dashboard/views.py` | New `lots_list(request)` and `lot_detail(request, id)`, both `@staff_member_required`. `lots_list` reads `source`/`page` from `GET`, calls `list_lots`, renders `dashboard/lots.html` with `admin.site.each_context(request)`. `lot_detail` calls `get_lot`, 404s via `Http404` if `None`, renders `dashboard/lot_detail.html`. |
| `src/control/dashboard/urls.py` | `path("lots/", views.lots_list, name="lots_list")`, `path("lots/<str:id>/", views.lot_detail, name="lot_detail")`. |
| `src/control/templates/dashboard/lots.html` (new) | Extends `dashboard/base.html`. Source `<select>` filter (plain `GET` form, page reload). Table: источник, номер лота, статус (badge), цена, дедлайн торгов; each row links to its detail page. Page-number links at the bottom, preserving `source` in the query string. Empty state when no lots match. |
| `src/control/templates/dashboard/lot_detail.html` (new) | All document fields in a definition-list/card layout; `attachments`/`price_schedule`/`extra` rendered as `<pre>`-formatted JSON (`json.dumps(..., indent=2, ensure_ascii=False, default=str)` — `ObjectId`/`datetime` need `default=str`); `lot_url` as a real link; back-link to the filtered list. |
| `src/control/templatetags/dashboard_extras.py` | Reuse the existing status badge filter for the lot's `status` field if its values overlap with what the filter already handles; otherwise a small addition — confirmed at implementation time by inspecting actual stored `status` values. |
| `src/project/settings.py` | `UNFOLD["SIDEBAR"]["navigation"]` — new item "Лоты" (icon `inventory_2` or similar) in the "Сбор данных" group, after "Задачи", linking to `reverse_lazy("dashboard:lots_list")`. |
| `tests/test_dashboard_lots.py` (new) | See Testing below. |

## What does not change

- `control.models.Lot`, `execution.worker.mongo_lot_sink`, `execution.worker.mongo` — untouched;
  this is a new read path alongside the existing write path, not a replacement.
- The import-linter contracts — a second, independent Mongo client in `control` keeps `control` and
  `execution` decoupled exactly as the existing contract requires.
- `/admin/` and every model changelist under it.
- The configs/jobs dashboard (`index`, `jobs_panel`, `run_now`, `run_selected`, `cancel_job`) — no
  changes to that page or its views.

## Testing

New `tests/test_dashboard_lots.py`, using `mongomock` for a fake `pymongo` collection (the same kind
of fake `mongo_lot_sink.py`'s own docstring already anticipates: "some client implementations
(mongomock's fake among them)"), injected in place of `control.services.mongo.get_lots_collection`:

- `lots_list` renders only lots matching the `source` filter when one is given, and all lots when it
  is absent;
- results are ordered by `last_seen_at` descending;
- pagination: with more than one page's worth of documents, page 2 shows the next slice and the page
  links carry the current `source` filter forward;
- `lot_detail` renders all fields for a valid `_id`, including pretty-printed JSON for
  `attachments`/`price_schedule`/`extra`;
- `lot_detail` returns 404 for an `_id` that doesn't exist and for a malformed id string;
- both views 302-redirect to login for an unauthenticated request (same as the existing dashboard
  views).

No migration is needed — no Django model changes. Import-linter contracts are unaffected; a new
`importlinter` contract is not needed either, since `control.services.mongo` never imports
`execution`.
