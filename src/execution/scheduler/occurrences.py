"""Cron arithmetic — the pure part of the scheduler.

Kept apart from the transaction and the enqueue on purpose: "which occurrence is due" is a
function of a cron string, a timezone and two instants, and it should be testable as one.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from control.models import Schedule

#: Hard stop on how far a single tick walks forward looking for the latest due occurrence. After a
#: long outage this keeps one tick from silently absorbing an unbounded amount of missed history —
#: hitting the cap just means the next tick picks up from where this one stopped.
DEFAULT_MAX_CATCHUP = 100


def due_occurrences(
    schedule: Schedule,
    *,
    now: datetime,
    max_catchup: int = DEFAULT_MAX_CATCHUP,
) -> list[datetime]:
    """The single most recent occurrence of `schedule` still due, if any.

    Returns a list of zero or one UTC datetimes — a list, not `datetime | None`, so callers do not
    need a separate branch for "nothing due" versus "one thing due".

    A schedule that has never fired starts from *now*: `last_fired_at is None` means "no history",
    not "the epoch", and walking a cron back to 1970 is never what anyone wanted. The caller
    stamps `last_fired_at` on that first tick. Missed occurrences before the latest one are not
    caught up — only the most recent still means anything.
    """
    if schedule.last_fired_at is None:
        return []

    tz = ZoneInfo(schedule.timezone)
    cursor = croniter(schedule.cron, schedule.last_fired_at.astimezone(tz))
    horizon = now.astimezone(tz)

    latest: datetime | None = None
    for _ in range(max_catchup):
        candidate = cursor.get_next(datetime)
        if candidate > horizon:
            break
        latest = candidate

    if latest is None:
        return []
    return [latest.astimezone(now.tzinfo)]
