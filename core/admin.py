from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django_q.admin import FailAdmin as BaseFailAdmin
from django_q.admin import QueueAdmin as BaseQueueAdmin
from django_q.admin import ScheduleAdmin as BaseScheduleAdmin
from django_q.admin import TaskAdmin as BaseTaskAdmin
from django_q.models import Failure, OrmQ, Schedule, Success
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


# Модели Django-Q2 регистрируются на стандартном ModelAdmin —
# перерегистрируем под Unfold, чтобы списки выглядели как остальная админка.
for model in (Schedule, Success, Failure, OrmQ):
    admin.site.unregister(model)


@admin.register(Schedule)
class ScheduleAdmin(BaseScheduleAdmin, ModelAdmin):
    pass


@admin.register(Success)
class SuccessAdmin(BaseTaskAdmin, ModelAdmin):
    pass


@admin.register(Failure)
class FailureAdmin(BaseFailAdmin, ModelAdmin):
    pass


@admin.register(OrmQ)
class OrmQAdmin(BaseQueueAdmin, ModelAdmin):
    pass
