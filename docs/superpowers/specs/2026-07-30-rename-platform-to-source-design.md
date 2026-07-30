# Design: rename `Platform` → `Source`

Date: 2026-07-30 · Status: approved, not yet implemented

## Why

`control.models.Platform` is the tab where trading-platform sites (fogsoft/kendo/btorg/ruson) are
authored. The name fit while every source the system collected from was, literally, a bankruptcy
auction trading platform. It stops fitting the moment a non-auction source is added — e.g.
`cian.ru`, a real-estate listing site with no "platform" in the auction sense at all.

This is a pure rename: the label and the identifiers change, nothing about behavior does. The
tab still shows only `Config` rows whose `collector_key` starts with `tender_`; the form still
asks for the same fixed set of tender-specific fields (domain, listing path, TLS switches,
`fetch_details`). Decoupling "site" from "which collector parses it" — so a future non-tender
source can get its own generalized authoring form — is explicitly out of scope here; the user
raised it as a separate, larger concern and chose to defer it to its own design pass.

## Decisions made during brainstorming

1. **Scope of the new name: one word for every kind of source**, not "keep «Площадка» for tender
   sites and invent a new tab per family later." The `Source` proxy's manager keeps its current
   `collector_key__startswith='tender_'` filter for now (unchanged behavior) — broadening it to
   show every collector family is part of the deferred site↔collector redesign, not this pass.
2. **The word: «Источник» / `Source`.** Considered alternatives: «Сайт» (too literal — excludes a
   future non-website source such as an API or feed) and «Цель» (reads as a security/pentest term
   in an admin UI, not a fit for an internal back office).
3. **Rename scope: labels *and* code identifiers**, not just the Russian strings. The user chose
   this explicitly over the cheaper label-only option, for the sake of a future reader of the code
   not finding "Platform" misleading once the label already says otherwise.

## What changes

| File | Change |
|---|---|
| `src/control/models.py` | `Platform` → `Source`; `PlatformManager` → `SourceManager`; `verbose_name`/`verbose_name_plural` → «Источник»/«Источники». The `domain` property and the `collector_key__startswith` filter are unchanged. |
| `src/control/forms/platform.py` | Renamed to `src/control/forms/source.py`. `PlatformForm` → `SourceForm`. Field list, validation, and `_collect_parameters` logic unchanged. |
| `src/control/forms/__init__.py` | Import/`__all__` updated to `SourceForm`. |
| `src/control/admin.py` | `PlatformAdmin` → `SourceAdmin`; `form = SourceForm`; import updated. `list_display`/`fieldsets`/actions unchanged. |
| `src/control/management/commands/seed_platforms.py` | Renamed to `seed_sources.py`. Same `PLATFORMS` data, same idempotent upsert-by-domain behavior — only the command's own name and its `help` text change. |
| New migration | A hand-written `migrations.RenameModel(old_name="Platform", new_name="Source")` — see "Migration approach" below. Numbered after the current latest (`0005`). |
| `src/project/settings.py` | `UNFOLD["SIDEBAR"]["navigation"]`: label "Площадки" → "Источники"; `reverse_lazy("admin:control_platform_changelist")` → `reverse_lazy("admin:control_source_changelist")`. |
| `Makefile` | `.PHONY` entry and target `platforms` → `sources`, calling `seed_sources`. |
| `README.md`, `README.ru.md` | Prose and the command-table row updated to the new names/URL. |
| `CLAUDE.md` | D17 edited in place (this is a rename, not a reversal of the decision's substance, so it does not get the "superseded" treatment D19 got) to say `Source` instead of `Platform`. Repo map's `models.py`/`forms/` lines updated. |
| `tests/test_platforms.py` | Renamed to `tests/test_sources.py`. Every `Platform`/`PlatformForm` reference and every `reverse("admin:control_platform_...")` call updated to the `source` equivalents. Test *behavior* (what's asserted) is unchanged — only names. |

## What does not change

- `docs/architecture/adr/0002-tender-site-collectors.md` — left as the historical record of what
  was decided on 2026-07-29. It still says `Platform`; that was true then. No new ADR is needed
  for a rename (unlike ADR 0003, which recorded an actual reversal of a guarantee).
- `docs/spec/` — frozen, never edited.
- Prose in `collectors/engine/` that uses "trading platform" in the ordinary business sense (an
  auction site) — that phrase remains accurate regardless of what the Django admin proxy model is
  called, and is outside the `control` package entirely.
- The old migration `control/migrations/0003_platform.py` — its filename and content are history;
  migrations are never renamed or edited after the fact. `0004_lot.py`'s dependency reference to
  `('control', '0003_platform')` also stays as-is — it names a migration file, not the model.
- The manager's filter, the form's field set, and every behavioral test assertion.

## Migration approach

Django's non-interactive `makemigrations` cannot ask "did you rename Platform to Source?" — run
without a human answering that prompt, its autodetector emits `DeleteModel` + `CreateModel`
instead of a rename. For a proxy model that is a no-op against the actual database table, but it
recreates the model's `ContentType` row, which would silently orphan:

- the `control.*_platform` permission rows already granted to the `petr` user (bulk-granted by
  `content_type__app_label`, so a fresh `sync` would eventually cover a recreated `control.*_source`
  permission — but the *old* rows and anything referencing them, such as `LogEntry` history, do not
  automatically migrate);
- any admin `LogEntry` rows already recorded against the `Platform` content type.

The migration is therefore hand-written as a single `migrations.RenameModel` operation, which
Django's contenttypes framework recognizes and updates the existing `ContentType` row in place
(via `RenameContentType`) rather than replacing it. No permission or history data is lost.

## Verification

- `make verify` (check, migrations check, ruff, `lint-imports`, `pytest`) must stay green.
- After migrating, confirm in a shell that the `ContentType` for `control.source` has the *same*
  primary key it had as `control.platform` (proves the rename preserved identity rather than
  recreating the row), and that `petr`'s permissions still resolve correctly under the new
  codenames.
- Manually load `/admin/control/source/` and confirm the sidebar label, the per-field form, and
  the existing 33 rows all still work exactly as before under the new URL.
