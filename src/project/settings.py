"""Django settings for the data-collection back office.

One deployment, one database, one settings module. Environment-driven via django-environ.
"""

from pathlib import Path

import environ
from django.urls import reverse_lazy

#: The repository root — src/project/settings.py -> src/project -> src -> repo root.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, "dev-insecure-secret-key-change-me"),
    DJANGO_ALLOWED_HOSTS=(list, ["*"]),
    DJANGO_TIME_ZONE=(str, "UTC"),
    POSTGRES_DB=(str, "dashboard"),
    POSTGRES_USER=(str, "dashboard"),
    POSTGRES_PASSWORD=(str, "dashboard"),
    POSTGRES_HOST=(str, "127.0.0.1"),
    POSTGRES_PORT=(int, 5432),
    WORKER_LEASE_SECONDS=(int, 900),
    WORKER_POLL_SECONDS=(float, 1.0),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "control",
    "execution",
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

ROOT_URLCONF = "project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Filesystem loader runs before the per-app one, so a same-path template placed here wins
        # over the matching template shipped inside an installed app (e.g. unfold's own) — that is
        # what lets control/templates/unfold/... override an unfold template without depending on
        # INSTALLED_APPS ordering.
        "DIRS": [BASE_DIR / "src" / "control" / "templates"],
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

WSGI_APPLICATION = "project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
# Storage stays UTC (USE_TZ); this only decides how instants are rendered in the admin and the
# dashboard. Set DJANGO_TIME_ZONE=Europe/Moscow to read local times instead.
TIME_ZONE = env("DJANGO_TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_REDIRECT_URL = "/dashboard/"
LOGIN_URL = "/admin/login/"

# Unfold reads its own chrome strings from here rather than from admin.site.site_header.
#
# The sidebar is fully hand-authored (Unfold's per-model auto-listing is off the moment
# SIDEBAR.navigation is non-empty), grouped the way the work actually flows: what to collect,
# then what ran, then the read-only projection of code, then who gets to administer the admin
# itself. "Пользователи"/"Группы" carry an explicit `permission` check — `has_permission` defaults
# to True for an item that omits it, so leaving it off would show the item to everyone regardless
# of Django permissions. The dotted path is a string, not an import, so it is resolved lazily per
# request rather than at settings load time, when `control.admin` may not exist yet.
UNFOLD = {
    "SITE_TITLE": "Сбор данных",
    "SITE_HEADER": "Сбор данных",
    "SHOW_LANGUAGES": False,
    "SIDEBAR": {
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Обзор",
                "items": [
                    {
                        "title": "Дашборд",
                        "icon": "dashboard",
                        "link": reverse_lazy("dashboard:index"),
                    },
                ],
            },
            {
                "title": "Сбор данных",
                "items": [
                    {
                        # D22: «Источники» and «Конфигурации» merged into the one Config admin —
                        # one sidebar entry, not two.
                        "title": "Источники",
                        "icon": "language",
                        "link": reverse_lazy("admin:control_config_changelist"),
                    },
                    {
                        "title": "Расписания",
                        "icon": "calendar_month",
                        "link": reverse_lazy("admin:control_schedule_changelist"),
                    },
                    {
                        "title": "Задачи",
                        "icon": "list_alt",
                        "link": reverse_lazy("admin:control_job_changelist"),
                    },
                ],
            },
            {
                "title": "Код",
                "items": [
                    {
                        "title": "Сборщики",
                        "icon": "extension",
                        "link": reverse_lazy("admin:control_collector_changelist"),
                    },
                ],
            },
            {
                "title": "Доступ",
                "items": [
                    {
                        "title": "Пользователи",
                        "icon": "person",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                        "permission": "control.admin.can_view_users",
                    },
                    {
                        "title": "Группы",
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": "control.admin.can_view_groups",
                    },
                ],
            },
        ],
    },
}

# --- Execution runtime knobs (§7, §9) -------------------------------------------------
# A generous lease is preferred over frequent renewal; renewal exists but is not a heartbeat.
WORKER_LEASE_SECONDS = env("WORKER_LEASE_SECONDS")
WORKER_POLL_SECONDS = env("WORKER_POLL_SECONDS")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
