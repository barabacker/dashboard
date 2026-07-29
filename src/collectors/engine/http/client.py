"""HttpClient — wrapper over curl_cffi.requests.AsyncSession with middleware."""

from __future__ import annotations

from typing import Any, cast

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from collectors.engine.http.middleware import Middleware


class HttpClient:
    """HTTP client: each request passes through request/response middleware.

    Network errors are retried with exponential backoff (4 attempts, 1–60s).
    """

    def __init__(self, session: AsyncSession[Any], middleware: Middleware) -> None:
        self._session = session
        self._middleware = middleware

    @property
    def middleware(self) -> Middleware:
        return self._middleware

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._session.close()

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1.0, min=1.0, max=60.0),
        retry=retry_if_exception_type(RequestException),
        reraise=True,
    )
    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Run a request through the registered hooks."""
        for request_hook in self._middleware.request_middleware:
            await request_hook(method, url, kwargs)

        async def do_request() -> Any:
            return await self._session.request(cast("Any", method), url, **kwargs)

        response = await do_request()

        for response_hook in self._middleware.response_middleware:
            response = await response_hook(response, session=self._session, retry=do_request)

        return response
