"""Заводит периодическую задачу очистки сессий.

Дальше расписание правится в админке: можно поменять cron, выключить
задачу или удалить — миграция её не пересоздаст.
"""

from django.db import migrations

TASK_NAME = "Очистка просроченных сессий"
TASK_PATH = "core.tasks.cleanup_expired_sessions"


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    # каждый час в :30
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name=TASK_NAME,
        defaults={
            "task": TASK_PATH,
            "crontab": schedule,
            "description": "Удаляет протухшие записи django_session",
        },
    )


def delete_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, delete_periodic_task),
    ]
