"""Local development seed: an admin user, the collector projection, and a few Configs.

Idempotent — re-running it changes nothing. Never run against production data.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from control.models import CatchupPolicy, Config, OverlapPolicy, Schedule


class Command(BaseCommand):
    help = "Create a dev superuser, sync collectors and add sample Configs (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default="admin")
        parser.add_argument("--email", default="admin@example.com")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        user_model = get_user_model()
        username = options["username"]

        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={"email": options["email"], "is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_password(options["password"])
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"created superuser {username!r}"))
        else:
            self.stdout.write(f"superuser {username!r} already exists")

        call_command("sync_collectors")

        samples = [
            {
                "name": "Пример API — ночная полная выгрузка",
                "collector_key": "example_api",
                "parameters": {
                    "base_url": "https://api.example.com",
                    "path": "/items",
                    "page_size": 200,
                    "pages": 3,
                    "dataset": "orders",
                    "credential_ref": "COLLECTOR_SECRET_DEMO_TOKEN",
                },
                "tags": ["nightly", "orders"],
                "schedule": {
                    "cron": "0 2 * * *",
                    "timezone": "Europe/Berlin",
                    "overlap_policy": OverlapPolicy.SKIP,
                    "catchup_policy": CatchupPolicy.SKIP_TO_NOW,
                },
            },
            {
                "name": "Пример API — клиенты каждый час",
                "collector_key": "example_api",
                "parameters": {
                    "base_url": "https://api.example.com",
                    "path": "/customers",
                    "pages": 1,
                    "dataset": "customers",
                },
                "tags": ["hourly", "customers"],
                "schedule": {
                    "cron": "0 * * * *",
                    "timezone": "UTC",
                    "overlap_policy": OverlapPolicy.QUEUE,
                    "catchup_policy": CatchupPolicy.FIRE_MISSED,
                },
            },
            {
                # Deliberately missing the `dataset` parameter that v2.0 requires: this is what a
                # Config authored against v1.0 looks like after the collector was upgraded.
                # "Run now" refuses it; a scheduled fire records a failed Job.
                "name": "Пример API — устаревшая конфигурация (до v2.0)",
                "collector_key": "example_api",
                "parameters": {"base_url": "https://api.example.com", "path": "/legacy"},
                "tags": ["legacy"],
                "schedule": None,
            },
        ]

        for sample in samples:
            schedule_spec = sample.pop("schedule")
            config, made = Config.objects.get_or_create(
                name=sample["name"],
                defaults={**sample, "owner": user, "created_by": user},
            )
            self.stdout.write(("created " if made else "kept    ") + f"config {config.name!r}")
            if schedule_spec and not config.schedules.exists():
                Schedule.objects.create(config=config, **schedule_spec)
                self.stdout.write(f"        + schedule {schedule_spec['cron']}")

        self.stdout.write(self.style.SUCCESS("seed complete"))
