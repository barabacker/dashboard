import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import LineString, Point, Polygon
from django.core.management.base import BaseCommand
from django.utils import timezone

from fleet.models import Alert, Trip, Vehicle, Zone

CITIES = {
    "Москва": (37.62, 55.75),
    "Санкт-Петербург": (30.31, 59.94),
    "Нижний Новгород": (44.00, 56.33),
    "Казань": (49.11, 55.80),
    "Воронеж": (39.20, 51.67),
    "Ярославль": (39.87, 57.63),
    "Тула": (37.62, 54.19),
    "Смоленск": (32.05, 54.78),
}

MODELS = [
    "КАМАЗ 5490",
    "Volvo FH 460",
    "Scania R450",
    "MAN TGX 18.440",
    "Mercedes Actros 1845",
    "ГАЗель Next",
]


def box(lon, lat, d):
    return Polygon(
        ((lon - d, lat - d), (lon + d, lat - d), (lon + d, lat + d), (lon - d, lat + d), (lon - d, lat - d)),
        srid=4326,
    )


class Command(BaseCommand):
    help = "Наполняет демо-стенд данными"

    def handle(self, *args, **options):
        random.seed(42)
        now = timezone.now()

        Alert.objects.all().delete()
        Trip.objects.all().delete()
        Vehicle.objects.all().delete()
        Zone.objects.all().delete()

        zones = []
        for (city, (lon, lat)), kind in zip(
            CITIES.items(),
            [Zone.Kind.DEPOT, Zone.Kind.DEPOT, Zone.Kind.CLIENT, Zone.Kind.CLIENT,
             Zone.Kind.CLIENT, Zone.Kind.RESTRICTED, Zone.Kind.CLIENT, Zone.Kind.RESTRICTED],
        ):
            zones.append(
                Zone.objects.create(
                    name=f"{'Депо' if kind == Zone.Kind.DEPOT else 'Зона'} «{city}»",
                    kind=kind,
                    is_active=kind != Zone.Kind.RESTRICTED or random.random() > 0.5,
                    area=box(lon, lat, random.uniform(0.25, 0.7)),
                )
            )

        statuses = (
            [Vehicle.Status.MOVING] * 7
            + [Vehicle.Status.IDLE] * 4
            + [Vehicle.Status.SERVICE] * 2
            + [Vehicle.Status.OFFLINE] * 1
        )
        letters = "АВЕКМНОРСТУХ"
        vehicles = []
        for i, status in enumerate(statuses):
            city, (lon, lat) = random.choice(list(CITIES.items()))
            moving = status == Vehicle.Status.MOVING
            vehicles.append(
                Vehicle.objects.create(
                    plate=f"{random.choice(letters)}{100 + i}{random.choice(letters)}{random.choice(letters)} {random.choice([77, 78, 50, 52, 16])}",
                    model=random.choice(MODELS),
                    status=status,
                    home_zone=random.choice(zones),
                    location=Point(
                        lon + random.uniform(-1.5, 1.5), lat + random.uniform(-1.0, 1.0), srid=4326
                    ),
                    speed_kmh=random.randint(45, 95) if moving else 0,
                    fuel_pct=random.randint(8, 100),
                    odometer_km=random.randint(40_000, 480_000),
                    last_seen=now - timedelta(minutes=random.randint(1, 240)),
                )
            )

        names = list(CITIES)
        for i in range(24):
            origin, destination = random.sample(names, 2)
            a, b = CITIES[origin], CITIES[destination]
            steps = 6
            track = LineString(
                [
                    (
                        a[0] + (b[0] - a[0]) * s / steps + random.uniform(-0.25, 0.25),
                        a[1] + (b[1] - a[1]) * s / steps + random.uniform(-0.25, 0.25),
                    )
                    for s in range(steps + 1)
                ],
                srid=4326,
            )
            started = now - timedelta(days=random.randint(0, 13), hours=random.randint(0, 20))
            Trip.objects.create(
                vehicle=random.choice(vehicles),
                started_at=started,
                finished_at=started + timedelta(hours=random.randint(4, 30)),
                origin=origin,
                destination=destination,
                track=track,
                # Длина трека в километрах — считается GEOS в проекции 3857
                distance_km=round(track.transform(3857, clone=True).length / 1000, 1),
                cargo_tons=round(random.uniform(1.5, 21.0), 2),
            )

        messages = [
            (Alert.Level.CRITICAL, "Выход из геозоны без задания"),
            (Alert.Level.CRITICAL, "Резкое торможение, возможен инцидент"),
            (Alert.Level.WARNING, "Остаток топлива ниже 15%"),
            (Alert.Level.WARNING, "Превышение скорости на 24 км/ч"),
            (Alert.Level.WARNING, "Отклонение от маршрута 12 км"),
            (Alert.Level.INFO, "Прибытие в депо"),
            (Alert.Level.INFO, "Начало рейса"),
            (Alert.Level.INFO, "Плановое ТО пройдено"),
        ]
        for i in range(30):
            level, message = random.choice(messages)
            vehicle = random.choice(vehicles)
            Alert.objects.create(
                vehicle=vehicle,
                level=level,
                message=message,
                point=vehicle.location,
                is_resolved=random.random() > 0.45,
                created_at=now - timedelta(hours=random.randint(0, 96)),
            )

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin12345")

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: {Zone.objects.count()} зон, {Vehicle.objects.count()} машин, "
                f"{Trip.objects.count()} рейсов, {Alert.objects.count()} событий"
            )
        )
