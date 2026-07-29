"""Small parsing helpers shared by the source engines.

Engines stay independent of each other but may depend on ``core``; these were
previously duplicated per engine (clean / read_max_pages / parse_price).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
# Leading numeric run: space/nbsp thousands, dot or comma decimal. Stops before
# trailing currency/VAT text (e.g. "280 000,00 руб, НДС не облагается").
_PRICE_HEAD_RE = re.compile(r"[\d\s\xa0.,]+")
# DD.MM.YYYY with an optional HH:MM[:SS]; trailing text (e.g. "(33 дн.)") ignored.
_DATETIME_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})(?:\D+(\d{2}):(\d{2})(?::(\d{2}))?)?")


def clean(value: str | None) -> str | None:
    """Collapse whitespace to single spaces. None for empty."""
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", value).strip()
    return cleaned or None


# Statuses that mean the trade is over. Anything else (including an unknown or
# missing status) counts as live — we never cut a crawl short on doubt.
_FINISHED_MARKERS = (
    "завершен",
    "завершён",
    "состоял",
    "отменен",
    "отменён",
    "приостановлен",
    "аннулирован",
    "признан",
    "окончен",
)
# Words that make a short cell recognisable as a status at all.
_STATUS_HINTS = (*_FINISHED_MARKERS, "объявлен", "прием", "приём", "утверждени")


def is_active_status(status: str | None) -> bool:
    """Is a trade still live? Unknown/empty statuses count as live."""
    if not status:
        return True
    lowered = status.lower()
    return not any(marker in lowered for marker in _FINISHED_MARKERS)


def pick_status(texts: list[str | None]) -> str | None:
    """First short text that reads like a trade status (listing status cell)."""
    for text in texts:
        cleaned = clean(text)
        if cleaned and len(cleaned) < 40 and any(h in cleaned.lower() for h in _STATUS_HINTS):
            return cleaned
    return None


def read_only_active(params: dict[str, str]) -> bool:
    """Whether to dive only into live trades (default: on).

    When on, finished trades are skipped from the (expensive) detail dive, but
    the listing is still paged through in full — this flag does not stop
    pagination. Set ``only_active=0`` to also collect finished/archive lots.
    """
    raw = params.get("only_active")
    if raw is None or raw == "":
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def read_max_pages(params: dict[str, str]) -> int | None:
    """Read ``max_pages`` from job params. None means no limit."""
    raw = params.get("max_pages")
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (ValueError, TypeError):
        logger.warning("parsing.bad_max_pages value=%s", raw)
        return None
    return value if value > 0 else None


def read_concurrency(params: dict[str, str], default: int) -> int:
    """Read ``concurrency`` (in-site request workers) from job params.

    Falls back to ``default`` (the parser's ClassVar) when unset or invalid; a
    non-positive value is treated as invalid.
    """
    raw = params.get("concurrency")
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        logger.warning("parsing.bad_concurrency value=%s", raw)
        return default
    return value if value > 0 else default


def parse_price(value: str | None) -> float | None:
    """Parse a rouble amount to a float.

    Handles "270 000,00", "1 315 000.00" and "280 000,00 руб, НДС…": takes the
    leading numeric run, drops space/nbsp thousands separators, and treats comma
    or dot as the decimal point.
    """
    if value is None:
        return None
    m = _PRICE_HEAD_RE.match(value)
    if not m:
        return None
    raw = m.group(0).replace("\xa0", "").replace(" ", "").replace(",", ".").strip().rstrip(".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("parsing.bad_price value=%s", value)
        return None


def parse_datetime(value: str | None) -> datetime | None:
    """Parse a "DD.MM.YYYY[ HH:MM[:SS]]" string to a datetime, else None."""
    if not value:
        return None
    m = _DATETIME_RE.search(value)
    if not m:
        return None
    day, month, year, hour, minute, second = m.groups()
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
        )
    except ValueError:
        return None
