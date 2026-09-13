import logging

from django.core.management import call_command

logger = logging.getLogger(__name__)

# Задачи Django-Q2 — обычные функции. В очередь ставятся по строковому пути:
#     from django_q.tasks import async_task
#     async_task("core.tasks.say_hello", "Пётр")


def say_hello(name="мир"):
    """Одноразовая задача: ставится в очередь по требованию."""
    message = f"Привет, {name}!"
    logger.info(message)
    return message


def cleanup_expired_sessions():
    """Периодическая задача: чистит протухшие сессии.

    Расписание (каждый час в :30) заводит миграция core/0001 и дальше
    оно редактируется в админке без деплоя.
    """
    call_command("clearsessions")
    logger.info("Просроченные сессии удалены")
    return "ok"
