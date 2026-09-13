from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateTimeFilter, RelatedDropdownFilter
from unfold.decorators import action, display

from control.conf import control_settings
from control.models import Run, RunLog, Runner, Source
from control.services import trigger_manual_run

LEVEL_COLORS = {
    RunLog.Level.DEBUG: "#94a3b8",
    RunLog.Level.INFO: "#2563eb",
    RunLog.Level.WARNING: "#d97706",
    RunLog.Level.ERROR: "#dc2626",
    RunLog.Level.CRITICAL: "#991b1b",
}

STATUS_LABELS = {
    "Ожидает": "info",
    "Выполняется": "warning",
    "Успех": "success",
    "Ошибка": "danger",
    "Просрочен": "danger",
}


@admin.register(Runner)
class RunnerAdmin(ModelAdmin):
    list_display = ("name", "active_badge", "last_seen_display", "token_hint")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("last_seen_at", "created_at")
    fieldsets = (
        ("Раннер", {"fields": ("name", "is_active")}),
        (
            "Доступ",
            {
                "fields": ("token",),
                "description": "Токен передаётся в заголовке X-Runner-Token. "
                "Скомпрометирован — просто впишите новый.",
            },
        ),
        ("Служебное", {"fields": ("last_seen_at", "created_at")}),
    )

    @display(description="активен", boolean=True)
    def active_badge(self, obj):
        return obj.is_active

    @display(description="последняя активность")
    def last_seen_display(self, obj):
        if not obj.last_seen_at:
            return "ни разу не приходил"
        delta = timezone.now() - obj.last_seen_at
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "только что"
        if minutes < 60:
            return f"{minutes} мин назад"
        return obj.last_seen_at.strftime("%d.%m.%Y %H:%M")

    @display(description="токен")
    def token_hint(self, obj):
        return f"{obj.token[:6]}…{obj.token[-4:]}"


