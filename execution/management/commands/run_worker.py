"""`manage.py run_worker` — start a worker process.

Run as many as you like. They compete for rows; there is nothing to configure between them.
"""

from __future__ import annotations

import os
import socket

from django.core.management.base import BaseCommand

from execution.worker import Worker


def default_worker_id() -> str:
    """Identifies the *process*, which is what a lease is really held by."""
    return f"{socket.gethostname()}:{os.getpid()}"


class Command(BaseCommand):
    help = "Claim and execute Jobs until stopped."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--worker-id",
            default=None,
            help="Identity recorded in claimed_by. Defaults to host:pid.",
        )
        parser.add_argument(
            "--lease-seconds",
            type=int,
            default=None,
            help="How long a claim is held before it becomes reclaimable. "
            "Prefer generous over frequent renewal.",
        )
        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=None,
            help="Sleep between empty polls.",
        )
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=None,
            help="Exit after this many jobs. Useful for one-shot runs and tests.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Claim and execute at most one job, then exit.",
        )

    def handle(self, *args, **options) -> None:
        worker = Worker(
            worker_id=options["worker_id"] or default_worker_id(),
            lease_seconds=options["lease_seconds"],
            poll_seconds=options["poll_seconds"],
            max_jobs=1 if options["once"] else options["max_jobs"],
        )

        if options["once"]:
            did_work = worker.run_once()
            self.stdout.write("executed one job" if did_work else "nothing to do")
            return

        worker.install_signal_handlers()
        worker.run_forever()
