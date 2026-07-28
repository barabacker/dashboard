"""Sync the Collector projection from collector code. Run on every deploy.

Code is the source of truth. This command only mirrors key/label/description into the database so
the admin has something to filter and link against. It never writes versions or schemas, and it
never deletes: a collector whose key disappeared from the registry is *disabled*, keeping its
Configs and Job history intact (deprecate-not-delete).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from collectors import schemas
from control.models import Collector


class Command(BaseCommand):
    help = "Mirror the collector registry into the Collector projection table."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        now = timezone.now()

        descriptors = schemas.all_collectors()
        known_keys = {d.key for d in descriptors}
        existing = {c.key: c for c in Collector.objects.all()}

        created, updated, disabled = [], [], []

        for descriptor in descriptors:
            row = existing.get(descriptor.key)
            if row is None:
                created.append(descriptor.key)
                if not dry_run:
                    Collector.objects.create(
                        key=descriptor.key,
                        display_name=descriptor.display_name,
                        description=descriptor.description,
                        enabled=True,
                        synced_at=now,
                    )
                continue

            changes = {
                "display_name": descriptor.display_name,
                "description": descriptor.description,
            }
            drifted = [f for f, v in changes.items() if getattr(row, f) != v]
            # A key that came back after being disabled is re-enabled: the code says it exists.
            if not row.enabled:
                drifted.append("enabled")
            if drifted:
                updated.append(f"{descriptor.key} ({', '.join(sorted(drifted))})")
            if not dry_run:
                row.display_name = descriptor.display_name
                row.description = descriptor.description
                row.enabled = True
                row.synced_at = now
                row.save(update_fields=["display_name", "description", "enabled", "synced_at"])

        for key, row in existing.items():
            if key in known_keys or not row.enabled:
                continue
            disabled.append(key)
            if not dry_run:
                row.enabled = False
                row.synced_at = now
                row.save(update_fields=["enabled", "synced_at"])

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(f"{prefix}collectors in code: {len(descriptors)}")
        for label, items in (
            ("created", created),
            ("updated", updated),
            ("disabled (vanished from code)", disabled),
        ):
            if items:
                self.stdout.write(f"{prefix}{label}: {', '.join(items)}")
        if not (created or updated or disabled):
            self.stdout.write(self.style.SUCCESS(f"{prefix}projection already in sync"))

        if dry_run:
            transaction.set_rollback(True)
