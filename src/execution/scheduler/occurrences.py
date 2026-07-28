"""Cron arithmetic — the pure part of the scheduler.

Kept apart from the transaction and the enqueue on purpose: "which occurrences are due" is a
function of a cron string, a timezone and two instants, and it should be testable as one.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from control.models import CatchupPolicy, Schedule

#: Hard stop on how far a single catch-up will walk. After a long outage, `fire_missed` would
#: otherwise enqueue an occurrence per minute of downtime and bury the queue. Hitting this cap is
#: a signal to look at the schedule, not something to silently absorb.
DEFAULT_MAX_CATCHUP = 100


def due_occurrences(
    schedule: Schedule,
    *,
    now: datetime,
    max_catchup: int = DEFAULT_MAX_CATCHUP,
) -> list[datetime]:
    """Occurrences of `schedule` in `(last_fired_at, now]`, filtered by its catch-up policy.

    Returns UTC datetimes, oldest first.

    A schedule that has never fired starts from *now*: `last_fired_at is None` means "no history",
    not "the epoch", and walking a cron back to 1970 is never what anyone wanted. The caller
    stamps `last_fired_at` on that first tick.
    """
    if schedule.last_fired_at is None:
        return []

    tz = ZoneInfo(schedule.timezone)
    cursor = croniter(schedule.cron, schedule.last_fired_at.astimezone(tz))
    horizon = now.astimezone(tz)

    # Truncating at `max_catchup` is safe: `last_fired_at` advances to the last occurrence acted
    # on, so anything beyond the cap is simply picked up by the next tick.
    occurrences: list[datetime] = []
    for _ in range(max_catchup):
        candidate = cursor.get_next(datetime)
        if candidate > horizon:
            break
        occurrences.append(candidate.astimezone(now.tzinfo))

    if not occurrences:
        return []

    if schedule.catchup_policy == CatchupPolicy.SKIP_TO_NOW:
        # Missed runs are water under the bridge; only the most recent occurrence still means
        # anything. `last_fired_at` still advances past all of them.
        return occurrences[-1:]

    return occurrences
