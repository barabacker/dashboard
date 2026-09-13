"""Обслуживание control plane: просроченные запуски и чистка истории.

Вешается на системный планировщик (cron, systemd timer, Планировщик заданий):
    manage.py maintenance
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from control.conf import control_settings
from control.models import Run, RunLog
from control.services import expire_stale_runs


class Command(BaseCommand):
    help = "Пометить зависшие запуски просроченными и удалить старые логи"

    def add_arguments(self, parser):
        parser.add_argument(
            "--log-days",
            type=int,
            default=control_settings.LOG_RETENTION_DAYS,
            help="сколько дней хранить строки логов",
        )
        parser.add_argument(
            "--run-days",
            type=int,
            default=control_settings.RUN_RETENTION_DAYS,
            help="сколько дней хранить сами запуски",
        )
        parser.add_argument("--dry-run", action="store_true", help="только показать, что будет удалено")

    def handle(self, *args, **options):
        now = timezone.now()
        expired = expire_stale_runs(now)

        log_cutoff = now - timezone.timedelta(days=options["log_days"])
        run_cutoff = now - timezone.timedelta(days=options["run_days"])

        old_logs = RunLog.objects.filter(ts__lt=log_cutoff)
        old_runs = Run.objects.filter(created_at__lt=run_cutoff, status__in=Run.Status.values)

        if options["dry_run"]:
            self.stdout.write(
                f"просрочено: {expired}, к удалению логов: {old_logs.count()}, запусков: {old_runs.count()}"
            )
            return

        logs_deleted = old_logs.delete()[0]
        runs_deleted = old_runs.delete()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"Просрочено запусков: {expired}. Удалено строк логов: {logs_deleted}, "
                f"запусков: {runs_deleted}"
            )
        )
