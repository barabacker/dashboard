import ast

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django_q.admin import FailAdmin as BaseFailAdmin
from django_q.admin import QueueAdmin as BaseQueueAdmin
from django_q.admin import ScheduleAdmin as BaseScheduleAdmin
from django_q.admin import TaskAdmin as BaseTaskAdmin
from django_q.models import Failure, OrmQ, Schedule, Success
from django_q.tasks import async_task
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateTimeFilter
from unfold.decorators import action, display

admin.site.index_title = "Обзор"


def environment_callback(request):
    """Бейдж окружения в шапке админки."""
    return ["Разработка", "warning"]


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    list_display = ("user_header", "email", "staff_badge", "active_badge", "last_login")
    list_filter = ("is_staff", "is_superuser", "is_active", ("last_login", RangeDateTimeFilter))
    list_filter_submit = True

    @display(description="пользователь", header=True, ordering="username")
    def user_header(self, obj):
        full_name = obj.get_full_name() or "—"
        return [obj.username, full_name, obj.username[:2].upper()]

    @display(description="админка", label={"да": "success", "нет": "info"})
    def staff_badge(self, obj):
        return "да" if obj.is_staff else "нет"

    @display(description="активен", boolean=True)
    def active_badge(self, obj):
        return obj.is_active


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    list_display = ("name", "users_count")

    @display(description="пользователей")
    def users_count(self, obj):
        return obj.user_set.count()


# Модели Django-Q2 регистрируются на стандартном ModelAdmin —
# перерегистрируем под Unfold, чтобы списки выглядели как остальная админка.
for model in (Schedule, Success, Failure, OrmQ):
    admin.site.unregister(model)


def enqueue_schedule(schedule):
    """Ставит задачу расписания в очередь немедленно.

    Аргументы разбираются так же, как это делает планировщик Django-Q2:
    в модели они хранятся строками. next_run при этом не сдвигается —
    очередной запуск по расписанию произойдёт как обычно.
    """
    args = ()
    kwargs = {}

    if schedule.args:
        args = ast.literal_eval(schedule.args)
        if not isinstance(args, tuple):
            args = (args,)

    if schedule.kwargs:
        try:
            kwargs = ast.literal_eval(schedule.kwargs)
        except (SyntaxError, ValueError):
            kwargs = {}

    q_options = kwargs.pop("q_options", {})
    if schedule.hook:
        q_options["hook"] = schedule.hook
    q_options["group"] = schedule.name or str(schedule.pk)

    return async_task(
        schedule.func,
        *args,
        task_name=f"Ручной запуск {schedule.pk}",
        q_options=q_options,
        **kwargs,
    )


@admin.register(Schedule)
class ScheduleAdmin(BaseScheduleAdmin, ModelAdmin):
    # Колонок меньше, чем в стандартном списке: иначе кнопка действия
    # уезжает за правый край и до неё приходится доскроллить
    list_display = ("name", "func", "schedule_type", "next_run", "get_last_run", "get_success")
    list_display_links = ("name",)
    # Кнопка в каждой строке списка и на странице расписания
    actions_row = ("run_now",)
    actions_detail = ("run_now",)

    @action(description="Запустить сейчас", icon="play_arrow")
    def run_now(self, request, object_id):
        schedule = get_object_or_404(Schedule, pk=object_id)
        task_id = enqueue_schedule(schedule)
        messages.success(
            request,
            f"«{schedule.name or schedule.func}» поставлена в очередь, id {task_id}. "
            "Результат появится в разделе «Выполненные».",
        )
        return redirect(reverse("admin:django_q_schedule_changelist"))


@admin.register(Success)
class SuccessAdmin(BaseTaskAdmin, ModelAdmin):
    pass


@admin.register(Failure)
class FailureAdmin(BaseFailAdmin, ModelAdmin):
    actions_row = ("retry",)
    actions_detail = ("retry",)

    @action(description="Перезапустить", icon="restart_alt")
    def retry(self, request, object_id):
        failure = get_object_or_404(Failure, pk=object_id)
        task_id = async_task(
            failure.func,
            *(failure.args or ()),
            task_name=f"Перезапуск {failure.name}",
            **(failure.kwargs or {}),
        )
        messages.success(request, f"Задача перезапущена, id {task_id}")
        return redirect(reverse("admin:django_q_failure_changelist"))


@admin.register(OrmQ)
class OrmQAdmin(BaseQueueAdmin, ModelAdmin):
    pass
