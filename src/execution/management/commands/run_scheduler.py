"""`manage.py run_scheduler` — one scheduling pass, or a loop.

Default is a single tick, so the natural deployment is system cron every minute. `--loop` exists
for docker-compose and for hosts without cron; it is the same tick on a timer, and running both
at once is harmless — `(schedule_id, fire_time)` makes duplicate work impossible.
"""

from __future__ import annotations

import signal
import time
from types import FrameType

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from execution.scheduler import DEFAULT_MAX_CATCHUP, tick


class Command(BaseCommand):
    help = "Find due schedules and enqueue their Jobs."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep ticking instead of exiting after one pass.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=30.0,
            help="Seconds between ticks in --loop mode.",
        )
        parser.add_argument(
            "--max-catchup",
            type=int,
            default=DEFAULT_MAX_CATCHUP,
            help="Cap on occurrences fired per schedule per tick after downtime.",
        )

    def handle(self, *args, **options) -> None:
        max_catchup: int = options["max_catchup"]

        if not options["loop"]:
            self.stdout.write(tick(max_catchup=max_catchup).summary())
            return

        stopping = False

        def _stop(signum: int, frame: FrameType | None) -> None:
            nonlocal stopping
            stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _stop)

        interval: float = options["interval"]
        self.stdout.write(f"scheduler loop started (interval={interval}s)")
        while not stopping:
            close_old_connections()
            tick(max_catchup=max_catchup)
            # Coarse sleep, checked often, so a stop signal is not held up for a whole interval.
            slept = 0.0
            while slept < interval and not stopping:
                time.sleep(min(0.5, interval - slept))
                slept += 0.5
        self.stdout.write("scheduler loop stopped")
