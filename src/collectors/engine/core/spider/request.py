"""Request — describes an HTTP request that crawl() must perform."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collectors.engine.core.spider.response import Response


@dataclass(slots=True)
class Request:
    """Describes an HTTP request that crawl() must perform."""

    url: str
    method: str = "GET"
    callback: Callable[[Response], AsyncIterator[Request | dict[str, Any]]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] | None = None
    data: dict[str, str] | str | None = None
