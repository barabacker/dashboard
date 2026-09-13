from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.html import format_html
from leaflet.admin import LeafletGeoAdminMixin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateTimeFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import display

from .models import Alert, Trip, Vehicle, Zone


def environment_callback(request):
    """Бейдж окружения в шапке."""
    return ["Демо-стенд", "warning"]


def dashboard_callback(request, context):
    """Данные для главной страницы админки."""
    now = timezone.now()
    total = Vehicle.objects.count()
    by_status = dict(
        Vehicle.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    week = Trip.objects.filter(started_at__gte=now - timedelta(days=7))

    context.update(
        {
            "kpi": [
                {
                    "title": "Транспорт на линии",
                    "metric": f"{by_status.get(Vehicle.Status.MOVING, 0)} / {total}",
                    "footer": "Передают координаты сейчас",
                    "icon": "local_shipping",
                },
                {
                    "title": "Рейсов за неделю",
                    "metric": week.count(),
                    "footer": f"{week.aggregate(s=Sum('distance_km'))['s'] or 0:.0f} км суммарно",
                    "icon": "route",
                },
                {
                    "title": "Активных геозон",
                    "metric": Zone.objects.filter(is_active=True).count(),
                    "footer": "Полигоны в SpatiaLite",
                    "icon": "pentagon",
                },
                {
                    "title": "Событий без обработки",
                    "metric": Alert.objects.filter(is_resolved=False).count(),
                    "footer": f"{Alert.objects.filter(level=Alert.Level.CRITICAL, is_resolved=False).count()} критичных",
                    "icon": "notifications_active",
                },
            ],
            "statuses": [
                {
                    "label": label,
                    "count": by_status.get(value, 0),
                    "share": round(100 * by_status.get(value, 0) / total) if total else 0,
                    "color": color,
                }
                for value, label, color in (
                    (Vehicle.Status.MOVING, "В движении", "bg-green-500"),
                    (Vehicle.Status.IDLE, "Стоянка", "bg-blue-500"),
                    (Vehicle.Status.SERVICE, "На ТО", "bg-amber-500"),
                    (Vehicle.Status.OFFLINE, "Нет связи", "bg-red-500"),
                )
            ],
            "recent_alerts": Alert.objects.select_related("vehicle")[:6],
        }
    )
    return context


@admin.register(Zone)
class ZoneAdmin(LeafletGeoAdminMixin, ModelAdmin):
    list_display = ("name", "kind_badge", "area_display", "vehicles_count", "active_badge")
    list_filter = (("kind", ChoicesDropdownFilter), "is_active")
    search_fields = ("name",)
    list_filter_submit = True
    compressed_fields = True
    fieldsets = (
        ("Геозона", {"fields": ("name", "kind", "is_active")}),
        ("География", {"fields": ("area",), "description": "PolygonField, SRID 4326 — рисуется прямо на карте"}),
    )

    @display(description="тип", label={"Депо": "info", "Клиентская зона": "success", "Запретная зона": "danger"})
    def kind_badge(self, obj):
        return obj.get_kind_display()

    @display(description="площадь", ordering="name")
    def area_display(self, obj):
        return f"{obj.area_km2} км²"

    @display(description="техника")
    def vehicles_count(self, obj):
        return obj.vehicles.count()

    @display(description="статус", boolean=True)
    def active_badge(self, obj):
        return obj.is_active


class AlertInline(admin.TabularInline):
    model = Alert
    extra = 0
    fields = ("level", "message", "created_at", "is_resolved")
    readonly_fields = ("created_at",)
    tab = True


class TripInline(admin.TabularInline):
    model = Trip
    extra = 0
    fields = ("origin", "destination", "started_at", "distance_km", "cargo_tons")
    tab = True


@admin.register(Vehicle)
class VehicleAdmin(LeafletGeoAdminMixin, ModelAdmin):
    list_display = ("vehicle_header", "status_badge", "fuel_bar", "speed_display", "home_zone", "last_seen")
    list_filter = (
        ("status", ChoicesDropdownFilter),
        ("home_zone", RelatedDropdownFilter),
        ("fuel_pct", RangeNumericFilter),
        ("last_seen", RangeDateTimeFilter),
    )
    list_filter_submit = True
    search_fields = ("plate", "model")
    autocomplete_fields = ("home_zone",)
    list_fullwidth = True
    inlines = (TripInline, AlertInline)
    readonly_fields = ("last_seen",)
    fieldsets = (
        ("Машина", {"fields": (("plate", "model"), ("status", "home_zone"))}),
        ("Телеметрия", {"fields": (("speed_kmh", "fuel_pct", "odometer_km"), "last_seen")}),
        ("Позиция", {"fields": ("location",), "description": "PointField, SRID 4326"}),
    )

    @display(
        description="статус",
        label={
            "В движении": "success",
            "Стоянка": "info",
            "На ТО": "warning",
            "Нет связи": "danger",
        },
    )
    def status_badge(self, obj):
        return obj.get_status_display()

    @display(description="транспорт", header=True, ordering="plate")
    def vehicle_header(self, obj):
        """Заголовок строки: госномер, модель и инициалы-аватар."""
        return [obj.plate, obj.model, obj.plate[:2]]

    @display(description="топливо", ordering="fuel_pct")
    def fuel_bar(self, obj):
        color = "#16a34a" if obj.fuel_pct > 50 else "#f59e0b" if obj.fuel_pct > 20 else "#dc2626"
        return format_html(
            '<div class="flex items-center gap-2">'
            '<div style="width:72px;height:6px;border-radius:3px;background:#e5e7eb">'
            '<div style="width:{}%;height:6px;border-radius:3px;background:{}"></div></div>'
            "<span>{}%</span></div>",
            obj.fuel_pct,
            color,
            obj.fuel_pct,
        )

    @display(description="скорость", ordering="speed_kmh")
    def speed_display(self, obj):
        return f"{obj.speed_kmh} км/ч"


@admin.register(Trip)
class TripAdmin(LeafletGeoAdminMixin, ModelAdmin):
    list_display = ("route_display", "vehicle", "started_at", "distance_km", "cargo_tons")
    list_filter = (("vehicle", RelatedDropdownFilter), ("started_at", RangeDateTimeFilter))
    list_filter_submit = True
    search_fields = ("origin", "destination", "vehicle__plate")
    date_hierarchy = "started_at"
    fieldsets = (
        ("Рейс", {"fields": ("vehicle", ("origin", "destination"), "started_at", "finished_at")}),
        ("Показатели", {"fields": (("distance_km", "cargo_tons"),)}),
        ("Трек", {"fields": ("track",), "description": "LineStringField — маршрут по точкам телеметрии"}),
    )

    @display(description="маршрут")
    def route_display(self, obj):
        return f"{obj.origin} → {obj.destination}"


@admin.register(Alert)
class AlertAdmin(LeafletGeoAdminMixin, ModelAdmin):
    list_display = ("message", "level_badge", "vehicle", "created_at", "resolved_badge")
    list_filter = (("level", ChoicesDropdownFilter), "is_resolved", ("created_at", RangeDateTimeFilter))
    list_filter_submit = True
    search_fields = ("message", "vehicle__plate")

    @display(description="уровень", label={"Инфо": "info", "Предупреждение": "warning", "Критично": "danger"})
    def level_badge(self, obj):
        return obj.get_level_display()

    @display(description="обработано", boolean=True)
    def resolved_badge(self, obj):
        return obj.is_resolved


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    pass


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
