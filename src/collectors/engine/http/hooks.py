"""Request/response logging hooks (stdlib logging)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def log_request(method: str, url: str, kwargs: dict[str, Any]) -> None:
    """Request hook: log method and URL."""
    logger.info("http.request %s %s", method, url)


async def log_response(response: Any, *, session: Any, retry: Any) -> Any:
    """Response hook: log url/status/size, return the response unchanged."""
    logger.info(
        "http.response %s status=%s size=%s",
        getattr(response, "url", "?"),
        response.status_code,
        len(response.content),
    )
    return response
