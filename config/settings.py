from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-demo-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "leaflet",
    "fleet",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# GeoDjango на SQLite: движок spatialite, расширение mod_spatialite грузится в
# каждое соединение. GDAL/GEOS подхватываются через системные библиотеки.
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.spatialite",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
SPATIALITE_LIBRARY_PATH = "mod_spatialite"

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Тайлы — локальные, сгенерированы офлайн (tools/make_tiles.py).
# В обычном окружении сюда ставится OSM: https://tile.openstreetmap.org/{z}/{x}/{y}.png
LEAFLET_CONFIG = {
    "DEFAULT_CENTER": (55.75, 37.62),
    "DEFAULT_ZOOM": 5,
    "MIN_ZOOM": 3,
    "MAX_ZOOM": 7,
    "TILES": [("Схема", "/static/tiles/{z}/{x}/{y}.png", {"attribution": "GSHHS / офлайн-подложка"})],
    "RESET_VIEW": False,
    "SCALE": "metric",
}

UNFOLD = {
    "SITE_TITLE": "Телеметрия",
    "SITE_HEADER": "Телеметрия автопарка",
    "SITE_SUBHEADER": "Django + Unfold + SpatiaLite + GDAL",
    "SITE_SYMBOL": "local_shipping",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "ENVIRONMENT": "fleet.admin.environment_callback",
    "DASHBOARD_CALLBACK": "fleet.admin.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "oklch(97.7% .013 236.62)",
            "100": "oklch(95.1% .026 236.82)",
            "200": "oklch(90.1% .058 230.9)",
            "300": "oklch(82.8% .111 230.318)",
            "400": "oklch(74.6% .16 232.661)",
            "500": "oklch(68.5% .169 237.323)",
            "600": "oklch(58.8% .158 241.966)",
            "700": "oklch(50% .134 242.749)",
            "800": "oklch(44.3% .11 240.79)",
            "900": "oklch(39.1% .09 240.876)",
            "950": "oklch(29.3% .066 243.157)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Обзор",
                "separator": False,
                "items": [
                    {
                        "title": "Дашборд",
                        "icon": "dashboard",
                        "link": "/admin/",
                    },
                ],
            },
            {
                "title": "Автопарк",
                "separator": True,
                "items": [
                    {
                        "title": "Транспорт",
                        "icon": "local_shipping",
                        "link": "/admin/fleet/vehicle/",
                    },
                    {
                        "title": "Рейсы",
                        "icon": "route",
                        "link": "/admin/fleet/trip/",
                    },
                    {
                        "title": "Геозоны",
                        "icon": "pentagon",
                        "link": "/admin/fleet/zone/",
                    },
                    {
                        "title": "События",
                        "icon": "notifications_active",
                        "link": "/admin/fleet/alert/",
                    },
                ],
            },
            {
                "title": "Доступ",
                "separator": True,
                "items": [
                    {
                        "title": "Пользователи",
                        "icon": "person",
                        "link": "/admin/auth/user/",
                    },
                    {
                        "title": "Группы",
                        "icon": "groups",
                        "link": "/admin/auth/group/",
                    },
                ],
            },
        ],
    },
    "TABS": [
        {
            "models": ["fleet.vehicle", "fleet.trip"],
            "items": [
                {"title": "Транспорт", "link": "/admin/fleet/vehicle/"},
                {"title": "Рейсы", "link": "/admin/fleet/trip/"},
            ],
        },
    ],
}
