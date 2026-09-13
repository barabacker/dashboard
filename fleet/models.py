from django.contrib.gis.db import models
from django.utils import timezone


class Zone(models.Model):
    """Геозона: полигон в WGS84, хранится в SpatiaLite."""

    class Kind(models.TextChoices):
        DEPOT = "depot", "Депо"
        CLIENT = "client", "Клиентская зона"
        RESTRICTED = "restricted", "Запретная зона"

    name = models.CharField("название", max_length=120)
    kind = models.CharField("тип", max_length=16, choices=Kind.choices, default=Kind.CLIENT)
    is_active = models.BooleanField("активна", default=True)
    area = models.PolygonField("контур", srid=4326)
    created_at = models.DateTimeField("создана", default=timezone.now)

    class Meta:
        verbose_name = "геозона"
        verbose_name_plural = "геозоны"
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def area_km2(self):
        """Площадь в км² — считается в проекции 3857 средствами GEOS/GDAL."""
        return round(self.area.transform(3857, clone=True).area / 1_000_000, 1)


class Vehicle(models.Model):
    """Единица техники с последней известной позицией (PointField)."""

    class Status(models.TextChoices):
        MOVING = "moving", "В движении"
        IDLE = "idle", "Стоянка"
        SERVICE = "service", "На ТО"
        OFFLINE = "offline", "Нет связи"

    plate = models.CharField("госномер", max_length=16, unique=True)
    model = models.CharField("модель", max_length=64)
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.IDLE)
    home_zone = models.ForeignKey(
        Zone,
        verbose_name="домашняя зона",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    location = models.PointField("позиция", srid=4326, null=True, blank=True)
    speed_kmh = models.PositiveSmallIntegerField("скорость, км/ч", default=0)
    fuel_pct = models.PositiveSmallIntegerField("топливо, %", default=100)
    odometer_km = models.PositiveIntegerField("пробег, км", default=0)
    last_seen = models.DateTimeField("последний пакет", default=timezone.now)

    class Meta:
        verbose_name = "транспорт"
        verbose_name_plural = "транспорт"
        ordering = ("plate",)

    def __str__(self):
        return f"{self.plate} · {self.model}"


class Trip(models.Model):
    """Рейс: трек как LineString."""

    vehicle = models.ForeignKey(
        Vehicle, verbose_name="транспорт", on_delete=models.CASCADE, related_name="trips"
    )
    started_at = models.DateTimeField("начало")
    finished_at = models.DateTimeField("окончание", null=True, blank=True)
    origin = models.CharField("откуда", max_length=120)
    destination = models.CharField("куда", max_length=120)
    track = models.LineStringField("трек", srid=4326, null=True, blank=True)
    distance_km = models.DecimalField("расстояние, км", max_digits=8, decimal_places=1, default=0)
    cargo_tons = models.DecimalField("груз, т", max_digits=6, decimal_places=2, default=0)

    class Meta:
        verbose_name = "рейс"
        verbose_name_plural = "рейсы"
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.origin} → {self.destination}"


class Alert(models.Model):
    """Событие телеметрии, привязанное к точке."""

    class Level(models.TextChoices):
        INFO = "info", "Инфо"
        WARNING = "warning", "Предупреждение"
        CRITICAL = "critical", "Критично"

    vehicle = models.ForeignKey(
        Vehicle, verbose_name="транспорт", on_delete=models.CASCADE, related_name="alerts"
    )
    level = models.CharField("уровень", max_length=16, choices=Level.choices, default=Level.INFO)
    message = models.CharField("сообщение", max_length=200)
    point = models.PointField("место", srid=4326, null=True, blank=True)
    is_resolved = models.BooleanField("обработано", default=False)
    created_at = models.DateTimeField("время", default=timezone.now)

    class Meta:
        verbose_name = "событие"
        verbose_name_plural = "события"
        ordering = ("-created_at",)

    def __str__(self):
        return self.message
