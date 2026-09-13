from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateTimeFilter
from unfold.decorators import display

admin.site.index_title = "Обзор"


def plural(n, forms):
    """Русские числовые формы: plural(5, ("группа", "группы", "групп"))."""
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def environment_callback(request):
    """Бейдж окружения в шапке админки."""
    return ["Разработка", "warning"]


def dashboard_callback(request, context):
    """Данные для главной страницы админки.

    Пока считает только то, что реально есть в базе. По мере появления
    доменных моделей сюда добавляются их метрики.
    """
    now = timezone.now()
    users = User.objects.all()
    active = users.filter(is_active=True).count()
    superusers = users.filter(is_superuser=True).count()
    logins = users.filter(last_login__gte=now - timezone.timedelta(days=7)).count()

    context.update(
        {
            "kpi": [
                {
                    "title": "Пользователей",
                    "metric": users.count(),
                    "footer": f"{active} {plural(active, ('активный', 'активных', 'активных'))}",
                    "icon": "person",
                },
                {
                    "title": "С доступом в админку",
                    "metric": users.filter(is_staff=True).count(),
                    "footer": f"{superusers} {plural(superusers, ('суперпользователь', 'суперпользователя', 'суперпользователей'))}",
                    "icon": "shield_person",
                },
                {
                    "title": "Групп",
                    "metric": Group.objects.count(),
                    "footer": "Наборы прав",
                    "icon": "groups",
                },
                {
                    "title": "Входов за неделю",
                    "metric": logins,
                    "footer": f"{plural(logins, ('уникальный пользователь', 'уникальных пользователя', 'уникальных пользователей'))}".capitalize(),
                    "icon": "login",
                },
            ],
        }
    )
    return context


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
