from django.core.management.base import BaseCommand, CommandError

from core import tasks


class Command(BaseCommand):
    help = "Поставить задачу в очередь: manage.py run_task say_hello --name Пётр"

    def add_arguments(self, parser):
        parser.add_argument("task", choices=["say_hello", "cleanup_expired_sessions"])
        parser.add_argument("--name", default="мир", help="аргумент для say_hello")
        parser.add_argument(
            "--now",
            action="store_true",
            help="выполнить сразу в этом процессе, не отправляя в очередь",
        )

    def handle(self, *args, **options):
        task = getattr(tasks, options["task"])
        kwargs = {"name": options["name"]} if options["task"] == "say_hello" else {}

        if options["now"]:
            self.stdout.write(self.style.SUCCESS(str(task(**kwargs))))
            return

        try:
            result = task.delay(**kwargs)
        except Exception as exc:  # брокер недоступен
            raise CommandError(f"Не удалось поставить задачу в очередь: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Задача отправлена в очередь, id {result.id}"))
