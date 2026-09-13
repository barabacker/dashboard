import secrets

from croniter import CroniterBadCronError, croniter
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from control.conf import control_settings


def validate_cron(value):
    """Проверяет cron-выражение из пяти полей."""
    try:
        croniter(value)
    except (CroniterBadCronError, ValueError) as exc:
        raise ValidationError(f"Некорректное cron-выражение: {exc}") from exc


def generate_token():
    return secrets.token_urlsafe(32)


class Runner(models.Model):
    """Исполнитель заданий: отдельный процесс, возможно на другой машине."""

    name = models.CharField("имя", max_length=100, unique=True)
    token = models.CharField("токен", max_length=64, unique=True, default=generate_token)
    is_active = models.BooleanField("активен", default=True)
    last_seen_at = models.DateTimeField("последняя активность", null=True, blank=True)
    created_at = models.DateTimeField("создан", auto_now_add=True)

    class Meta:
        verbose_name = "раннер"
        verbose_name_plural = "раннеры"
        ordering = ("name",)

    def __str__(self):
        return self.name

    def touch(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at"])


class Source(models.Model):
    """Источник: что запускать, с какими параметрами и по какому расписанию.

    Control plane не знает, что именно делает парсер и куда кладёт данные —
    только имя парсера, параметры и расписание.
    """

    class LogLevel(models.TextChoices):
        DEBUG = "DEBUG", "DEBUG — всё подряд"
        INFO = "INFO", "INFO — обычный режим"
        WARNING = "WARNING", "WARNING — только проблемы"

    name = models.CharField("название", max_length=150)
    slug = models.SlugField("код", max_length=100, unique=True)
    parser = models.CharField(
        "парсер",
        max_length=100,
        help_text="Ключ парсера на стороне раннера, например example.news",
    )
    params = models.JSONField("параметры", default=dict, blank=True)
    cron = models.CharField(
        "расписание",
        max_length=100,
        validators=[validate_cron],
        help_text="Пять полей cron, например «0 6,18 * * *» — в 06:00 и 18:00",
    )
    is_active = models.BooleanField("активен", default=True)
    log_level = models.CharField(
        "уровень логов", max_length=10, choices=LogLevel.choices, default=LogLevel.INFO
    )
    lease_seconds = models.PositiveIntegerField(
        "аренда задания, с",
        default=control_settings.LEASE_SECONDS,
        help_text="Если раннер не подаёт признаков жизни дольше — запуск считается просроченным",
    )
    max_failures = models.PositiveSmallIntegerField(
        "отключить после N неудач",
        default=5,
        help_text="0 — не отключать автоматически",
    )
    consecutive_failures = models.PositiveIntegerField("неудач подряд", default=0)
    next_run_at = models.DateTimeField("следующий запуск", null=True, blank=True)
    last_run_at = models.DateTimeField("последний запуск", null=True, blank=True)
    created_at = models.DateTimeField("создан", auto_now_add=True)
    updated_at = models.DateTimeField("изменён", auto_now=True)

    class Meta:
        verbose_name = "источник"
        verbose_name_plural = "источники"
        ordering = ("name",)
        indexes = [models.Index(fields=["is_active", "next_run_at"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.cron and not self.next_run_at:
            self.next_run_at = self.compute_next_run()
        super().save(*args, **kwargs)

    def compute_next_run(self, since=None):
        """Ближайший запуск по cron после указанного момента."""
        since = since or timezone.now()
        return croniter(self.cron, timezone.localtime(since)).get_next(type(since))


class Run(models.Model):
    """Один запуск источника: журнал, а не хранилище данных."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Успех"
        FAILED = "failed", "Ошибка"
        EXPIRED = "expired", "Просрочен"

    class Trigger(models.TextChoices):
        SCHEDULE = "schedule", "По расписанию"
        MANUAL = "manual", "Вручную"

    source = models.ForeignKey(Source, verbose_name="источник", on_delete=models.CASCADE, related_name="runs")
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.PENDING)
    trigger = models.CharField("запуск", max_length=16, choices=Trigger.choices, default=Trigger.SCHEDULE)
    runner = models.ForeignKey(
        Runner,
        verbose_name="раннер",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    created_at = models.DateTimeField("создан", auto_now_add=True)
    started_at = models.DateTimeField("начало", null=True, blank=True)
    finished_at = models.DateTimeField("окончание", null=True, blank=True)
    lease_expires_at = models.DateTimeField("аренда до", null=True, blank=True)

    items_total = models.PositiveIntegerField("получено", default=0)
    items_new = models.PositiveIntegerField("новых", default=0)
    items_updated = models.PositiveIntegerField("обновлено", default=0)
    counters = models.JSONField("прочие счётчики", default=dict, blank=True)

    # Непрозрачная ссылка на то, куда раннер положил данные: путь, URI, id партии.
    # Control plane её не интерпретирует, только показывает.
    result_locator = models.CharField("результат", max_length=500, blank=True)
    error = models.TextField("ошибка", blank=True)
    warnings_count = models.PositiveIntegerField("предупреждений", default=0)
    log_lines = models.PositiveIntegerField("строк лога", default=0)

    class Meta:
        verbose_name = "запуск"
        verbose_name_plural = "запуски"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["source", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.source} · {self.get_status_display()}"

    @property
    def is_active(self):
        return self.status in (self.Status.PENDING, self.Status.RUNNING)

    @property
    def duration(self):
        if not self.started_at:
            return None
        return (self.finished_at or timezone.now()) - self.started_at


class RunLog(models.Model):
    """Строка лога запуска. Данные сюда попадать не должны — только диагностика."""

    class Level(models.TextChoices):
        DEBUG = "DEBUG", "DEBUG"
        INFO = "INFO", "INFO"
        WARNING = "WARNING", "WARNING"
        ERROR = "ERROR", "ERROR"
        CRITICAL = "CRITICAL", "CRITICAL"

    run = models.ForeignKey(Run, verbose_name="запуск", on_delete=models.CASCADE, related_name="logs")
    seq = models.PositiveIntegerField("номер строки")
    ts = models.DateTimeField("время")
    level = models.CharField("уровень", max_length=10, choices=Level.choices, default=Level.INFO)
    message = models.TextField("сообщение")
    context = models.JSONField("контекст", default=dict, blank=True)

    class Meta:
        verbose_name = "строка лога"
        verbose_name_plural = "логи запусков"
        ordering = ("run", "seq")
        indexes = [
            models.Index(fields=["run", "seq"]),
            models.Index(fields=["level", "ts"]),
        ]

    def __str__(self):
        return f"{self.level}: {self.message[:80]}"
