"""Lot change-detection contract, vendored from the old geo-contracts package.

Only the two pieces the parsers actually need are kept: the fingerprint of a
lot's tabular fields (to decide cheaply whether to dive into the detail page)
and the upsert outcome enum. The full RawLot pydantic model is replaced by the
Django Lot/LotHistory models.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any


class ChangeStatus(StrEnum):
    """Result of upserting a lot."""

    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


# Tabular fields that make up the fingerprint. Changing this set invalidates
# every stored fingerprint: all existing lots would be reported CHANGED on the
# next scan after deploy.
FINGERPRINT_FIELDS: tuple[str, ...] = (
    "status",
    "price",
    "bidding_date",
    "event_date",
    "trade_number",
)


def _canonicalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def lot_fingerprint(item: Mapping[str, Any]) -> str:
    """Stable sha1 hash of a lot's tabular fields (see FINGERPRINT_FIELDS).

    Lets a listing scan detect a changed lot without fetching the expensive
    detail page. Key order does not matter; a missing field is treated as None.
    """
    canonical = {field: _canonicalize(item.get(field)) for field in FINGERPRINT_FIELDS}
    payload = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
