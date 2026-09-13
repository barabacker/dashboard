from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django_celery_beat.admin import ClockedScheduleAdmin as BaseClockedScheduleAdmin
from django_celery_beat.admin import CrontabScheduleAdmin as BaseCrontabScheduleAdmin
from django_celery_beat.admin import PeriodicTaskAdmin as BasePeriodicTaskAdmin
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateTimeFilter
from unfold.decorators import display

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


# django-celery-beat регистрирует свои модели на стандартном ModelAdmin —
# перерегистрируем под Unfold, чтобы списки выглядели как остальная админка.
# Форму PeriodicTask это не затрагивает: у неё собственные виджеты.
for model in (PeriodicTask, IntervalSchedule, CrontabSchedule, SolarSchedule, ClockedSchedule):
    admin.site.unregister(model)


@admin.register(PeriodicTask)
class PeriodicTaskAdmin(BasePeriodicTaskAdmin, ModelAdmin):
    pass


@admin.register(CrontabSchedule)
class CrontabScheduleAdmin(BaseCrontabScheduleAdmin, ModelAdmin):
    pass


@admin.register(ClockedSchedule)
class ClockedScheduleAdmin(BaseClockedScheduleAdmin, ModelAdmin):
    pass


@admin.register(IntervalSchedule)
class IntervalScheduleAdmin(ModelAdmin):
    pass


@admin.register(SolarSchedule)
class SolarScheduleAdmin(ModelAdmin):
    pass
