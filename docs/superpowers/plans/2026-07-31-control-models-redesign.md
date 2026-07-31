# Control Models Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the `control` app's data model per `docs/superpowers/specs/2026-07-31-control-models-redesign-design.md` — remove revision tracking, dashboard cache columns, soft-delete flags, unused schedule policy variants, and the dynamically-generated `Config` parameter form — then retire the five ADRs and `CLAUDE.md` references that described the old shape.

**Architecture:** No new components. This is a subtractive refactor of existing `control` models, forms, admin, services, the scheduler, and seed commands, plus one cross-cutting rename (`listing_path` → `start_url`) that ripples into `collectors.schemas.tender` and `collectors.runners.tender_site`. `execution`'s claim/lease queue and the collector engine itself are untouched. The database has no production data, so migrations are reset to a fresh baseline rather than data-migrated.

**Tech Stack:** Django 5.2, PostgreSQL, pytest-django, `uv`.

---

## Before you start

Read `docs/superpowers/specs/2026-07-31-control-models-redesign-design.md` in full — it is the source of truth for *what* changes and *why*. This plan is the *how*.

Run `uv run pytest -q` once before touching anything and confirm it passes, so later failures are attributable to this work.

```bash
uv run pytest -q
```

---

### Task 1: Rewrite `control/models.py`

**Files:**
- Modify: `src/control/models.py`

