"""All persistence for the whole system lives here.

`execution` owns runtime behavior and no models; it imports these. Keep framework glue thin and
put invariants that must always hold — terminal states, snapshot immutability — in the model
layer, where nothing can route around them.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from collectors import schemas


def _snapshot_values(names: Iterable[str], values: Sequence[Any]) -> dict[str, Any]:
    """Remember loaded field values for change detection.

    JSON fields are deep-copied: without that, mutating `config.parameters` in place would leave
    the "before" and "after" pointing at the same object and the change would go unnoticed.
    """
    return {
        name: copy.deepcopy(value) if isinstance(value, dict | list) else value
        for name, value in zip(names, values, strict=True)
    }


# Stored values stay English — they are data, referenced by the queue SQL, the tests and
# CLAUDE.md. Only the labels are Russian, because only labels are ever shown to a human.
class JobStatus(models.TextChoices):
    PENDING = "pending", "В очереди"
    RUNNING = "running", "Выполняется"
    SUCCEEDED = "succeeded", "Успешно"
    FAILED = "failed", "Ошибка"
    CANCELLED = "cancelled", "Отменена"

    @classmethod
    def terminal(cls) -> frozenset[str]:
        return frozenset({cls.SUCCEEDED, cls.FAILED, cls.CANCELLED})

    @classmethod
    def active(cls) -> frozenset[str]:
        return frozenset({cls.PENDING, cls.RUNNING})


class JobOrigin(models.TextChoices):
    MANUAL = "manual", "Вручную"
    SCHEDULE = "schedule", "По расписанию"


class Collector(models.Model):
    """A projection of collector *code* into the database.

    Deliberately lightweight: key, label, description, enabled. Version and parameter schema come
    from `collectors/` and are never editable here — storing them would make the DB a second,
    divergent source of truth. `manage.py sync_collectors` maintains these rows; they are
    disabled, never deleted.
    """

    key = models.CharField("Ключ", max_length=100, unique=True)
    display_name = models.CharField("Название", max_length=200)
    description = models.TextField("Описание", blank=True)
    enabled = models.BooleanField(
        "Включён",
        default=True,
        help_text="У выключенного сборщика сохраняется история и конфигурации, "
        "но ничего нового не запускается.",
    )
    synced_at = models.DateTimeField("Синхронизирован", null=True, blank=True, editable=False)

    class Meta:
        ordering = ["key"]
        verbose_name = "Сборщик"
        verbose_name_plural = "Сборщики"

    def __str__(self) -> str:
        return f"{self.display_name} ({self.key})"


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


class Lot(models.Model):
    """One collected lot, as last seen — kept for whatever history already accumulated here.

    No longer written to: `execution.worker.mongo_lot_sink.MongoLotSink` is what `open_lot_sink`
    hands runners now, because a lot's shape varies by collector family and that fights a
    fixed-column table. This model stays so existing rows remain queryable; a fresh deployment has
    no reason to populate it.

    Current state, not history: a crawl updates the row in place. `(source, lot_id)` is the
    identity, so re-crawling a site converges instead of accumulating.

    **A lot is never retired for being absent.** A crawl is truncated by `max_pages` and filtered
    by `only_active`, so a lot missing from one pass says something about the pass, not about the
    lot. `is_active` therefore comes from the site's own status text, and `last_seen_at` is what
    tells you how stale a row is.

    `fingerprint` is the load-bearing column: the listing parser compares it against the
    fingerprint of the row it just read and skips the expensive detail request when they match.
    It must be computed from the same values the listing produces — see
    `collectors.engine.core.storage.contracts.fingerprint_of`.
    """

    source = models.CharField("Источник", max_length=255, help_text="Хост площадки.")
    lot_id = models.CharField("Идентификатор лота", max_length=255)

    trade_id = models.CharField("Идентификатор торга", max_length=255, blank=True, default="")
    lot_num = models.CharField("Номер лота", max_length=64, blank=True, default="")
    trade_number = models.CharField("Номер торга", max_length=255, blank=True, default="")
    trade_type = models.CharField("Тип торгов", max_length=255, blank=True, default="")
    debtor = models.TextField("Должник", blank=True, default="")
    organizer = models.TextField("Организатор", blank=True, default="")

    description = models.TextField("Описание", blank=True, default="")
    lot_url = models.TextField("Ссылка на лот", blank=True, default="")
    price = models.FloatField("Цена", null=True, blank=True)
    price_raw = models.CharField("Цена как на сайте", max_length=255, blank=True, default="")

    status = models.CharField("Статус", max_length=255, blank=True, default="")
    is_active = models.BooleanField(
        "Идут торги",
        default=True,
        help_text="Выведено из статуса самой площадки, а не из присутствия лота в обходе.",
    )
    bidding_deadline = models.DateTimeField("Приём заявок до", null=True, blank=True)
    result_date = models.DateTimeField("Дата результатов", null=True, blank=True)
    bidding_date_raw = models.CharField("Срок как на сайте", max_length=255, blank=True, default="")
    event_date_raw = models.CharField("Дата как на сайте", max_length=255, blank=True, default="")

    attachments = models.JSONField("Документы", default=list, blank=True)
    price_schedule = models.JSONField("График снижения цены", default=list, blank=True)
    extra = models.JSONField("Прочее с карточки", default=dict, blank=True)

    fingerprint = models.CharField(
        "Отпечаток",
        max_length=64,
        blank=True,
        default="",
        help_text="Хэш табличных полей. Совпал — карточка лота не перезапрашивается.",
    )
    first_seen_at = models.DateTimeField("Впервые увиден", auto_now_add=True)
    last_seen_at = models.DateTimeField("Последний раз увиден", db_index=True)
    last_job_id = models.BigIntegerField(
        "Последняя задача",
        null=True,
        blank=True,
        help_text="Мягкая ссылка, как и у Job на Config: лоты переживают чистку истории задач.",
    )

    class Meta:
        ordering = ["-last_seen_at"]
        verbose_name = "Лот"
        verbose_name_plural = "Лоты"
        constraints = [
            models.UniqueConstraint(fields=["source", "lot_id"], name="uniq_lot_per_source"),
        ]
        indexes = [
            models.Index(fields=["source", "is_active"], name="lot_by_source_active_idx"),
            models.Index(fields=["-last_seen_at"], name="lot_by_last_seen_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source} · {self.lot_id}"


class Schedule(models.Model):
    """When to run a Config. A containment child: it dies with its Config.

    `last_fired_at` is the *only* produced-state echo allowed in `control`. Anything resembling a
    collection cursor belongs to execution, not here.
    """

    config = models.ForeignKey(
        Config, verbose_name="Конфигурация", on_delete=models.CASCADE, related_name="schedules"
    )
    cron = models.CharField(
        "Cron", max_length=100, help_text="Стандартное cron-выражение из пяти полей."
    )
    timezone = models.CharField(
        "Часовой пояс",
        max_length=64,
        default="UTC",
        help_text="Название по IANA. Моменты запуска считаются в этом поясе, хранятся в UTC.",
    )
    enabled = models.BooleanField("Включено", default=True)
    skip_if_running = models.BooleanField(
        "Пропускать, если ещё выполняется",
        default=True,
        help_text="Не запускать новый экземпляр, пока предыдущий запуск этой конфигурации не "
        "завершён. Пропущенное срабатывание не догоняется — считается только ближайшее к "
        "текущему моменту.",
    )
    last_fired_at = models.DateTimeField(
        "Последнее срабатывание",
        null=True,
        blank=True,
        help_text="Сдвигается в той же транзакции, что создаёт задачу.",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        ordering = ["config__name", "cron"]
        verbose_name = "Расписание"
        verbose_name_plural = "Расписания"
        indexes = [models.Index(fields=["enabled"])]

    def __str__(self) -> str:
        return f"{self.cron} [{self.timezone}]"

    def clean(self) -> None:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(
                {"timezone": f"неизвестный часовой пояс {self.timezone!r}"}
            ) from None

        from croniter import croniter

        if not croniter.is_valid(self.cron):
            raise ValidationError({"cron": f"некорректное cron-выражение {self.cron!r}"})


class Job(models.Model):
    """One execution attempt of one Config, and the queue row that drives it.

    A separate aggregate, not a child of Config: it holds an immutable **snapshot** (§4) plus
    mutable execution state (§7). Everything a run needs is in the snapshot, so a Config edit —
    or an archive — mid-flight changes nothing about a run already in progress.

    The table *is* the queue. See `execution.queue.claim`.
    """

    #: Immutable once the row exists. Guarded in `save()`.
    SNAPSHOT_FIELDS = (
        "collector_key",
        "effective_parameters",
        "config_id",
    )

    # --- snapshot (§4) ----------------------------------------------------------------
    collector_key = models.CharField("Сборщик", max_length=100, editable=False)
    effective_parameters = models.JSONField(
        "Итоговые параметры",
        default=dict,
        editable=False,
        help_text="Параметры, разрешённые по схеме сборщика: подставлены умолчания, пройдена "
        "проверка. Только *ссылки* на учётные данные — никогда не сами секреты.",
    )
    config_id = models.BigIntegerField(
        "Конфигурация",
        db_index=True,
        editable=False,
        help_text="Мягкая ссылка. Внешнего ключа нет намеренно: история задач переживает "
        "жизненный цикл конфигурации.",
    )
    # --- origin -----------------------------------------------------------------------
    origin = models.CharField(
        "Источник", max_length=16, choices=JobOrigin.choices, default=JobOrigin.MANUAL
    )
    schedule_id = models.BigIntegerField("Расписание", null=True, blank=True, editable=False)
    fire_time = models.DateTimeField(
        "Момент срабатывания",
        null=True,
        blank=True,
        editable=False,
        help_text="Запланированный момент, который реализует эта задача. Уникален в пределах "
        "расписания — именно это ограничение, а не блокировка, делает планирование "
        "идемпотентным.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Запросил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_jobs",
        editable=False,
    )

    # --- mutable state / lease (§7) ---------------------------------------------------
    status = models.CharField(
        "Статус", max_length=16, choices=JobStatus.choices, default=JobStatus.PENDING
    )
    claimed_by = models.CharField("Захвачена воркером", max_length=200, blank=True, default="")
    claimed_until = models.DateTimeField("Аренда до", null=True, blank=True)
    attempt_no = models.PositiveIntegerField(
        "Попытка",
        default=0,
        help_text="Число передач между исполнителями, а не повторов сборщика. Растёт при каждом "
        "захвате, включая перехват после истечения аренды.",
    )
    cancel_requested = models.BooleanField("Запрошена отмена", default=False)
    priority = models.IntegerField("Приоритет", default=0, help_text="Больше — раньше.")
    available_at = models.DateTimeField("Доступна с", default=timezone.now, db_index=True)

    # --- outcome (§8) -----------------------------------------------------------------
    started_at = models.DateTimeField("Начата", null=True, blank=True)
    finished_at = models.DateTimeField("Завершена", null=True, blank=True)
    result = models.JSONField("Результат", default=dict, blank=True)
    structured_error = models.JSONField(
        "Ошибка", null=True, blank=True, help_text="{type, message, trace}"
    )
    metrics = models.JSONField(
        "Метрики", default=dict, blank=True, help_text="{rows, bytes, calls, ...}"
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        constraints = [
            models.UniqueConstraint(
                fields=["schedule_id", "fire_time"],
                condition=Q(schedule_id__isnull=False),
                name="uniq_job_per_schedule_fire_time",
            ),
        ]
        indexes = [
            # The claim's pending branch.
            models.Index(
                fields=["-priority", "available_at"],
                condition=Q(status="pending"),
                name="job_claimable_pending_idx",
            ),
            # The claim's expired-lease branch — the dead-worker reclaim.
            models.Index(
                fields=["claimed_until"],
                condition=Q(status="running"),
                name="job_expired_lease_idx",
            ),
            models.Index(fields=["config_id", "-created_at"], name="job_by_config_idx"),
            models.Index(fields=["status", "-created_at"], name="job_by_status_idx"),
        ]

    def __str__(self) -> str:
        return f"Задача #{self.pk} · {self.collector_key} · {self.get_status_display()}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        loaded = getattr(self, "_loaded_values", None)
        if self.pk is not None and loaded is not None:
            self._assert_snapshot_unchanged(loaded)
            self._assert_terminal_not_mutated(loaded)
        super().save(*args, **kwargs)
        self._loaded_values = _snapshot_values(
            (*self.SNAPSHOT_FIELDS, "status"),
            [getattr(self, name) for name in (*self.SNAPSHOT_FIELDS, "status")],
        )

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = _snapshot_values(field_names, values)
        return instance

    def _assert_snapshot_unchanged(self, loaded: dict[str, Any]) -> None:
        changed = [
            name
            for name in self.SNAPSHOT_FIELDS
            if name in loaded and loaded[name] != getattr(self, name)
        ]
        if changed:
            raise ValueError(
                f"Job #{self.pk}: snapshot fields are immutable, refusing to change {changed}"
            )

    def _assert_terminal_not_mutated(self, loaded: dict[str, Any]) -> None:
        was = loaded.get("status")
        if was not in JobStatus.terminal():
            return
        if self.status != was:
            raise ValueError(
                f"Job #{self.pk}: {was} is terminal, refusing transition to {self.status}. "
                f"A retry is a new Job."
            )

    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.terminal()

    @property
    def is_active(self) -> bool:
        return self.status in JobStatus.active()

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
