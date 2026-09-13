"""Заводит расписание очистки сессий.

Дальше оно правится в админке: «Задачи» → «Расписания». Миграция не
пересоздаёт запись, если её удалили или переименовали.
"""

from django.db import migrations

NAME = "Очистка просроченных сессий"
FUNC = "core.tasks.cleanup_expired_sessions"


def create_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.get_or_create(
        name=NAME,
        defaults={
            "func": FUNC,
            "schedule_type": "C",  # Schedule.CRON
            "cron": "30 * * * *",
            "repeats": -1,
        },
    )


def delete_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(name=NAME).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, delete_schedule),
    ]