This is one file, one coherent edit — do all four model changes together, then move on. Tests are not run yet (the DB schema won't match until Task 2 regenerates migrations); just get the file correct.

- [ ] **Step 1: Remove `OverlapPolicy` and `CatchupPolicy`**

Delete these two classes entirely (currently around line 53-62):

```python
class OverlapPolicy(models.TextChoices):
    SKIP = "skip", "Пропустить — не запускать, пока идёт предыдущий запуск"
    QUEUE = "queue", "В очередь — поставить в очередь за текущим запуском"
    ALLOW = "allow", "Разрешить — запускать параллельно"


class CatchupPolicy(models.TextChoices):
    FIRE_MISSED = "fire_missed", "Догнать — поставить каждый пропущенный запуск"
    SKIP_TO_NOW = "skip_to_now", "Только последний — пропустить всё, кроме ближайшего к текущему"
```

- [ ] **Step 2: Rewrite the `Source` model**

Replace the entire `Source` class with:

```python
class Source(models.Model):
    """A site, authored: domain, start URL and TLS quirks — the identity a crawl needs before
    behaviour (which collector, how many pages, how many requests at once) enters the picture.

    Referenced by `Config.source`, not the other way around: one `Source` can back many named
    `Config` profiles (`default`, `full`, `fast`, ...), each with its own collector and its own
    behavioural parameters. `effective_parameters` at enqueue merges this Source's fields — filtered
    to the ones the profile's collector actually declares — with the profile's own `parameters`
    (see `Config.raw_parameters`); the two key sets are disjoint by construction.

    `Config.source` uses `on_delete=PROTECT` so a referenced Source cannot be removed out from
    under the profiles that point at it — deletion is real (there is no soft-delete flag here),
    it is simply refused while anything still depends on the row.
    """

    #: Keys inside `tls_options` that double as collector parameters — rare, site-specific
    #: quirks (an extra CA cert, skipping verification, and whatever else turns out to be needed)
    #: bagged into one JSON field instead of one column each.
    TLS_OPTION_FIELDS = ("extra_ca_cert", "skip_tls_verify")

    #: Every Source field that can double as a collector parameter — a plain attribute (`domain`,
    #: `start_url`) or a key inside `tls_options`. Excluded, for that reason, from the dynamic
    #: per-profile fields `ConfigForm` would otherwise build: a name must not be editable in two
    #: places at once.
    PARAM_FIELDS = ("domain", "start_url", *TLS_OPTION_FIELDS)

    name = models.CharField("Название", max_length=200)
    domain = models.URLField(
        "Домен",
        max_length=200,
        help_text="Корень сайта площадки со схемой и без завершающего слэша, например "
        "https://bankrupt.centerr.ru.",
    )
    start_url = models.CharField(
        "Путь к листингу",
        max_length=200,
        blank=True,
        default="",
        help_text="Пусто — путь по умолчанию для движка того профиля, который обходит этот сайт.",
    )
    tls_options = models.JSONField(
        "TLS-настройки",
        default=dict,
        blank=True,
        help_text="Редкие костыли под конкретный сайт: доп. сертификат, отключение проверки "
        "TLS и подобное.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Источник"
        verbose_name_plural = "Источники"

    def __str__(self) -> str:
        return f"{self.name} ({self.domain})"

    def param_value(self, name: str) -> Any:
        """One Source-supplied value, addressed by the name a collector's schema would use."""
        if name in self.TLS_OPTION_FIELDS:
            return self.tls_options.get(name, "")
        return getattr(self, name)
```

- [ ] **Step 3: Rewrite the `Config` model**

Replace the entire `Config` class with:

```python
class Config(models.Model):
    """The primary business object: *what to collect*, authored by a human.

    Editable at any time. Editing never disturbs a running Job — the Job carries its own snapshot.
    """

    name = models.CharField("Название", max_length=200)
    source = models.ForeignKey(
        Source,
        verbose_name="Источник",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="configs",
        help_text="Сайт, чьи домен/путь листинга/TLS-настройки объединяются с параметрами этого "
        "профиля при постановке в очередь. Пусто — у сборщика нет понятия сайта.",
    )
    collector_key = models.CharField(
        "Сборщик",
        max_length=100,
        db_index=True,
        help_text="Ссылка по ключу. Конкретная версия фиксируется в момент постановки "
        "в очередь, а не здесь.",
    )
    parameters = models.JSONField(
        "Параметры",
        default=dict,
        blank=True,
        help_text="Исходные параметры как их задал человек. При постановке в очередь они "
        "проверяются по схеме сборщика, и уже результат попадает в снимок задачи.",
    )
    enabled = models.BooleanField("Включена", default=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Владелец",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_configs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_configs",
        editable=False,
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Конфигурация"
        verbose_name_plural = "Конфигурации"
        indexes = [
            models.Index(fields=["enabled"]),
            models.Index(fields=["collector_key"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_runnable(self) -> bool:
        """The enqueue precondition that lives on the Config itself (§6)."""
        return self.enabled

    def raw_parameters(self) -> dict[str, Any]:
        """`parameters`, extended with whatever `source` provides.

        The two key sets are disjoint by construction — a `Source` field and a profile parameter
        never share a name — so this is a plain union, never an override. Source fields are
        filtered to the ones the collector's schema actually declares, so attaching a `source` to
        a collector that knows nothing about, say, `start_url` never leaks it through as an
        unknown parameter. `enqueue`, the admin's resolved-parameters preview and the authoring
        forms all resolve against this one method, so they cannot drift apart.
        """
        if self.source_id is None:
            return dict(self.parameters)
        try:
            descriptor = schemas.get_collector(self.collector_key)
        except schemas.UnknownCollector:
            return dict(self.parameters)

        merged: dict[str, Any] = {}
        for param_name in Source.PARAM_FIELDS:
            spec = descriptor.param(param_name)
            if spec is None:
                continue
            value = self.source.param_value(param_name)
            if not spec.required and value == "":
                continue
            merged[param_name] = value
        merged.update(self.parameters)
        return merged
```

Note what disappeared: `archived`, `tags`, `revision`, `last_status`, `last_run_at`, `last_job_id`,
`REVISIONED_FIELDS`, the custom `save()`/`from_db()` override, `_revisioned_changed()`,
`record_job_outcome()`, `forget_job_outcomes()`. `Config` is now a plain Django model with no
override at all.

- [ ] **Step 4: Rewrite the `Schedule` model's policy field**

In the `Schedule` class, replace the `overlap_policy` and `catchup_policy` fields:

```python
    overlap_policy = models.CharField(
        "При наложении",
        max_length=16,
        choices=OverlapPolicy.choices,
        default=OverlapPolicy.SKIP,
        help_text="Что делать, если предыдущий запуск этой конфигурации ещё не завершён.",
    )
    catchup_policy = models.CharField(
        "После простоя",
        max_length=16,
        choices=CatchupPolicy.choices,
        default=CatchupPolicy.SKIP_TO_NOW,
        help_text="Что делать с запусками, пропущенными пока система была недоступна.",
    )
```

with:

```python
    skip_if_running = models.BooleanField(
        "Пропускать, если ещё выполняется",
        default=True,
        help_text="Не запускать новый экземпляр, пока предыдущий запуск этой конфигурации не "
        "завершён. Пропущенное срабатывание не догоняется — считается только ближайшее к "
        "текущему моменту.",
    )
```

Leave every other `Schedule` field (`config`, `cron`, `timezone`, `enabled`, `last_fired_at`,
`created_at`/`updated_at`) and `clean()` exactly as they are.

- [ ] **Step 5: Remove `Job.config_revision`**

In `Job.SNAPSHOT_FIELDS`, remove the entry:

```python
    SNAPSHOT_FIELDS = (
        "collector_key",
        "effective_parameters",
        "config_id",
        "config_revision",
    )
```

becomes:

```python
    SNAPSHOT_FIELDS = (
        "collector_key",
        "effective_parameters",
        "config_id",
    )
```

Delete the field definition:

```python
    config_revision = models.PositiveIntegerField("Ревизия конфигурации", default=0, editable=False)
```

Leave every other part of `Job` (the snapshot fields that remain, origin, claim/lease, outcome,
`save()`/`from_db()`/the two `_assert_*` guards) untouched — they were confirmed accurate during
the design review.

- [ ] **Step 6: Commit**

```bash
git add src/control/models.py
git commit -m "refactor: simplify control models (drop revision, soft-delete, unused schedule policies)"
```

---

### Task 2: Reset migrations to a fresh baseline

**Files:**
- Delete: `src/control/migrations/0001_initial.py` through `0008_split_domain_into_source.py`
- Create: `src/control/migrations/0001_initial.py` (regenerated)

There is no production data to preserve (confirmed with the user), so this resets the migration
history rather than writing eight incremental ALTER migrations for a model that has not shipped.

- [ ] **Step 1: Delete the old migrations**

```bash
rm src/control/migrations/0001_initial.py \
   src/control/migrations/0002_alter_collector_options_alter_config_options_and_more.py \
   src/control/migrations/0003_platform.py \
   src/control/migrations/0004_lot.py \
   src/control/migrations/0005_remove_job_collector_version_and_more.py \
   src/control/migrations/0006_rename_platform_to_source.py \
   src/control/migrations/0007_source_becomes_a_table.py \
   src/control/migrations/0008_split_domain_into_source.py
```

Keep `src/control/migrations/__init__.py`.

- [ ] **Step 2: Regenerate a single initial migration**

```bash
uv run python src/manage.py makemigrations control
```

Expected: creates a new `src/control/migrations/0001_initial.py` covering `Collector`, `Source`,
`Config`, `Lot`, `Schedule`, `Job` as they now stand in `models.py` (`Lot` is untouched — it comes
along unchanged).

- [ ] **Step 3: Verify the migration is consistent**

```bash
uv run python src/manage.py makemigrations --check --dry-run
```

Expected: `No changes detected` — if it reports pending changes, a field edit in Task 1 was missed.

- [ ] **Step 4: Drop and recreate the local dev database, then apply**

```bash
uv run python src/manage.py migrate
```

(If running against the compose Postgres and the old schema is still there from before this
refactor, drop and recreate the database first — `make db` or the project's usual local-Postgres
reset, per the README. There is no data worth preserving.)

- [ ] **Step 5: Commit**

```bash
git add src/control/migrations/
git commit -m "refactor: reset control migrations to a single fresh baseline"
```

---

### Task 3: Update test fixtures (`tests/conftest.py`)

**Files:**
- Modify: `tests/conftest.py`

Nothing can run yet until fixtures stop passing a removed field.

- [ ] **Step 1: Drop `archived` from `make_config`'s defaults**

```python
@pytest.fixture
def make_config(db):
    def _make(**overrides) -> Config:
        defaults = {
            "name": "cfg",
            "collector_key": "example_api",
            "parameters": dict(VALID_PARAMS),
            "enabled": True,
        }
        return Config.objects.create(**{**defaults, **overrides})

    return _make
```

- [ ] **Step 2: Run the fixture-only smoke check**

```bash
uv run pytest tests/test_models.py -x -q
```

Expected: fails on assertions inside tests that reference removed fields (`revision`,
`last_status`, ...) — that is Task 8's job, not this one. Confirm the failures are exactly those
(no `TypeError`/`AttributeError` about the fixture itself) before moving on.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: drop archived from the make_config fixture"
```

---

### Task 4: Propagate the `listing_path` → `start_url` rename into `collectors`

**Files:**
- Modify: `src/collectors/schemas/tender.py`
- Modify: `src/collectors/runners/tender_site.py`
- Test: `tests/unit/test_tender_schemas.py`

`Source.start_url` merges into a Job's `effective_parameters` by key-name match against the
collector's own schema (same mechanism as before, see `Config.raw_parameters`). Since the field is
renamed, the tender collectors' schema must declare a parameter named `start_url`, not
`listing_path`, or the merge silently stops supplying it.

- [ ] **Step 1: Update the failing test first**

In `tests/unit/test_tender_schemas.py`, change:

```python
    assert effective["listing_path"] == DEFAULT_LISTING_PATHS[engine]
```

to:

```python
    assert effective["start_url"] == DEFAULT_LISTING_PATHS[engine]
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest tests/unit/test_tender_schemas.py -x -q
```

Expected: `KeyError: 'start_url'`.

- [ ] **Step 3: Rename the `ParamSpec` in `collectors/schemas/tender.py`**

In `_params_for`, change:

```python
    listing_path = ParamSpec(
        name="listing_path",
        kind="str",
        default=DEFAULT_LISTING_PATHS[engine],
        description=f"Путь к листингу относительно домена. По умолчанию "
        f"{DEFAULT_LISTING_PATHS[engine]!r} — менять только тем сайтам семейства, "
        f"которые отдают листинг по другому адресу.",
    )
```

to:

```python
    start_url = ParamSpec(
        name="start_url",
        kind="str",
        default=DEFAULT_LISTING_PATHS[engine],
        description=f"Путь к листингу относительно домена. По умолчанию "
        f"{DEFAULT_LISTING_PATHS[engine]!r} — менять только тем сайтам семейства, "
        f"которые отдают листинг по другому адресу.",
    )
```

and update the tuple it is placed into:

```python
    common = (
        _DOMAIN,
        start_url,
        _MAX_PAGES,
        _ONLY_ACTIVE,
        _CONCURRENCY,
        _EXTRA_CA_CERT,
        _SKIP_TLS_VERIFY,
    )
```

- [ ] **Step 4: Run the schema test again**

```bash
uv run pytest tests/unit/test_tender_schemas.py -x -q
```

Expected: PASS.

- [ ] **Step 5: Update the runner to read the renamed key**

In `src/collectors/runners/tender_site.py`, `TenderSiteRunner.run()`, change:

```python
            spec = SiteSpec(
                engine=self.engine,
                domain=str(params["domain"]),
                listing_path=str(params.get("listing_path") or ""),
                extra_ca_cert=str(params.get("extra_ca_cert") or ""),
                skip_tls_verify=bool(params.get("skip_tls_verify")),
            )
```

to:

```python
            spec = SiteSpec(
                engine=self.engine,
                domain=str(params["domain"]),
                listing_path=str(params.get("start_url") or ""),
                extra_ca_cert=str(params.get("extra_ca_cert") or ""),
                skip_tls_verify=bool(params.get("skip_tls_verify")),
            )
```

(`SiteSpec`'s own field stays named `listing_path` — that dataclass lives in
`collectors.engine.core.spider` and is out of scope; only the snapshot parameter key that feeds it
changes.)

- [ ] **Step 6: Run the collectors unit suite**

```bash
uv run pytest tests/unit -x -q
```

Expected: PASS. This also covers `tests/unit/test_tender_runner.py`, which does not reference
`listing_path` directly.

- [ ] **Step 7: Commit**

```bash
git add src/collectors/schemas/tender.py src/collectors/runners/tender_site.py tests/unit/test_tender_schemas.py
git commit -m "refactor: rename tender collectors' listing_path parameter to start_url"
```

---

### Task 5: Update `control/services/enqueue.py`

**Files:**
- Modify: `src/control/services/enqueue.py`

- [ ] **Step 1: Remove the `archived` precondition**

Delete:

```python
    if config.archived:
        raise EnqueueRefused(
            "config_archived", f"Конфигурация {config.name!r} в архиве — запуск невозможен."
        )
```

leaving only the `enabled` check under "precondition 1":

```python
    # --- precondition 1: the Config is allowed to run at all --------------------------
    if not config.enabled:
        raise EnqueueRefused(
            "config_disabled", f"Конфигурация {config.name!r} отключена — запуск невозможен."
        )
```

- [ ] **Step 2: Drop `config_revision` from both `Job.objects.create(...)` calls**

In `enqueue()`, remove the line `config_revision=config.revision,` from the snapshot section.

In `_record_invalid_config_job()`, remove the same line.

- [ ] **Step 3: Remove the `Config.record_job_outcome` call**

In `_record_invalid_config_job()`, delete:

```python
    # This Job is born terminal, so nothing downstream will ever refresh the cache columns.
    Config.record_job_outcome(
        config_id=config.pk, job_id=job.pk, status=job.status, finished_at=now
    )
```

The function now ends with `return job` right after the `Job.objects.create(...)` call. Also drop
the now-unused `now = timezone.now()` binding's only-other-use check — `now` is still used for
`started_at`/`finished_at`/`available_at` above it, so keep that line; only the `record_job_outcome`
call and its comment are removed.

- [ ] **Step 4: Run the enqueue suite (expect failures — Task 8 fixes the test file itself)**

```bash
uv run pytest tests/test_enqueue.py -q
```

Expected: some failures referencing `config.archived`, `job.config_revision`,
`config.last_status` — confirm they are all in `tests/test_enqueue.py` itself, not in
`enqueue.py`. Leave the test file for Task 8.

- [ ] **Step 5: Commit**

```bash
git add src/control/services/enqueue.py
git commit -m "refactor: drop archived precondition and revision snapshotting from enqueue"
```

---

### Task 6: Update `execution/worker/loop.py`

**Files:**
- Modify: `src/execution/worker/loop.py`

- [ ] **Step 1: Remove the cache-column refresh from `_finish()`**

Replace:

```python
    def _finish(self, job: Job, result: RunResult) -> None:
        written = finish_job(
            job_id=job.pk,
            worker_id=self.worker_id,
            status=result.status,
            result=result.result,
            metrics=result.metrics,
            structured_error=result.structured_error,
        )
        if not written:
            # Lost the claim between running and finishing. The reclaiming executor owns the
            # outcome; the cache columns must not be touched either.
            return

        finished = Job.objects.values_list("finished_at", flat=True).get(pk=job.pk)
        Config.record_job_outcome(
            config_id=job.config_id, job_id=job.pk, status=result.status, finished_at=finished
        )
        logger.info(
            "job %s: %s (%s)",
            job.pk,
            result.status,
            ", ".join(f"{k}={v}" for k, v in sorted(result.metrics.items())) or "no metrics",
        )
```

with:

```python
    def _finish(self, job: Job, result: RunResult) -> None:
        written = finish_job(
            job_id=job.pk,
            worker_id=self.worker_id,
            status=result.status,
            result=result.result,
            metrics=result.metrics,
            structured_error=result.structured_error,
        )
        if not written:
            # Lost the claim between running and finishing. The reclaiming executor owns the
            # outcome.
            return

        logger.info(
            "job %s: %s (%s)",
            job.pk,
            result.status,
            ", ".join(f"{k}={v}" for k, v in sorted(result.metrics.items())) or "no metrics",
        )
```

- [ ] **Step 2: Drop the now-unused `Config` import**

Change:

```python
from control.models import Config, Job
```

to:

```python
from control.models import Job
```

- [ ] **Step 3: Run the worker suite**

```bash
uv run pytest tests/test_worker.py tests/test_lot_sink.py -x -q
```

Expected: PASS (neither file asserted on the cache columns per the earlier grep).

- [ ] **Step 4: Commit**

```bash
git add src/execution/worker/loop.py
git commit -m "refactor: stop refreshing the removed Config dashboard cache columns from the worker"
```

---

### Task 7: Simplify `execution/scheduler/occurrences.py`

**Files:**
- Modify: `src/execution/scheduler/occurrences.py`
- Test: `tests/test_scheduler.py` (the `TestDueOccurrences` class only — the rest is Task 9)

With `catchup_policy` gone, the scheduler always keeps only the most recent due occurrence.

- [ ] **Step 1: Rewrite `TestDueOccurrences` first**

Replace the whole class in `tests/test_scheduler.py`:

```python
class TestDueOccurrences:
    """Pure cron arithmetic — no enqueue, no transaction."""

    def test_a_schedule_that_never_fired_yields_nothing(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *")
        assert schedule.last_fired_at is None
        assert due_occurrences(schedule, now=at(12)) == []

    def test_keeps_only_the_latest_occurrence(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *", last_fired_at=at(9))
        assert due_occurrences(schedule, now=at(12, 30)) == [at(12)]

    def test_nothing_is_due_before_the_next_occurrence(self, config, make_schedule):
        schedule = make_schedule(config, cron="0 * * * *", last_fired_at=at(12))
        assert due_occurrences(schedule, now=at(12, 30)) == []

    def test_the_cron_is_evaluated_in_the_schedules_timezone(self, config, make_schedule):
        """02:00 Europe/Berlin in March is 01:00 UTC."""
        schedule = make_schedule(
            config,
            cron="0 2 * * *",
            timezone="Europe/Berlin",
            last_fired_at=at(0, day=5),
        )
        occurrences = due_occurrences(schedule, now=at(12, day=5))
        assert [o.astimezone(UTC) for o in occurrences] == [at(1, day=5)]

    def test_catch_up_is_capped(self, config, make_schedule):
        schedule = make_schedule(config, cron="* * * * *", last_fired_at=at(0))
        assert due_occurrences(schedule, now=at(12), max_catchup=10) == [at(0, 10)]
```

(This drops `catchup_policy=CatchupPolicy.FIRE_MISSED`/`SKIP_TO_NOW` from every call — the
behavior is no longer a choice.)

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest tests/test_scheduler.py::TestDueOccurrences -x -q
```

Expected: fails — `due_occurrences` still branches on `schedule.catchup_policy`, which no longer
exists on the model after Task 1's `Schedule` rewrite (`AttributeError`).

- [ ] **Step 3: Rewrite `due_occurrences`**

Replace the whole function body in `src/execution/scheduler/occurrences.py`:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from control.models import Schedule

#: Hard stop on how far a single tick walks forward looking for the latest due occurrence. After a
#: long outage this keeps one tick from silently absorbing an unbounded amount of missed history —
#: hitting the cap just means the next tick picks up from where this one stopped.
DEFAULT_MAX_CATCHUP = 100


def due_occurrences(
    schedule: Schedule,
    *,
    now: datetime,
    max_catchup: int = DEFAULT_MAX_CATCHUP,
) -> list[datetime]:
    """The single most recent occurrence of `schedule` still due, if any.

    Returns a list of zero or one UTC datetimes — a list, not `datetime | None`, so callers do not
    need a separate branch for "nothing due" versus "one thing due".

    A schedule that has never fired starts from *now*: `last_fired_at is None` means "no history",
    not "the epoch", and walking a cron back to 1970 is never what anyone wanted. The caller
    stamps `last_fired_at` on that first tick. Missed occurrences before the latest one are not
    caught up — only the most recent still means anything.
    """
    if schedule.last_fired_at is None:
        return []

    tz = ZoneInfo(schedule.timezone)
    cursor = croniter(schedule.cron, schedule.last_fired_at.astimezone(tz))
    horizon = now.astimezone(tz)

    latest: datetime | None = None
    for _ in range(max_catchup):
        candidate = cursor.get_next(datetime)
        if candidate > horizon:
            break
        latest = candidate

    if latest is None:
        return []
    return [latest.astimezone(now.tzinfo)]
```

- [ ] **Step 4: Run the test again**

```bash
uv run pytest tests/test_scheduler.py::TestDueOccurrences -x -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/execution/scheduler/occurrences.py tests/test_scheduler.py
git commit -m "refactor: always keep only the latest due occurrence, drop catchup_policy"
```

---

### Task 8: Update `execution/scheduler/runtime.py`

**Files:**
- Modify: `src/execution/scheduler/runtime.py`
- Test: `tests/test_scheduler.py` (`TestOverlapPolicy` → `TestSkipIfRunning`, plus every other
  `overlap_policy=`/`catchup_policy=` call site in the file)

- [ ] **Step 1: Rewrite the remaining scheduler tests first**

In `tests/test_scheduler.py`, change the import block:

```python
from control.models import (
    CatchupPolicy,
    Config,
    Job,
    JobOrigin,
    JobStatus,
    OverlapPolicy,
    Schedule,
)
```

to:

```python
from control.models import Config, Job, JobOrigin, JobStatus, Schedule
```

Replace `TestOverlapPolicy` with:

```python
class TestSkipIfRunning:
    @pytest.fixture
    def busy_config(self, config) -> Config:
        enqueue(config)  # a pending Job — an active run for this Config
        return config

    def test_drops_the_occurrence_but_still_advances(self, busy_config, make_schedule):
        schedule = make_schedule(
            busy_config, cron="0 * * * *", skip_if_running=True, last_fired_at=at(9)
        )

        report = tick(now=at(10, 30))

        assert report.skipped_overlap == 1
        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 0
        assert Schedule.objects.get(pk=schedule.pk).last_fired_at == at(10)

    def test_false_enqueues_anyway(self, busy_config, make_schedule):
        make_schedule(
            busy_config, cron="0 * * * *", skip_if_running=False, last_fired_at=at(9)
        )

        tick(now=at(10, 30))

        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 1

    def test_only_applies_while_a_run_is_active(self, config, make_schedule):
        job = enqueue(config)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.SUCCEEDED)
        make_schedule(
            config, cron="0 * * * *", skip_if_running=True, last_fired_at=at(9)
        )

        tick(now=at(10, 30))

        assert Job.objects.filter(origin=JobOrigin.SCHEDULE).count() == 1
```

In `TestIdempotency.test_a_crash_between_insert_and_advance_cannot_double_enqueue`, change:

```python
        schedule = make_schedule(
            config, cron="0 * * * *", overlap_policy=OverlapPolicy.ALLOW, last_fired_at=at(9)
        )
```

to:

```python
        schedule = make_schedule(
            config, cron="0 * * * *", skip_if_running=False, last_fired_at=at(9)
        )
```

(and update the docstring's `overlap_policy=allow` mention to `skip_if_running=False`.)

In `TestIdempotency.test_repeated_ticks_over_the_same_window_stay_at_one_job_per_occurrence`,
change:

```python
        make_schedule(
            config,
            cron="0 * * * *",
            overlap_policy=OverlapPolicy.ALLOW,
            catchup_policy=CatchupPolicy.FIRE_MISSED,
            last_fired_at=at(9),
        )

        for _ in range(5):
            tick(now=at(12, 30))

        fire_times = sorted(Job.objects.values_list("fire_time", flat=True))
        assert fire_times == [at(10), at(11), at(12)]
```

to (catch-up is gone, so five ticks converge on the one latest occurrence, not three):

```python
        make_schedule(config, cron="0 * * * *", skip_if_running=False, last_fired_at=at(9))

        for _ in range(5):
            tick(now=at(12, 30))

        assert list(Job.objects.values_list("fire_time", flat=True)) == [at(12)]
```

Delete the whole `TestCatchupThroughTick` class — both its tests (`test_fire_missed_enqueues_every_occurrence`,
`test_skip_to_now_enqueues_only_the_latest`) asserted a policy choice that no longer exists; the
single remaining behavior is already covered by `TestDueOccurrences.test_keeps_only_the_latest_occurrence`
(Task 7) and `TestTick.test_enqueues_a_due_occurrence_and_advances_the_cursor`.

- [ ] **Step 2: Run it to confirm the new tests fail**

```bash
uv run pytest tests/test_scheduler.py -x -q
```

Expected: fails — `Schedule(...)` rejects `skip_if_running` as an unexpected keyword until the
model change lands (it already landed in Task 1, so this should actually fail on
`runtime.py` still reading `schedule.overlap_policy`, an `AttributeError`). Confirm the failure
is in `runtime.py`, not in the test file itself.

- [ ] **Step 3: Update `runtime.py`**

Change the import:

```python
from control.models import Config, Job, JobOrigin, JobStatus, OverlapPolicy, Schedule
```

to:

```python
from control.models import Config, Job, JobOrigin, JobStatus, Schedule
```

Change the overlap check in `_fire()`:

```python
    if schedule.overlap_policy == OverlapPolicy.SKIP and _has_active_job(config):
```

to:

```python
    if schedule.skip_if_running and _has_active_job(config):
```

Update the comment two lines above it, which currently reads:

```python
    # Only `skip` changes what the scheduler does. `queue` and `allow` both enqueue — under
    # Option A they are indistinguishable at runtime, because keeping a queued run from
    # overlapping needs the per-stream claim predicate from Option B. See the "Known limitation"
    # note in CLAUDE.md before treating `queue` as mutual exclusion.
```

to:

```python
    # `skip_if_running=False` is not a queueing guarantee — it just does not check for an
    # active run before enqueuing. Preventing two runs of the same Config from ever overlapping
    # would need a per-stream claim predicate this queue does not have.
```

- [ ] **Step 4: Run the full scheduler suite**

```bash
uv run pytest tests/test_scheduler.py -x -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/execution/scheduler/runtime.py tests/test_scheduler.py
git commit -m "refactor: collapse Schedule.overlap_policy to a boolean skip_if_running"
```

---

### Task 9: Update `control/forms/source.py`

**Files:**
- Modify: `src/control/forms/source.py`
- Test: `tests/test_sources.py` (`TestSourceForm` only — the rest of the file is Task 13)

`extra_ca_cert` and `skip_tls_verify` stay two separate, familiar form fields (a dropdown and a
checkbox) even though they now live inside `Source.tls_options` in the database — only the storage
shape changed, not what the person filling the form sees.

- [ ] **Step 1: Update `TestSourceForm` first**

In `tests/test_sources.py`, change `_source_form_data`:

```python
def _source_form_data(**overrides):
    data = {
        "name": "Центр реализации",
        "domain": "https://bankrupt.centerr.ru",
        "start_url": "",
        "extra_ca_cert": "",
        "skip_tls_verify": False,
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}
```

Update `TestSourceForm`:

```python
class TestSourceForm:
    def test_a_source_is_just_site_identity(self):
        form = SourceForm(data=_source_form_data())
        assert form.is_valid(), form.errors
        source = form.save()

        assert source.domain == "https://bankrupt.centerr.ru"
        assert source.start_url == ""
        assert source.tls_options.get("skip_tls_verify") is False

    def test_a_missing_domain_is_refused(self):
        form = SourceForm(data=_source_form_data(domain=""))
        assert not form.is_valid()
        assert "domain" in form.errors

    def test_a_per_site_start_url_is_stored(self):
        form = SourceForm(
            data=_source_form_data(
                name="Объединённые системы торгов",
                domain="https://sistematorg.com",
                start_url="tradelist.php",
            )
        )
        assert form.is_valid(), form.errors
        assert form.save().start_url == "tradelist.php"

    def test_editing_shows_what_is_authored(self):
        source = Source.objects.create(
            name="Промконсалт", domain="https://promkonsalt.ru", start_url="tradelist.php"
        )
        form = SourceForm(instance=source)

        assert form.initial["domain"] == "https://promkonsalt.ru"
        assert form.initial["start_url"] == "tradelist.php"

    def test_extra_ca_cert_offers_the_shipped_certificates(self):
        choices = {value for value, _label in SourceForm().fields["extra_ca_cert"].choices}
        assert "" in choices  # "— обычный набор корневых —"
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest tests/test_sources.py::TestSourceForm -x -q
```

Expected: fails — `SourceForm` still declares `listing_path` and has no knowledge of
`tls_options`.

- [ ] **Step 3: Rewrite `SourceForm`**

Replace the whole file:

```python
"""Authoring form for a `Source` — a site's identity: domain, start URL, TLS quirks.

Behaviour (which collector, `max_pages`, `fetch_details`, ...) belongs to a `Config` profile that
references this `Source`, not to the `Source` itself — see `control.forms.ConfigForm` for that
side. `extra_ca_cert`/`skip_tls_verify` are declared here as their own fields even though they are
stored together inside `Source.tls_options`: the split is a database-shape decision, not something
the person filling the form needs to see.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors.schemas.tender import DEFAULT_LISTING_PATHS, available_certs
from control.models import Source


class SourceForm(forms.ModelForm):
    extra_ca_cert = forms.ChoiceField(
        label="Доп. сертификат",
        required=False,
        help_text="Имя PEM-файла из collectors/certs с промежуточным сертификатом, который сайт "
        "не отдаёт сам. Пусто — обычный набор корневых сертификатов.",
    )
    skip_tls_verify = forms.BooleanField(
        label="Не проверять сертификат",
        required=False,
        help_text="Полностью отключить проверку сертификата для этого сайта.",
    )
    start_url = forms.CharField(
        label="Путь к листингу",
        max_length=200,
        required=False,
        help_text="Пусто — путь по умолчанию для движка того профиля, который обходит этот сайт: "
        + ", ".join(f"{engine} → {path}" for engine, path in DEFAULT_LISTING_PATHS.items()),
    )

    class Meta:
        model = Source
        fields = ["name", "domain", "start_url"]
        labels = {"name": "Название источника"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["extra_ca_cert"].choices = [("", "— обычный набор корневых —")] + [
            (name, name) for name in available_certs()
        ]
        if self.instance.pk:
            self.fields["extra_ca_cert"].initial = self.instance.tls_options.get(
                "extra_ca_cert", ""
            )
            self.fields["skip_tls_verify"].initial = self.instance.tls_options.get(
                "skip_tls_verify", False
            )

    def save(self, commit: bool = True) -> Source:
        source = super().save(commit=False)
        source.tls_options = {
            "extra_ca_cert": self.cleaned_data.get("extra_ca_cert", ""),
            "skip_tls_verify": self.cleaned_data.get("skip_tls_verify", False),
        }
        if commit:
            source.save()
        return source
```

- [ ] **Step 4: Run the test again**

```bash
uv run pytest tests/test_sources.py::TestSourceForm -x -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/control/forms/source.py tests/test_sources.py
git commit -m "refactor: SourceForm writes tls_options, keeps the two-field TLS UX"
```

---

### Task 10: Simplify `control/forms/config.py`

**Files:**
- Modify: `src/control/forms/config.py`
- Test: `tests/test_sources.py` (`TestConfigFormWithSource` — the rest of the file is Task 13)

`parameters` becomes a single JSON textarea instead of one Django field per `ParamSpec`.

- [ ] **Step 1: Update the dependent tests first**

In `tests/test_sources.py`, `TestConfigFormWithSource`, every POST payload currently includes
`"tags": "[]"` (a removed field) and expects one form field per parameter. Replace the whole
class:

```python
class TestConfigFormWithSource:
    def test_parameters_are_a_single_json_field(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        form = ConfigForm(
            data={
                "name": "Торги82 — fast",
                "collector_key": "tender_kendo",
                "source": source.pk,
                "parameters": '{"max_pages": 0, "only_active": true, "concurrency": 1}',
                "enabled": "on",
            }
        )
        assert form.is_valid(), form.errors
        # domain/start_url/... are the source's fields — not re-asked here, and not part of
        # the parameters JSON either.
        assert "domain" not in form.fields

        profile = form.save()
        assert profile.parameters == {"max_pages": 0, "only_active": True, "concurrency": 1}
        assert profile.raw_parameters()["domain"] == "https://lot.torgi82.ru"

    def test_a_bad_parameters_json_is_reported_on_the_field(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        form = ConfigForm(
            data={
                "name": "Торги82 — fast",
                "collector_key": "tender_kendo",
                "source": source.pk,
                "parameters": "{not json",
                "enabled": "on",
            }
        )
        assert not form.is_valid()
        assert "parameters" in form.errors

    def test_without_a_source_a_site_shaped_collector_is_refused(self):
        form = ConfigForm(
            data={
                "name": "Без сайта",
                "collector_key": "tender_kendo",
                "parameters": "{}",
                "enabled": "on",
            }
        )
        assert not form.is_valid()
        assert "source" in form.errors

    def test_a_source_on_a_non_site_collector_is_refused(self):
        """`example_api` declares no site parameters — a `source` here would silently do nothing."""
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        form = ConfigForm(
            data={
                "name": "Демо",
                "collector_key": "example_api",
                "source": source.pk,
                "parameters": "{}",
                "enabled": "on",
            }
        )
        assert not form.is_valid()
        assert "source" in form.errors
```

(`test_fetch_details_only_appears_for_the_engine_that_declares_it` and
`test_a_bad_profile_parameter_is_reported_on_its_own_field` are deleted outright — both tested the
per-`ParamSpec` dynamic field generation this task removes.)

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest tests/test_sources.py::TestConfigFormWithSource -x -q
```

Expected: fails — `ConfigForm` does not yet have a `parameters` field.

- [ ] **Step 3: Rewrite `ConfigForm`**

Replace the whole file:

```python
"""Authoring form for Config.

`parameters` is one JSON textarea — the collector's schema is not reflected into the form at all.
Validation here is a *convenience*, not the guarantee: enqueue re-validates against the schema it
actually resolves (§6). A Config's raw parameters can still drift out of step with the code — the
schema is edited in place as requirements change — and that case is meant to fail fast at enqueue,
not to be prevented here.
"""

from __future__ import annotations

from django import forms

from collectors import schemas
from control.models import Config


class ConfigForm(forms.ModelForm):
    class Meta:
        model = Config
        fields = ["name", "collector_key", "source", "parameters", "enabled", "owner"]
        widgets = {"parameters": forms.Textarea(attrs={"rows": 8, "cols": 60})}

    def clean(self) -> dict:
        cleaned = super().clean()
        key = cleaned.get("collector_key")
        if not key:
            return cleaned

        try:
            descriptor = schemas.get_collector(key)
        except schemas.UnknownCollector:
            self.add_error("collector_key", f"Сборщика {key!r} нет в кодовой базе.")
            return cleaned

        # Resolves correctly whether this form shows a `source` field or not: the
        # Config-under-Source inline never displays one (it is implied by the parent page), but
        # Django's inline-formset machinery substitutes an `InlineForeignKeyField` for it, whose
        # own `clean()` returns the parent instance whenever nothing was submitted — exactly
        # this case.
        source = cleaned.get("source")

        if descriptor.is_site and source is None:
            self.add_error("source", f"Сборщик {key!r} привязан к сайту — выберите источник.")
            return cleaned
        if not descriptor.is_site and source is not None:
            self.add_error(
                "source",
                f"Сборщик {key!r} не использует параметры сайта — источник не даст эффекта.",
            )
            return cleaned

        parameters = cleaned.get("parameters")
        if parameters is None:
            return cleaned

        # An unsaved probe: `raw_parameters()` only reads `collector_key`/`source`/`parameters`,
        # none of which need a persisted row, and this keeps the source-merge logic in exactly
        # the one place (`Config.raw_parameters`) that `enqueue` and the admin preview also use.
        probe = Config(collector_key=key, parameters=parameters, source=source)
        try:
            schemas.resolve_parameters(key, probe.raw_parameters())
        except schemas.ParameterError as exc:
            self.add_error("parameters", "; ".join(exc.errors))
        return cleaned
```

`Config.parameters` is a `JSONField`, which Django's `ModelForm` already renders as a
`forms.JSONField` with the `Textarea` widget declared above — no custom `save()` override is
needed anymore, since the field is bound directly (unlike the old per-`ParamSpec` version, which
had to assemble `parameters` from separate cleaned fields).

- [ ] **Step 4: Run the test again**

```bash
uv run pytest tests/test_sources.py::TestConfigFormWithSource -x -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/control/forms/config.py tests/test_sources.py
git commit -m "refactor: ConfigForm renders parameters as one JSON field, not one per ParamSpec"
```

---

### Task 11: Update `control/admin.py`

**Files:**
- Modify: `src/control/admin.py`

This is the biggest single-file change. Do it in the four pieces below, in order, running the
admin-touching tests after each.

- [ ] **Step 1: `ConfigInline` — delete the dynamic-field workaround**

Delete the nested `ConfigInlineForm` class — with `ConfigForm` no longer building dynamic fields,
there is nothing left for it to suppress — but keep `form = ConfigForm` (now pointing at the plain
class, not the subclass): the inline still needs `ConfigForm.clean()`'s `is_site` gate, which is
what makes `test_a_non_site_collector_is_refused_from_the_inline` (`tests/test_sources.py`) pass.
Without it, Django's inline machinery would fall back to a plain `ModelForm` with none of that
validation.

```python
class ConfigInline(TabularInline):
    """Add another named profile to this source without leaving its page.

    The other half of the "one guided step" from the Source/Config split: the Config-add form
    already lets you register a brand-new source inline (via the `source` field's own add-popup);
    this is the reverse direction — a *second* profile (`full`, `fast`, ...) for a site that
    already has one. `source` is implied by the parent row, so it is deliberately not one of the
    visible fields; everything beyond name/collector/enabled — parameters, schedules — stays on
    the profile's own change page, reached via `show_change_link`.

    Uses the plain `ConfigForm` (not a subclass): the only reason a subclass ever existed was to
    suppress the old per-`ParamSpec` dynamic field generation, which no longer happens. The
    `fields` tuple below already limits what's rendered; `ConfigForm.clean()`'s `is_site` gate
    still runs because Django's inline formset machinery substitutes an `InlineForeignKeyField`
    for the (unrendered) `source` field, whose `clean()` returns the parent instance.
    """

    model = Config
    form = ConfigForm
    fk_name = "source"
    extra = 0
    fields = ("name", "collector_key", "enabled")
    show_change_link = True
    verbose_name = "Профиль"
    verbose_name_plural = "Профили"
```

- [ ] **Step 2: `ConfigAdmin` — replace the cache columns with a `Job` subquery, drop
  `get_form`/`get_fieldsets`, drop the archive/tags fields and actions**

Add the import at the top of the file:

```python
from django.db.models import OuterRef, QuerySet, Subquery
```

(replacing the existing `from django.db.models import QuerySet` line).

Replace the whole `ConfigAdmin` class:

```python
@admin.register(Config)
class ConfigAdmin(ModelAdmin):
    form = ConfigForm
    inlines = [ScheduleInline]
    list_display = (
        "name",
        "collector_key",
        "source",
        "enabled",
        "latest_status_badge",
        "latest_job_at_display",
        "latest_job_link",
        "owner",
    )
    list_filter = ("collector_key", "source", "enabled")
    search_fields = ("name", "collector_key")
    autocomplete_fields = ("owner", "source")
    readonly_fields = (
        "created_by",
        "created_at",
        "updated_at",
        "resolved_preview",
    )
    fieldsets = (
        (None, {"fields": ("name", "collector_key", "source", "parameters")}),
        ("Что уйдёт в задачу", {"fields": ("resolved_preview",), "classes": ("collapse",)}),
        ("Состояние", {"fields": ("enabled", "owner")}),
        (
            "Аудит",
            {"fields": ("created_by", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
    actions = ["action_run_now", "action_enable", "action_disable"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Config]:
        latest_job = Job.objects.filter(config_id=OuterRef("pk")).order_by("-created_at")
        return (
            super()
            .get_queryset(request)
            .annotate(
                latest_job_status=Subquery(latest_job.values("status")[:1]),
                latest_job_id_ann=Subquery(latest_job.values("id")[:1]),
                latest_job_at=Subquery(latest_job.values("created_at")[:1]),
            )
        )

    def save_model(self, request: HttpRequest, obj: Config, form, change: bool) -> None:
        if not change:
            obj.created_by = request.user
            if obj.owner_id is None:
                obj.owner = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Последний статус", ordering="latest_job_status")
    def latest_status_badge(self, obj: Config) -> SafeString:
        return _status_badge(getattr(obj, "latest_job_status", "") or "")

    @admin.display(description="Последний запуск", ordering="latest_job_at")
    def latest_job_at_display(self, obj: Config) -> str:
        value = getattr(obj, "latest_job_at", None)
        return "—" if value is None else str(value)

    @admin.display(description="Последняя задача")
    def latest_job_link(self, obj: Config) -> SafeString:
        job_id = getattr(obj, "latest_job_id_ann", None)
        if not job_id:
            return format_html("—")
        url = reverse("admin:control_job_change", args=[job_id])
        return format_html('<a href="{}">Задача #{}</a>', url, job_id)

    @admin.display(description="Итоговые параметры")
    def resolved_preview(self, obj: Config) -> SafeString:
        """Show exactly what a Job created right now would snapshot — or why it would not."""
        if not obj.pk:
            return format_html("<i>Сначала сохраните.</i>")
        try:
            effective = schemas.resolve_parameters(obj.collector_key, obj.raw_parameters())
        except schemas.UnknownCollector:
            return format_html(
                '<b style="color:#c92a2a">Сборщика {} нет в кодовой базе — запустить нельзя.</b>',
                obj.collector_key,
            )
        except schemas.ParameterError as exc:
            return format_html(
                '<b style="color:#c92a2a">Не подходит:</b><ul>{}</ul>',
                format_html("".join(format_html("<li>{}</li>", e) for e in exc.errors)),
            )
        rows = format_html(
            "".join(
                format_html("<tr><td><code>{}</code></td><td><code>{}</code></td></tr>", k, repr(v))
                for k, v in sorted(effective.items())
            )
        )
        return format_html("<table><tbody>{}</tbody></table>", rows)

    def _bulk(self, request: HttpRequest, queryset: QuerySet[Config], **updates) -> int:
        count = 0
        for config in queryset:
            for field, value in updates.items():
                setattr(config, field, value)
            config.save(update_fields=list(updates))
            count += 1
        return count

    @admin.action(description="Запустить сейчас")
    def action_run_now(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        """Produce work; never execute it. A worker picks the Job up on its own schedule."""
        from control.services import EnqueueRefused, enqueue

        created: list[str] = []
        for config in queryset:
            try:
                job = enqueue(config, origin=JobOrigin.MANUAL, requested_by=request.user)
            except EnqueueRefused as exc:
                detail = f" ({'; '.join(exc.errors)})" if exc.errors else ""
                self.message_user(request, f"{config.name}: {exc}{detail}", messages.ERROR)
                continue
            created.append(f"#{job.pk} {config.name}")
        if created:
            self.message_user(
                request,
                f"Поставлено задач: {len(created)} — {', '.join(created)}",
                messages.SUCCESS,
            )

    @admin.action(description="Включить выбранные конфигурации")
    def action_enable(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, enabled=True)
        self.message_user(request, f"Включено конфигураций: {n}.", messages.SUCCESS)

    @admin.action(description="Выключить выбранные конфигурации")
    def action_disable(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, enabled=False)
        self.message_user(request, f"Выключено конфигураций: {n}.", messages.SUCCESS)
```

Note what is gone from `ConfigAdmin`: the nested `get_form`/`get_fieldsets` overrides (no dynamic
field set to compute anymore — `fieldsets` is a plain static tuple again), `action_archive`/
`action_unarchive` (no `archived` field left), and `last_status_badge`/`last_job_link` reading
cache columns (replaced by the three `latest_*` methods reading the subquery annotation).

- [ ] **Step 3: `SourceAdmin` — drop the `archived` field**

Replace the class:

```python
@admin.register(Source)
class SourceAdmin(ModelAdmin):
    """The site registry: domain, start URL, TLS quirks — one row per real site.

    Behaviour — which collector, how many pages, how many requests at once — lives on the
    `Config` profiles that reference a Source (see `ConfigAdmin`), not here. A Source knows
    nothing about collectors, schedules or jobs; it exists so several named profiles of the same
    site (`default`/`full`/`fast`, ...) share one domain/TLS instead of each carrying its own copy.
    """

    form = SourceForm
    inlines = [ConfigInline]
    list_display = ("name", "domain", "start_url", "profiles_count")
    search_fields = ("name", "domain")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "domain", "start_url")}),
        (
            "TLS",
            {
                "fields": ("extra_ca_cert", "skip_tls_verify"),
                "classes": ("collapse",),
                "description": "Костыли под сайты со сломанной цепочкой сертификатов. "
                "По умолчанию не нужны.",
            },
        ),
        ("Аудит", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Профилей")
    def profiles_count(self, obj: Source) -> int:
        return obj.configs.count()
```

- [ ] **Step 4: `JobAdmin` — drop `config_revision`**

In the `JobAdmin.fieldsets` "Снимок" section, remove `"config_revision"` from the tuple:

```python
        (
            "Снимок (неизменяем — запуск воспроизводится только по нему)",
            {
                "fields": (
                    "collector_key",
                    "effective_parameters",
                    "config_link",
                    "config_id",
                )
            },
        ),
```

In `config_link`, drop the revision from the label:

```python
    @admin.display(description="Конфигурация")
    def config_link(self, obj: Job) -> SafeString:
        config = Config.objects.filter(pk=obj.config_id).first()
        if config is None:
            return format_html("#{} (удалена)", obj.config_id)
        url = reverse("admin:control_config_change", args=[config.pk])
        return format_html('<a href="{}">{}</a>', url, config.name)
```

- [ ] **Step 5: The "purge all terminal jobs" view — drop the cache-column message**

Find the view around what was line 624 and replace:

```python
        with transaction.atomic():
            deleted = Job.objects.all().delete()[0]
            forgotten = Config.forget_job_outcomes()

        self.message_user(
            request,
            f"Удалено задач: {deleted}. Сброшен последний статус у конфигураций: {forgotten}.",
            messages.SUCCESS if deleted else messages.INFO,
        )
```

with:

```python
        with transaction.atomic():
            deleted = Job.objects.all().delete()[0]

        self.message_user(
            request,
            f"Удалено задач: {deleted}.",
            messages.SUCCESS if deleted else messages.INFO,
        )
```

- [ ] **Step 6: Run the admin-touching test suites**

```bash
uv run pytest tests/test_admin_jobs.py tests/test_sources.py -q
```

Expected: `test_admin_jobs.py` still fails on the two tests that assert removed cache-column/
revision behavior (`test_it_forgets_the_dashboard_cache_columns`,
`test_it_does_not_bump_the_config_revision`) — Task 12 removes them. `test_sources.py` should be
close to passing except wherever Task 13 hasn't landed yet.

- [ ] **Step 7: Commit**

```bash
git add src/control/admin.py
git commit -m "refactor: ConfigAdmin computes latest job status via subquery, drops dynamic fieldsets"
```

---

### Task 12: Update `tests/test_admin_jobs.py`

**Files:**
- Modify: `tests/test_admin_jobs.py`

- [ ] **Step 1: Delete the two tests that assert removed behavior**

Delete `test_it_forgets_the_dashboard_cache_columns` and `test_it_does_not_bump_the_config_revision`
in full (both call `Config.record_job_outcome` directly and assert on `last_status`/`last_run_at`/
`last_job_id`/`revision`, none of which exist anymore).

- [ ] **Step 2: Update the purge-message assertion, if any, to match the shorter message**

Search the file for the old message text:

```bash
grep -n "Сброшен последний статус" tests/test_admin_jobs.py
```

If it appears in an assertion, update it to match the new one-sentence message
(`f"Удалено задач: {deleted}."`) from Task 11 Step 5.

- [ ] **Step 3: Run the file**

```bash
uv run pytest tests/test_admin_jobs.py -x -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_admin_jobs.py
git commit -m "test: drop admin coverage for the removed dashboard cache columns"
```

---

### Task 13: Finish `tests/test_sources.py`

**Files:**
- Modify: `tests/test_sources.py`

`TestSourceForm` (Task 9) and `TestConfigFormWithSource` (Task 10) are already done. This task
covers the rest of the file: rename `listing_path`/`extra_ca_cert`/`skip_tls_verify` attribute
reads, and delete the two tests that asserted the removed `revision` cascade.

- [ ] **Step 1: `TestOneToMany` — delete the revision tests**

Delete `test_editing_the_source_bumps_every_profiles_revision` and
`test_editing_something_other_than_identity_does_not_bump_revision` in full — both asserted the
`Source` → `Config.revision` cascade, which no longer exists (`Config.revision` is gone). Keep
`test_one_source_can_back_several_named_profiles` unchanged.

- [ ] **Step 2: `TestEnqueue` — rename the resolved parameter key**

Change:

```python
        assert job.effective_parameters["listing_path"] == "lots"
```

to:

```python
        assert job.effective_parameters["start_url"] == "lots"
```

- [ ] **Step 3: `TestEndToEnd` — delete the cache-column assertions**

In `test_a_worker_runs_a_profile_and_records_what_it_found`, delete the last two lines:

```python
        profile.refresh_from_db()
        assert profile.last_status == JobStatus.SUCCEEDED
        assert profile.last_job_id == job.pk
```

(the test already asserts `job.status == JobStatus.SUCCEEDED` above this — that is the coverage
that matters; there is no cache column left to check.)

- [ ] **Step 4: `TestConfigInlineUnderSource` — rename the posted field**

In `_inline_post_data`, change:

```python
        data = {
            "name": source.name,
            "domain": source.domain,
            "listing_path": source.listing_path,
            "extra_ca_cert": source.extra_ca_cert,
            ...
        }
```

to:

```python
        data = {
            "name": source.name,
            "domain": source.domain,
            "start_url": source.start_url,
            "extra_ca_cert": source.tls_options.get("extra_ca_cert", ""),
            ...
        }
```

- [ ] **Step 5: `TestSeed` — rename the field reads**

Change:

```python
    def test_per_site_quirks_survive_the_carry_over(self):
        call_command("seed_sources", verbosity=0)

        assert Source.objects.get(name="АРБбитЛот").skip_tls_verify is True
        assert Source.objects.get(name="МЕТА-ИНВЕСТ").extra_ca_cert.endswith(".pem")
        assert Source.objects.get(name="Промконсалт").listing_path == "tradelist.php"
```

to:

```python
    def test_per_site_quirks_survive_the_carry_over(self):
        call_command("seed_sources", verbosity=0)

        arbbitlot = Source.objects.get(name="АРБбитЛот")
        assert arbbitlot.tls_options.get("skip_tls_verify") is True
        meta_invest = Source.objects.get(name="МЕТА-ИНВЕСТ")
        assert meta_invest.tls_options.get("extra_ca_cert", "").endswith(".pem")
        assert Source.objects.get(name="Промконсалт").start_url == "tradelist.php"
```

- [ ] **Step 6: Run the full file**

```bash
uv run pytest tests/test_sources.py -x -q
```

Expected: PASS (this exercises `seed_sources`, which Task 14 has not touched yet — if it fails
here because `seed_sources.py` still writes the old field names, that is expected; do Task 14
next and re-run).

- [ ] **Step 7: Commit**

```bash
git add tests/test_sources.py
git commit -m "test: update test_sources.py for start_url/tls_options and the removed revision cascade"
```

---

### Task 14: Update `control/management/commands/seed.py` and `seed_sources.py`

**Files:**
- Modify: `src/control/management/commands/seed.py`
- Modify: `src/control/management/commands/seed_sources.py`

- [ ] **Step 1: Update `seed.py`**

Change the import:

```python
from control.models import CatchupPolicy, Config, OverlapPolicy, Schedule
```

to:

```python
from control.models import Config, Schedule
```

Update the three `samples` entries: drop every `"tags": [...]` key, and replace each
`"schedule": {...}` dict's policy keys. The first sample's schedule:

```python
                "schedule": {
                    "cron": "0 2 * * *",
                    "timezone": "Europe/Berlin",
                    "overlap_policy": OverlapPolicy.SKIP,
                    "catchup_policy": CatchupPolicy.SKIP_TO_NOW,
                },
```

becomes:

```python
                "schedule": {
                    "cron": "0 2 * * *",
                    "timezone": "Europe/Berlin",
                    "skip_if_running": True,
                },
```

The second sample's schedule:

```python
                "schedule": {
                    "cron": "0 * * * *",
                    "timezone": "UTC",
                    "overlap_policy": OverlapPolicy.QUEUE,
                    "catchup_policy": CatchupPolicy.FIRE_MISSED,
                },
```

becomes:

```python
                "schedule": {
                    "cron": "0 * * * *",
                    "timezone": "UTC",
                    "skip_if_running": False,
                },
```

The third sample has `"schedule": None` and a `"tags": ["legacy"]` key to drop — leave the
`"schedule": None` line as-is.

- [ ] **Step 2: Update `seed_sources.py`**

The `SOURCES` list's `"params"` dicts use `listing_path`/`skip_tls_verify`/`extra_ca_cert` keys
that fed straight into `Source.objects.create(**site_fields)`. Rename `listing_path` to
`start_url` in the two entries that set it:

```python
    {
        "engine": "ruson",
        "title": "Объединённые системы торгов",
        "domain": "https://sistematorg.com",
        "params": {"listing_path": "tradelist.php"},
    },
    {
        "engine": "ruson",
        "title": "Промконсалт",
        "domain": "https://promkonsalt.ru",
        "params": {"listing_path": "tradelist.php"},
    },
```

become:

```python
    {
        "engine": "ruson",
        "title": "Объединённые системы торгов",
        "domain": "https://sistematorg.com",
        "params": {"start_url": "tradelist.php"},
    },
    {
        "engine": "ruson",
        "title": "Промконсалт",
        "domain": "https://promkonsalt.ru",
        "params": {"start_url": "tradelist.php"},
    },
```

Leave the `skip_tls_verify`/`extra_ca_cert` entries' key names alone in the `SOURCES` list itself
(`"params": {"skip_tls_verify": True}`, `"params": {"extra_ca_cert": "meta_invest_....pem"}`) —
the command below bundles them into `tls_options` at creation time, so the source data stays
readable as flat quirks.

In `Command.handle()`, replace:

```python
            created += 1
            self.stdout.write(f"+ {spec['title']} ({domain})")
            if spec.get("note"):
                self.stdout.write(f"    {spec['note']}")
            if not dry_run:
                source = Source.objects.create(name=spec["title"], domain=domain, **site_fields)
                Config.objects.create(
                    name=spec["title"],
                    collector_key=key,
                    source=source,
                    enabled=spec.get("enabled", True),
                )
```

with:

```python
            created += 1
            self.stdout.write(f"+ {spec['title']} ({domain})")
            if spec.get("note"):
                self.stdout.write(f"    {spec['note']}")
            if not dry_run:
                tls_keys = set(Source.TLS_OPTION_FIELDS)
                source_kwargs = {k: v for k, v in site_fields.items() if k not in tls_keys}
                tls_options = {k: v for k, v in site_fields.items() if k in tls_keys}
                source = Source.objects.create(
                    name=spec["title"],
                    domain=domain,
                    tls_options=tls_options,
                    **source_kwargs,
                )
                Config.objects.create(
                    name=spec["title"],
                    collector_key=key,
                    source=source,
                    enabled=spec.get("enabled", True),
                )
```

- [ ] **Step 3: Run the full source-seeding coverage**

```bash
uv run pytest tests/test_sources.py -x -q
```

Expected: PASS, including `TestSeed`.

- [ ] **Step 4: Run `seed` end to end against a real database**

```bash
uv run python src/manage.py seed
uv run python src/manage.py seed_sources
```

Expected: both commands complete without error and report `created`/`kept` counts (run against a
freshly migrated dev database from Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/control/management/commands/seed.py src/control/management/commands/seed_sources.py
git commit -m "refactor: update seed commands for skip_if_running, start_url and tls_options"
```

---

### Task 15: Update `tests/test_models.py`

**Files:**
- Modify: `tests/test_models.py`

- [ ] **Step 1: Update the `_job` helper**

Remove `"config_revision": config.revision,` from `_job`'s defaults:

```python
def _job(config: Config, **overrides) -> Job:
    defaults = {
        "collector_key": config.collector_key,
        "effective_parameters": {"base_url": "https://x.test"},
        "config_id": config.pk,
    }
    return Job.objects.create(**{**defaults, **overrides})
```

- [ ] **Step 2: Delete `TestConfigRevision` in full**

All five of its tests (`test_starts_at_one_and_bumps_on_an_authored_change`,
`test_does_not_bump_when_nothing_meaningful_changed`,
`test_detects_an_in_place_mutation_of_the_parameters_dict`,
`test_cache_column_writes_are_not_edits`, `test_an_older_run_does_not_overwrite_a_newer_one`)
asserted the removed `revision`/cache-column mechanism — delete the whole class.

- [ ] **Step 3: Run the file**

```bash
uv run pytest tests/test_models.py -x -q
```

Expected: PASS — `TestJobInvariants` and `TestSchedule` were not touched and cover behavior
confirmed unchanged.

- [ ] **Step 4: Commit**

```bash
git add tests/test_models.py
git commit -m "test: drop TestConfigRevision, config_revision no longer exists"
```

---

### Task 16: Update `tests/test_enqueue.py`

**Files:**
- Modify: `tests/test_enqueue.py`

- [ ] **Step 1: Delete the archived-config test**

Delete `test_an_archived_config_is_refused` from `TestPreconditions` in full — `Config.archived`
no longer exists, so there is nothing left to refuse on that basis.

- [ ] **Step 2: Drop `config_revision` assertions from `TestSnapshot`**

Change:

```python
    def test_resolves_parameters_against_the_collectors_schema(self, config):
        job = enqueue(config)

        assert job.config_id == config.pk
        assert job.config_revision == config.revision
        assert job.status == JobStatus.PENDING
```

to:

```python
    def test_resolves_parameters_against_the_collectors_schema(self, config):
        job = enqueue(config)

        assert job.config_id == config.pk
        assert job.status == JobStatus.PENDING
```

Change:

```python
    def test_a_later_config_edit_does_not_touch_an_existing_snapshot(self, config):
        job = enqueue(config)
        original = dict(job.effective_parameters)

        config.parameters["base_url"] = "https://changed.test"
        config.save()

        assert Job.objects.get(pk=job.pk).effective_parameters == original
        assert Job.objects.get(pk=job.pk).config_revision == 1
        assert Config.objects.get(pk=config.pk).revision == 2
```

to:

```python
    def test_a_later_config_edit_does_not_touch_an_existing_snapshot(self, config):
        job = enqueue(config)
        original = dict(job.effective_parameters)

        config.parameters["base_url"] = "https://changed.test"
        config.save()

        assert Job.objects.get(pk=job.pk).effective_parameters == original
```

- [ ] **Step 3: Delete the dashboard-cache test from `TestInvalidParameters`**

Delete `test_the_recorded_failure_refreshes_the_dashboard_cache` in full — it asserted
`Config.last_status`/`last_job_id` directly, both removed. The Job itself reaching `FAILED` is
already covered by `test_a_scheduled_fire_records_a_failed_job_instead`.

- [ ] **Step 4: Run the file**

```bash
uv run pytest tests/test_enqueue.py -x -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_enqueue.py
git commit -m "test: drop archived-config and revision/cache-column coverage from test_enqueue.py"
```

---

### Task 17: Update the dashboard (`control/dashboard/views.py` + template)

**Files:**
- Modify: `src/control/dashboard/views.py`
- Modify: `src/control/templates/dashboard/index.html`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Check what `test_dashboard.py` currently asserts**

```bash
grep -n "last_status\|last_run_at\|last_job_id\|archived" tests/test_dashboard.py
```

If this reports nothing (per the earlier project-wide grep it should), no test changes are needed
here — only production code. If it does report matches, update those assertions the same way as
Task 13 Step 3/5 (read the latest `Job` for the `Config` under test instead of a cache column).

- [ ] **Step 2: Update `index()` to annotate instead of filtering by `archived` and reading cache
  columns**

Replace:

```python
from django.db.models import Count
...

@staff_member_required
def index(request: HttpRequest) -> HttpResponse:
    configs = Config.objects.filter(archived=False).order_by("name")
    # Job→Config is a soft reference, so "does this config have something in flight?" is a second
    # query rather than a join. One extra query for the whole page is the right trade here.
    active_config_ids = set(
        Job.objects.filter(status__in=JobStatus.active()).values_list("config_id", flat=True)
    )
    return render(
        request,
        "dashboard/index.html",
        {
            "configs": configs,
            "active_config_ids": active_config_ids,
            "jobs": _recent_jobs(),
            "counts": _status_counts(),
        },
    )
```

with:

```python
from django.db.models import Count, OuterRef, Subquery
...

@staff_member_required
def index(request: HttpRequest) -> HttpResponse:
    latest_job = Job.objects.filter(config_id=OuterRef("pk")).order_by("-created_at")
    configs = list(
        Config.objects.annotate(
            latest_job_status=Subquery(latest_job.values("status")[:1]),
            latest_job_id=Subquery(latest_job.values("id")[:1]),
            latest_job_at=Subquery(latest_job.values("created_at")[:1]),
        ).order_by("name")
    )
    for c in configs:
        c.latest_job_label = JobStatus(c.latest_job_status).label if c.latest_job_status else ""

    # Job→Config is a soft reference, so "does this config have something in flight?" is a second
    # query rather than a join. One extra query for the whole page is the right trade here.
    active_config_ids = set(
        Job.objects.filter(status__in=JobStatus.active()).values_list("config_id", flat=True)
    )
    return render(
        request,
        "dashboard/index.html",
        {
            "configs": configs,
            "active_config_ids": active_config_ids,
            "jobs": _recent_jobs(),
            "counts": _status_counts(),
        },
    )
```

- [ ] **Step 3: Update the template**

In `src/control/templates/dashboard/index.html`, replace:

```html
            <td>
              {% if config.last_status %}
                <span class="status status-{{ config.last_status }}">
                  {{ config.get_last_status_display }}</span>
                {% if config.last_job_id %}
                  <a class="muted" href="{% url 'admin:control_job_change' config.last_job_id %}">
                    #{{ config.last_job_id }}</a>
                {% endif %}
              {% else %}<span class="muted">не запускалась</span>{% endif %}
            </td>
            <td class="muted">{{ config.last_run_at|default:"—" }}</td>
```

with:

```html
            <td>
              {% if config.latest_job_status %}
                <span class="status status-{{ config.latest_job_status }}">
                  {{ config.latest_job_label }}</span>
                {% if config.latest_job_id %}
                  <a class="muted" href="{% url 'admin:control_job_change' config.latest_job_id %}">
                    #{{ config.latest_job_id }}</a>
                {% endif %}
              {% else %}<span class="muted">не запускалась</span>{% endif %}
            </td>
            <td class="muted">{{ config.latest_job_at|default:"—" }}</td>
```

- [ ] **Step 4: Run the dashboard suite**

```bash
uv run pytest tests/test_dashboard.py -x -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/control/dashboard/views.py src/control/templates/dashboard/index.html tests/test_dashboard.py
git commit -m "refactor: dashboard reads latest Job status via subquery instead of cache columns"
```

---

### Task 18: Retire the ADRs and fix stale references

**Files:**
- Delete: `docs/architecture/adr/0001-architecture-baseline.md` through
  `0005-config-parameter-fields.md`
- Modify: `README.md`, `README.ru.md`

- [ ] **Step 1: Delete the ADR files**

```bash
rm docs/architecture/adr/0001-architecture-baseline.md \
   docs/architecture/adr/0002-tender-site-collectors.md \
   docs/architecture/adr/0003-remove-collector-versioning.md \
   docs/architecture/adr/0004-source-as-table.md \
   docs/architecture/adr/0005-config-parameter-fields.md
```

- [ ] **Step 2: Fix `README.md` and `README.ru.md`**

Both files link to the now-deleted ADRs and to `CLAUDE.md` (already removed in a prior commit).
Remove the "Архитектура и обоснование решений" / "Architecture and rationale" bullet list pointing
at `docs/architecture/adr/०001...` and `CLAUDE.md`, and remove the sentence in the
"Сбор с торговых площадок" / lot-collection section claiming lots are not stored (they are, via
`Lot`/`DbLotSink` — unrelated to this redesign, just stale prose). Point instead at the new design
doc:

```markdown
* Обоснование решений в control (модели, формы, админка): [`docs/superpowers/specs/2026-07-31-control-models-redesign-design.md`](docs/superpowers/specs/2026-07-31-control-models-redesign-design.md)
```

(Mirror the equivalent sentence in `README.md`'s English section.)

- [ ] **Step 3: Confirm nothing else references the deleted files**

```bash
grep -rn "architecture/adr\|CLAUDE.md" --include=*.md --include=*.py . 2>/dev/null | grep -v docs/superpowers
```

Expected: no remaining hits outside `docs/superpowers/` (the design/plan docs themselves are
allowed to mention the old ADRs as historical context).

- [ ] **Step 4: Commit**

```bash
git add -A docs/architecture/adr README.md README.ru.md
git commit -m "docs: retire ADR 0001-0005, point README at the control-models redesign spec"
```

---

### Task 19: Full verification pass

**Files:** none — this is a checkpoint, not an edit.

- [ ] **Step 1: Run the whole test suite**

```bash
uv run pytest -q
```

Expected: PASS, zero failures.

- [ ] **Step 2: Run the project's own verification barrier**

```bash
make verify
```

Expected: passes — Django system checks, migration drift check, `ruff`, `import-linter` contracts,
and the full test suite (the same barrier CI would run).

- [ ] **Step 3: If anything fails**

Use `superpowers:systematic-debugging` rather than patching symptoms — this plan's tasks were
ordered so each file's dependents come right after it, but a missed cross-reference (an
`import-linter` contract catching a stray import, a template tag referencing a removed context
key) is still possible. Fix at the root file identified above, not by re-adding a removed field.

- [ ] **Step 4: Final commit if Step 3 needed one**

```bash
git add -A
git commit -m "fix: address make verify failures after the control models redesign"
```
