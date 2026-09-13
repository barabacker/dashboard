from django.core.management.base import BaseCommand, CommandError
from django_q.tasks import async_task

from core import tasks

TASKS = ("say_hello", "cleanup_expired_sessions")


class Command(BaseCommand):
    help = "Поставить задачу в очередь: manage.py run_task say_hello --name Пётр"

    def add_arguments(self, parser):
        parser.add_argument("task", choices=TASKS)
        parser.add_argument("--name", default="мир", help="аргумент для say_hello")
        parser.add_argument(
            "--now",
            action="store_true",
            help="выполнить сразу в этом процессе, не отправляя в очередь",
        )

    def handle(self, *args, **options):
        name = options["task"]
        args_ = (options["name"],) if name == "say_hello" else ()

        if options["now"]:
            self.stdout.write(self.style.SUCCESS(str(getattr(tasks, name)(*args_))))
            return

        try:
            task_id = async_task(f"core.tasks.{name}", *args_, task_name=name)
        except Exception as exc:
            raise CommandError(f"Не удалось поставить задачу в очередь: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Задача отправлена в очередь, id {task_id}"))
