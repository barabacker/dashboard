"""All persistence for the whole system lives here.

`execution` owns runtime behavior and no models; it imports these. Keep framework glue thin and
put invariants that must always hold — terminal states, snapshot immutability, revision bumps —
in the model layer, where nothing can route around them.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
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


class _ChangeTrackedModel(models.Model):
    """Base for models whose `save()` compares the row as loaded against in-memory edits.

    `from_db` is identical for every subclass — stash what the row looked like when it was read —
    so this is the one place that needs to be right, not three. Subclasses call `_remember()` at
    the end of `save()` with whichever fields they track, and `_any_changed()` to ask, before that
    update lands, whether any of them actually moved.
    """

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = _snapshot_values(field_names, values)
        return instance

    def _any_changed(self, names: Iterable[str]) -> bool:
        loaded = getattr(self, "_loaded_values", None)
        if loaded is None:
            return False
        return any(name in loaded and loaded[name] != getattr(self, name) for name in names)

    def _remember(self, names: Iterable[str]) -> None:
        names = tuple(names)
        self._loaded_values = _snapshot_values(names, [getattr(self, name) for name in names])


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


class OverlapPolicy(models.TextChoices):
    SKIP = "skip", "Пропустить — не запускать, пока идёт предыдущий запуск"
    QUEUE = "queue", "В очередь — поставить в очередь за текущим запуском"
    ALLOW = "allow", "Разрешить — запускать параллельно"


class CatchupPolicy(models.TextChoices):
    FIRE_MISSED = "fire_missed", "Догнать — поставить каждый пропущенный запуск"
    SKIP_TO_NOW = "skip_to_now", "Только последний — пропустить всё, кроме ближайшего к текущему"


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


class Source(_ChangeTrackedModel):
    """A site, authored: domain, listing path and TLS quirks — the identity a crawl needs before
    behaviour (which collector, how many pages, how many requests at once) enters the picture.

    Referenced by `Config.source`, not the other way around: one `Source` can back many named
    `Config` profiles (`default`, `full`, `fast`, ...), each with its own collector and its own
    behavioural parameters. `effective_parameters` at enqueue merges this Source's fields — filtered
    to the ones the profile's collector actually declares — with the profile's own `parameters`
    (see `Config.raw_parameters`); the two key sets are disjoint by construction.

    Deletion is soft (`archived`), the same as `Config`. `Config.source` uses `on_delete=PROTECT`
    so a referenced Source cannot be removed out from under the profiles that point at it.
    """

    #: The Source fields that double as collector parameters — merged into `effective_parameters`
    #: at enqueue (`Config.raw_parameters`) and, for that reason, excluded from the dynamic
    #: per-profile fields `ConfigForm` builds from a collector's `ParamSpec` list: a name must not
    #: be editable in two places at once.
    PARAM_FIELDS = ("domain", "listing_path", "extra_ca_cert", "skip_tls_verify")

    #: Fields whose change means "this site's identity changed" — every Config profile
    #: referencing this Source has its `revision` bumped when one of these moves (`save()` below).
    REVISIONED_FIELDS = (*PARAM_FIELDS, "archived")

    name = models.CharField("Название", max_length=200)
    domain = models.URLField(
        "Домен",
        max_length=200,
        help_text="Корень сайта площадки со схемой и без завершающего слэша, например "
        "https://bankrupt.centerr.ru.",
    )
    listing_path = models.CharField(
        "Путь к листингу",
        max_length=200,
        blank=True,
        default="",
        help_text="Пусто — путь по умолчанию для движка того профиля, который обходит этот сайт.",
    )
    extra_ca_cert = models.CharField(
        "Доп. сертификат",
        max_length=200,
        blank=True,
        default="",
        help_text="Имя PEM-файла из collectors/certs с промежуточным сертификатом. Пусто — "
        "обычный набор корневых сертификатов.",
    )
    skip_tls_verify = models.BooleanField(
        "Не проверять сертификат",
        default=False,
        help_text="Полностью отключить проверку сертификата для этого сайта.",
    )
    archived = models.BooleanField(
        "В архиве",
        default=False,
        help_text="Мягкое удаление. Профили, ссылающиеся на этот сайт, сохраняются.",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Источник"
        verbose_name_plural = "Источники"

    def __str__(self) -> str:
        return f"{self.name} ({self.domain})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Cascade a `revision` bump onto every Config profile that references this Source.

        `Config.save()` only reacts to its own fields; an edit here changes what a referencing
        profile would resolve to just as much as an edit to the profile itself, so the profile's
        `revision` must move too. A direct UPDATE — the same pattern `Config.record_job_outcome` /
        `Config.forget_job_outcomes` already use — because this is an echo of this Source's own
        edit, not an authored change to any one Config.
        """
        changed = self._any_changed(self.REVISIONED_FIELDS)
        super().save(*args, **kwargs)
        if changed:
            Config.objects.filter(source=self).update(revision=F("revision") + 1)
        self._remember(self.REVISIONED_FIELDS)


