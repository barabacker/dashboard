import logging

from django.core.management import call_command
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task

logger = logging.getLogger(__name__)


@db_task()
def say_hello(name="мир"):
    """Одноразовая задача: ставится в очередь по требованию.

    Из кода:      say_hello("Пётр")            — уходит в очередь
                  say_hello.call_local("Пётр") — выполняется здесь же
    Из консоли:   manage.py run_task say_hello --name Пётр
    """
    message = f"Привет, {name}!"
    logger.info(message)
    return message


@db_periodic_task(crontab(minute="30"))
def cleanup_expired_sessions():
    """Периодическая задача: каждый час в :30 чистит протухшие сессии.

    Расписание задаётся здесь, в коде: Huey читает его при старте
    процесса run_huey.
    """
    call_command("clearsessions")
    logger.info("Просроченные сессии удалены")
    return "ok"
