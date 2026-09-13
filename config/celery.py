import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("dashboard")
# Настройки берутся из settings.py, префикс CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")
# Задачи ищутся в tasks.py каждого приложения из INSTALLED_APPS
app.autodiscover_tasks()