class Config(_ChangeTrackedModel):
    """The primary business object: *what to collect*, authored by a human.

    Editable at any time. Editing never disturbs a running Job — the Job carries its own snapshot.
    Deletion is soft (`archived`) so history keeps referring to something.
    """

    #: Fields whose change means "the authored intent changed" and must bump `revision`. `source_id`
    #: (not `source`) so checking it never triggers a related-object fetch.
    REVISIONED_FIELDS = (
        "name",
        "collector_key",
        "parameters",
        "enabled",
        "archived",
        "tags",
        "source_id",
    )

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
        "проверяются по схеме версии сборщика, и уже результат попадает в снимок задачи.",
    )
    enabled = models.BooleanField("Включена", default=True)
    archived = models.BooleanField(
        "В архиве",
        default=False,
        help_text="Мягкое удаление. Архивная конфигурация никогда не ставится в очередь.",
    )
    tags = models.JSONField("Метки", default=list, blank=True)
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
    revision = models.PositiveIntegerField("Ревизия", default=1, editable=False)

    # --- dashboard cache columns (§11) ------------------------------------------------
    # Written by the worker when a Job reaches a terminal state, read by list views. These are
    # denormalized caches, not a read model: the Job table remains the source of truth.
    last_status = models.CharField(
        "Последний статус",
        max_length=16,
        choices=JobStatus.choices,
        blank=True,
        default="",
        editable=False,
    )
    last_run_at = models.DateTimeField("Последний запуск", null=True, blank=True, editable=False)
    last_job_id = models.BigIntegerField("Последняя задача", null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Конфигурация"
        verbose_name_plural = "Конфигурации"
        indexes = [
            models.Index(fields=["archived", "enabled"]),
            models.Index(fields=["collector_key"]),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Bump `revision` when authored intent changes — and only then.

        The worker writes the `last_*` cache columns with `update_fields`; that must not look like
        an edit, or every run would inflate the revision the snapshots are compared against.
        """
        update_fields = kwargs.get("update_fields")
        if self.pk is not None and self._any_changed(self.REVISIONED_FIELDS):
            touches_intent = update_fields is None or bool(
                set(update_fields) & set(self.REVISIONED_FIELDS)
            )
            if touches_intent:
                self.revision += 1
                if update_fields is not None:
                    kwargs["update_fields"] = list(set(update_fields) | {"revision"})
        super().save(*args, **kwargs)
        self._remember((*self.REVISIONED_FIELDS, "revision"))

    @property
    def is_runnable(self) -> bool:
        """The two enqueue preconditions that live on the Config itself (§6)."""
        return self.enabled and not self.archived

    def raw_parameters(self) -> dict[str, Any]:
        """`parameters`, extended with whatever `source` provides.

        The two key sets are disjoint by construction — a `Source` field and a profile parameter
        never share a name — so this is a plain union, never an override. Source fields are
        filtered to the ones the collector's schema actually declares, so attaching a `source` to
        a collector that knows nothing about, say, `listing_path` never leaks it through as an
        unknown parameter. `enqueue`, the admin's resolved-parameters preview and the authoring
        forms all resolve against this one method, so they cannot drift apart.
        """
        if self.source_id is None:
            return dict(self.parameters)
        try:
            descriptor = schemas.get_collector(self.collector_key)
        except schemas.UnknownCollector:
            return dict(self.parameters)

        source_fields = {name: getattr(self.source, name) for name in Source.PARAM_FIELDS}
        merged: dict[str, Any] = {}
        for param_name, value in source_fields.items():
            spec = descriptor.param(param_name)
            if spec is None:
                continue
            if not spec.required and value == "":
                continue
            merged[param_name] = value
        merged.update(self.parameters)
        return merged

    @classmethod
    def record_job_outcome(
        cls, *, config_id: int, job_id: int, status: str, finished_at: Any
    ) -> None:
        """Refresh the dashboard cache columns (§11) after a Job reached a terminal state.

        A direct UPDATE on purpose. It must not bump `revision` (this is not an authored change)
        and it must not touch `updated_at` (which should keep meaning "last edited"). The
        `last_run_at` guard keeps two concurrent runs from letting the older one win the race.
        """
        cls.objects.filter(pk=config_id).filter(
            Q(last_run_at__isnull=True) | Q(last_run_at__lte=finished_at)
        ).update(last_status=status, last_run_at=finished_at, last_job_id=job_id)

    @classmethod
    def forget_job_outcomes(cls) -> int:
        """Blank the dashboard cache columns — the mirror image of `record_job_outcome`.

        For when the Jobs they summarise are gone: a `last_status` pointing at a deleted row is
        worse than no status at all. A direct UPDATE for the same two reasons as above — clearing
        history is not an authored change, so it must not bump `revision`, and it is not an edit,
        so it must not move `updated_at`.
        """
        return cls.objects.exclude(last_status="", last_run_at=None, last_job_id=None).update(
            last_status="", last_run_at=None, last_job_id=None
        )


class Lot(models.Model):
    """One collected lot, as last seen.

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


class Job(_ChangeTrackedModel):
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
        "config_revision",
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
    config_revision = models.PositiveIntegerField("Ревизия конфигурации", default=0, editable=False)

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
        self._remember((*self.SNAPSHOT_FIELDS, "status"))

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