@admin.register(Source)
class SourceAdmin(ModelAdmin):
    list_display = (
        "name",
        "parser",
        "cron",
        "active_badge",
        "next_run_display",
        "last_status",
        "failures_display",
    )
    list_filter = ("is_active", ("log_level", ChoicesDropdownFilter))
    list_filter_submit = True
    search_fields = ("name", "slug", "parser")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("consecutive_failures", "last_run_at", "created_at", "updated_at")
    actions_row = ("run_now",)
    actions_detail = ("run_now",)
    fieldsets = (
        ("Источник", {"fields": ("name", "slug", "is_active")}),
        (
            "Что запускать",
            {
                "fields": ("parser", "params"),
                "description": "Ключ парсера и параметры — их интерпретирует раннер, "
                "control plane в них не заглядывает.",
            },
        ),
        ("Расписание", {"fields": ("cron", "next_run_at", "last_run_at")}),
        (
            "Поведение",
            {
                "fields": ("log_level", "lease_seconds", "max_failures", "consecutive_failures"),
            },
        ),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @display(description="активен", boolean=True)
    def active_badge(self, obj):
        return obj.is_active

    @display(description="следующий запуск")
    def next_run_display(self, obj):
        if not obj.is_active:
            return "—"
        if not obj.next_run_at:
            return "не запланирован"
        return timezone.localtime(obj.next_run_at).strftime("%d.%m %H:%M")

    @display(description="последний результат", label=STATUS_LABELS)
    def last_status(self, obj):
        run = obj.runs.first()
        return run.get_status_display() if run else "не запускался"

    @display(description="неудач подряд")
    def failures_display(self, obj):
        if not obj.consecutive_failures:
            return "0"
        return format_html('<span style="color:#dc2626">{}</span>', obj.consecutive_failures)

    @action(description="Запустить сейчас", icon="play_arrow")
    def run_now(self, request, object_id):
        source = get_object_or_404(Source, pk=object_id)
        run = trigger_manual_run(source)
        messages.success(
            request,
            f"Запуск #{run.pk} поставлен в очередь. Раннер подхватит его при следующем опросе.",
        )
        return redirect(reverse("admin:control_run_change", args=[run.pk]))


@admin.register(Run)
class RunAdmin(ModelAdmin):
    list_display = (
        "created_display",
        "source",
        "status_badge",
        "trigger",
        "duration_display",
        "items_total",
        "warnings_count",
        "runner",
    )
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("source", RelatedDropdownFilter),
        ("created_at", RangeDateTimeFilter),
    )
    list_filter_submit = True
    search_fields = ("source__name", "error", "result_locator")
    date_hierarchy = "created_at"
    list_fullwidth = True
    readonly_fields = (
        "source",
        "status",
        "trigger",
        "runner",
        "created_at",
        "started_at",
        "finished_at",
        "lease_expires_at",
        "items_total",
        "items_new",
        "items_updated",
        "counters",
        "result_locator",
        "error",
        "warnings_count",
        "log_lines",
        "log_view",
    )
    fieldsets = (
        ("Запуск", {"fields": (("source", "status", "trigger"), ("runner", "created_at"))}),
        ("Время", {"fields": (("started_at", "finished_at", "lease_expires_at"),)}),
        (
            "Результат",
            {
                "fields": (
                    ("items_total", "items_new", "items_updated"),
                    "counters",
                    "result_locator",
                    "error",
                ),
                "description": "Данные хранит парсер. Здесь только счётчики и ссылка на то, "
                "куда он их положил.",
            },
        ),
        ("Лог", {"fields": ("log_view",)}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Журнал не редактируется: страница открывается только на просмотр
        return False

    @display(description="создан", ordering="-created_at")
    def created_display(self, obj):
        return timezone.localtime(obj.created_at).strftime("%d.%m.%Y %H:%M:%S")

    @display(description="статус", label=STATUS_LABELS)
    def status_badge(self, obj):
        return obj.get_status_display()

    @display(description="длительность")
    def duration_display(self, obj):
        duration = obj.duration
        if duration is None:
            return "—"
        seconds = int(duration.total_seconds())
        if seconds < 60:
            return f"{seconds} с"
        return f"{seconds // 60} мин {seconds % 60} с"

    @display(description="")
    def log_view(self, obj):
        """Лента лога: хвост последних строк, цвет по уровню.

        Пока запуск идёт, страница обновляется сама — это и есть живой хвост.
        """
        tail = control_settings.LOG_TAIL_LINES
        entries = obj.logs.order_by("-seq")[:tail][::-1]

        if not entries:
            return format_html('<p style="color:#64748b">Строк лога нет</p>')

        rows = format_html_join(
            "",
            '<div style="display:flex;gap:12px;padding:2px 0">'
            '<span style="color:#94a3b8;white-space:nowrap">{}</span>'
            '<span style="color:{};min-width:72px">{}</span>'
            '<span style="white-space:pre-wrap;word-break:break-word">{}</span></div>',
            (
                (
                    timezone.localtime(entry.ts).strftime("%H:%M:%S"),
                    LEVEL_COLORS.get(entry.level, "#334155"),
                    entry.level,
                    entry.message,
                )
                for entry in entries
            ),
        )

        note = ""
        if obj.log_lines > tail:
            note = format_html(
                '<p style="color:#64748b;margin:0 0 8px">Показаны последние {} строк из {}</p>',
                tail,
                obj.log_lines,
            )

        refresh = ""
        if obj.is_active:
            refresh = format_html(
                '<p style="color:#d97706;margin:0 0 8px">Запуск идёт — страница обновится через 5 с</p>'
                '<meta http-equiv="refresh" content="5">'
            )

        return format_html(
            '{}{}<div style="font-family:ui-monospace,monospace;font-size:12.5px;'
            'background:#0f172a0d;border-radius:8px;padding:12px;max-height:640px;overflow:auto">{}</div>',
            refresh,
            note,
            rows,
        )


@admin.register(RunLog)
class RunLogAdmin(ModelAdmin):
    """Сквозной просмотр: например, все ошибки за сутки по всем источникам."""

    list_display = ("ts_display", "level_badge", "source_display", "message_short")
    list_filter = (
        ("level", ChoicesDropdownFilter),
        ("run__source", RelatedDropdownFilter),
        ("ts", RangeDateTimeFilter),
    )
    list_filter_submit = True
    search_fields = ("message",)
    date_hierarchy = "ts"
    list_fullwidth = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("run", "run__source")

    @display(description="время", ordering="-ts")
    def ts_display(self, obj):
        return timezone.localtime(obj.ts).strftime("%d.%m %H:%M:%S")

    @display(
        description="уровень",
        label={
            "DEBUG": "info",
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "danger",
            "CRITICAL": "danger",
        },
    )
    def level_badge(self, obj):
        return obj.level

    @display(description="источник")
    def source_display(self, obj):
        url = reverse("admin:control_run_change", args=[obj.run_id])
        return format_html('<a href="{}">{}</a>', url, obj.run.source.name)

    @display(description="сообщение")
    def message_short(self, obj):
        return obj.message[:160]
