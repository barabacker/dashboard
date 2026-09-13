import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-change-me-before-deploy")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    # Unfold должен идти до django.contrib.admin — он подменяет шаблоны админки
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
    "django_celery_beat",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Celery: брокер — Redis, расписания периодических задач хранятся в БД
# и правятся в админке (django-celery-beat).
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# В тестах задачи выполняются синхронно, брокер не нужен
CELERY_TASK_ALWAYS_EAGER = False

LOGIN_REDIRECT_URL = "/admin/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

UNFOLD = {
    "SITE_TITLE": "Dashboard",
    "SITE_HEADER": "Dashboard",
    "SITE_SUBHEADER": "Панель управления",
    "SITE_SYMBOL": "dashboard",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "ENVIRONMENT": "core.admin.environment_callback",
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
                "title": "Доступ",
                "separator": False,
                "items": [
                    {"title": "Пользователи", "icon": "person", "link": "/admin/auth/user/"},
                    {"title": "Группы", "icon": "groups", "link": "/admin/auth/group/"},
                ],
            },
            {
                "title": "Задачи",
                "separator": True,
                "items": [
                    {
                        "title": "Периодические задачи",
                        "icon": "schedule",
                        "link": "/admin/django_celery_beat/periodictask/",
                    },
                    {
                        "title": "Расписания cron",
                        "icon": "calendar_month",
                        "link": "/admin/django_celery_beat/crontabschedule/",
                    },
                    {
                        "title": "Интервалы",
                        "icon": "timer",
                        "link": "/admin/django_celery_beat/intervalschedule/",
                    },
                ],
            },
        ],
    },
}
