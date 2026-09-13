import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def say_hello(name="мир"):
    """Одноразовая задача: ставится в очередь по требованию.

    Из кода:      say_hello.delay("Пётр")
    Из консоли:   manage.py run_task say_hello --name Пётр
    Из админки:   Clocked-расписание + флаг «одноразовая задача»
    """
    message = f"Привет, {name}!"
    logger.info(message)
    return message


@shared_task
def cleanup_expired_sessions():
    """Периодическая задача: чистит протухшие сессии.

    Расписание (раз в час) заводится миграцией core/0002 и дальше
    редактируется в админке без деплоя.
    """
    call_command("clearsessions")
    logger.info("Просроченные сессии удалены")
    return "ok"
