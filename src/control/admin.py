"""Django Admin is the primary UI.

Shape of the surface:

* **Collector** — read-only. It is a projection of code; editing it here would create a second,
  divergent source of truth. Only `enabled` is writable, and even that gets overwritten by the
  next `sync_collectors` run for keys that still exist in code.
* **Config** — the object people actually work with. Fully editable, schedules inline.
* **Job** — history. Immutable except for a cancellation request.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from collectors import schemas
from control.forms import ConfigForm
from control.models import (
    Collector,
    Config,
    Job,
    JobOrigin,
    JobStatus,
    Schedule,
)

admin.site.site_header = "Сбор данных"
admin.site.site_title = "Сбор данных"
admin.site.index_title = "Управление сбором"

_STATUS_COLORS = {
    JobStatus.PENDING: "#8a8a8a",
    JobStatus.RUNNING: "#0b6bcb",
    JobStatus.SUCCEEDED: "#1a7f37",
    JobStatus.FAILED: "#c92a2a",
    JobStatus.CANCELLED: "#9c6b00",
}


def _status_badge(status: str) -> SafeString:
    """Colour by the stored value, label from the choices — never the raw value on screen."""
    if not status:
        return format_html('<span style="color:#aaa">—</span>')
    color = _STATUS_COLORS.get(status, "#333")
    return format_html('<b style="color:{}">{}</b>', color, JobStatus(status).label)


@admin.register(Collector)
class CollectorAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "display_name",
        "known_versions",
        "current_version",
        "enabled",
        "synced_at",
    )
    list_filter = ("enabled",)
    search_fields = ("key", "display_name", "description")
    readonly_fields = (
        "key",
        "display_name",
        "description",
        "synced_at",
        "known_versions",
        "current_version",
        "schema_table",
    )
    fields = (
        "key",
        "display_name",
        "description",
        "enabled",
        "known_versions",
        "current_version",
        "schema_table",
        "synced_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Collectors appear by shipping code, not by filling in a form.
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Collector | None = None) -> bool:
        # Deprecate, never delete: Job history references these keys.
        return False

    @admin.display(description="Версии (из кода)")
    def known_versions(self, obj: Collector) -> str:
        try:
            return ", ".join(schemas.get_collector(obj.key).version_names)
        except schemas.UnknownCollector:
            return "— нет в кодовой базе —"

    @admin.display(description="Текущая версия")
    def current_version(self, obj: Collector) -> str:
        try:
            return schemas.current_version(obj.key)
        except schemas.UnknownCollector:
            return "—"

    @admin.display(description="Схема параметров (из кода)")
    def schema_table(self, obj: Collector) -> SafeString:
        try:
            descriptor = schemas.get_collector(obj.key)
        except schemas.UnknownCollector:
            return format_html("<i>Этого ключа больше нет в кодовой базе.</i>")

        rows = []
        for version in descriptor.versions:
            for spec in version.params:
                rows.append(
                    format_html(
                        "<tr><td>{}</td><td><code>{}</code></td><td>{}</td><td>{}</td>"
                        "<td><code>{}</code></td><td>{}</td></tr>",
                        version.version,
                        spec.name,
                        spec.kind,
                        "да" if spec.required else "",
                        "" if spec.default is None else repr(spec.default),
                        "ссылка на секрет" if spec.is_credential_ref else spec.description,
                    )
                )
        return format_html(
            "<table><thead><tr><th>версия</th><th>параметр</th><th>тип</th><th>обязателен</th>"
            "<th>по умолчанию</th><th>примечание</th></tr></thead><tbody>{}</tbody></table>",
            format_html("".join(rows)),
        )


class ScheduleInline(admin.TabularInline):
    model = Schedule
    extra = 0
    fields = ("cron", "timezone", "enabled", "overlap_policy", "catchup_policy", "last_fired_at")
    readonly_fields = ("last_fired_at",)
    show_change_link = True


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    form = ConfigForm
    inlines = [ScheduleInline]
    list_display = (
        "name",
        "collector_key",
        "enabled",
        "archived",
        "last_status_badge",
        "last_run_at",
        "last_job_link",
        "revision",
        "owner",
    )
    list_filter = ("collector_key", "enabled", "archived", "last_status")
    search_fields = ("name", "collector_key")
    autocomplete_fields = ("owner",)
    readonly_fields = (
        "revision",
        "created_by",
        "created_at",
        "updated_at",
        "last_status",
        "last_run_at",
        "last_job_link",
        "resolved_preview",
    )
    fieldsets = (
        (None, {"fields": ("name", "collector_key", "parameters", "resolved_preview")}),
        ("Состояние", {"fields": ("enabled", "archived", "tags", "owner")}),
        (
            "Последний запуск (кэш-колонки)",
            {"fields": ("last_status", "last_run_at", "last_job_link"), "classes": ("collapse",)},
        ),
        (
            "Аудит",
            {
                "fields": ("revision", "created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
    actions = [
        "action_run_now",
        "action_enable",
        "action_disable",
        "action_archive",
        "action_unarchive",
    ]

    def save_model(self, request: HttpRequest, obj: Config, form, change: bool) -> None:
        if not change:
            obj.created_by = request.user
            if obj.owner_id is None:
                obj.owner = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Последний статус", ordering="last_status")
    def last_status_badge(self, obj: Config) -> SafeString:
        return _status_badge(obj.last_status)

    @admin.display(description="Последняя задача")
    def last_job_link(self, obj: Config) -> SafeString:
        if not obj.last_job_id:
            return format_html("—")
        url = reverse("admin:control_job_change", args=[obj.last_job_id])
        return format_html('<a href="{}">Задача #{}</a>', url, obj.last_job_id)

    @admin.display(description="Итоговые параметры на текущей версии")
    def resolved_preview(self, obj: Config) -> SafeString:
        """Show exactly what a Job created right now would snapshot — or why it would not."""
        if not obj.pk:
            return format_html("<i>Сначала сохраните.</i>")
        try:
            version = schemas.current_version(obj.collector_key)
            effective = schemas.resolve_parameters(obj.collector_key, version, obj.parameters)
        except schemas.UnknownCollector:
            return format_html(
                '<b style="color:#c92a2a">Сборщика {} нет в кодовой базе — запустить нельзя.</b>',
                obj.collector_key,
            )
        except schemas.ParameterError as exc:
            return format_html(
                '<b style="color:#c92a2a">Не подходит для v{}:</b><ul>{}</ul>',
                exc.collector_version,
                format_html("".join(format_html("<li>{}</li>", e) for e in exc.errors)),
            )
        rows = format_html(
            "".join(
                format_html("<tr><td><code>{}</code></td><td><code>{}</code></td></tr>", k, repr(v))
                for k, v in sorted(effective.items())
            )
        )
        return format_html("v{}<table><tbody>{}</tbody></table>", version, rows)

    def _bulk(self, request: HttpRequest, queryset: QuerySet[Config], **updates) -> int:
        # Deliberately per-instance: `revision` is bumped in `Config.save()`, and a bulk
        # `queryset.update()` would route around it.
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

    @admin.action(description="В архив (мягкое удаление)")
    def action_archive(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, archived=True)
        self.message_user(request, f"Отправлено в архив: {n}.", messages.SUCCESS)

    @admin.action(description="Вернуть из архива")
    def action_unarchive(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, archived=False)
        self.message_user(request, f"Возвращено из архива: {n}.", messages.SUCCESS)


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "config",
        "cron",
        "timezone",
        "enabled",
        "overlap_policy",
        "catchup_policy",
        "last_fired_at",
    )
    list_filter = ("enabled", "overlap_policy", "catchup_policy", "timezone")
    search_fields = ("config__name", "cron")
    autocomplete_fields = ("config",)
    readonly_fields = ("last_fired_at", "created_at", "updated_at")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status_badge",
        "collector_key",
        "collector_version",
        "config_link",
        "origin",
        "attempt_no",
        "created_at",
        "duration",
    )
    list_filter = ("status", "collector_key", "collector_version", "origin", "cancel_requested")
    search_fields = ("collector_key", "claimed_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ["action_request_cancel"]

    readonly_fields = tuple(f.name for f in Job._meta.fields if f.name != "cancel_requested") + (
        "config_link",
        "duration",
    )
    fieldsets = (
        (
            "Снимок (неизменяем — запуск воспроизводится только по нему)",
            {
                "fields": (
                    "collector_key",
                    "collector_version",
                    "schema_version",
                    "effective_parameters",
                    "config_link",
                    "config_id",
                    "config_revision",
                )
            },
        ),
        ("Источник", {"fields": ("origin", "schedule_id", "fire_time", "requested_by")}),
        (
            "Состояние выполнения",
            {
                "fields": (
                    "status",
                    "attempt_no",
                    "claimed_by",
                    "claimed_until",
                    "cancel_requested",
                    "priority",
                    "available_at",
                )
            },
        ),
        (
            "Итог",
            {
                "fields": (
                    "started_at",
                    "finished_at",
                    "duration",
                    "metrics",
                    "result",
                    "structured_error",
                )
            },
        ),
        ("Аудит", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Jobs are produced by enqueue, never typed in.
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False

    @admin.display(description="Статус", ordering="status")
    def status_badge(self, obj: Job) -> SafeString:
        return _status_badge(obj.status)

    @admin.display(description="Конфигурация")
    def config_link(self, obj: Job) -> SafeString:
        config = Config.objects.filter(pk=obj.config_id).first()
        if config is None:
            return format_html("#{} (удалена)", obj.config_id)
        url = reverse("admin:control_config_change", args=[config.pk])
        return format_html('<a href="{}">{}</a> (рев. {})', url, config.name, obj.config_revision)

    @admin.display(description="Длительность")
    def duration(self, obj: Job) -> str:
        seconds = obj.duration_seconds
        return "—" if seconds is None else f"{seconds:.1f} с"

    @admin.action(description="Запросить отмену")
    def action_request_cancel(self, request: HttpRequest, queryset: QuerySet[Job]) -> None:
        from control.services import request_cancel

        cancelled, signalled, ignored = 0, 0, 0
        for job in queryset:
            outcome = request_cancel(job)
            if outcome == "cancelled":
                cancelled += 1
            elif outcome == "signalled":
                signalled += 1
            else:
                ignored += 1
        self.message_user(
            request,
            f"Отменено в очереди: {cancelled}. Сигнал отправлен выполняющимся: {signalled}. "
            f"Уже завершено: {ignored}.",
            messages.SUCCESS if (cancelled or signalled) else messages.WARNING,
        )
