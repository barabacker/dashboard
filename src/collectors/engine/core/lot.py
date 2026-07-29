"""Lot — the standardized, typed item every parser emits.

Parsers build ad-hoc dicts; this model validates and normalizes one at the
engine boundary (see DiveParser / fogsoft base). It renames ``_source``/
``detail`` to ``source``/``extra``, parses the two date strings into
``datetime`` (keeping the raw strings), and derives ``is_active`` from status.
Unknown fields are rejected so engine drift surfaces immediately.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from collectors.engine.core.parsing import is_active_status, parse_datetime


class Lot(BaseModel):
    """A single lot within a trade, normalized across all engines."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(alias="_source")
    lot_id: str
    trade_id: str
    lot_num: str | None = None

    trade_number: str | None = None
    trade_type: str | None = None
    debtor: str | None = None
    organizer: str | None = None

    description: str | None = None
    lot_url: str | None = None
    price: float | None = None
    price_raw: str | None = None

    status: str | None = None
    is_active: bool = True
    bidding_deadline: datetime | None = None
    result_date: datetime | None = None
    bidding_date_raw: str | None = None
    event_date_raw: str | None = None

    attachments: list[dict[str, Any]] = Field(default_factory=list)
    price_schedule: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict, alias="detail")

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "bidding_date" in d:
            d["bidding_date_raw"] = d.get("bidding_date")
            d["bidding_deadline"] = parse_datetime(d.pop("bidding_date"))
        if "event_date" in d:
            d["event_date_raw"] = d.get("event_date")
            d["result_date"] = parse_datetime(d.pop("event_date"))
        d.setdefault("is_active", is_active_status(d.get("status")))
        return d
