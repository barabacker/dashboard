"""BaseParser — Spider-style base class for parsers."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from collectors.engine.core.parsing import read_concurrency
from collectors.engine.core.spider.context import ParserContext
from collectors.engine.core.spider.request import Request
from collectors.engine.core.spider.response import Response
from collectors.engine.core.storage.contracts import ChangeStatus

if TYPE_CHECKING:
    from collectors.engine.core.lot import Lot
    from collectors.engine.http.middleware import ResponseHook


class BaseParser(ABC):
    """Spider-style parser with a concurrent ``crawl()``.

    A subclass sets ``name`` / ``start_urls`` and implements ``parse()`` as an
    async generator: yield a ``Request`` to enqueue it, yield a ``dict`` to emit
    a lot (item).
    """

    name: ClassVar[str]
    start_urls: ClassVar[list[str]] = []
    concurrency: ClassVar[int] = 1
    EXTRA_CA_CERT: ClassVar[str | None] = None
    SKIP_TLS_VERIFY: ClassVar[bool] = False
    RESPONSE_HOOKS: ClassVar[tuple[ResponseHook, ...]] = ()

    def __init__(self, ctx: ParserContext) -> None:
        self.ctx = ctx
        self.http = ctx.http
        self.item_count = 0
        self.new_item_count = 0
        self.changed_item_count = 0
        self.request_count = 0
        self.listing_page_count = 0
        self.cancelled = False
        self._errors: list[Exception] = []

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        callback: Callable[[Response], AsyncIterator[Request | dict[str, Any]]] | None = None,
        metadata: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | str | None = None,
    ) -> Request:
        """Build a ``Request`` defaulting its callback to ``self.parse``."""
        return Request(
            url=url,
            method=method,
            callback=callback or self.parse,
            metadata=metadata or {},
            headers=headers,
            data=data,
        )

    @abstractmethod
    def parse(self, response: Response) -> AsyncIterator[Request | dict[str, Any]]:
        """yield ``Request`` to enqueue; yield ``dict`` to emit a lot (item)."""

    async def log(self, message: str) -> None:
        """Write a message to the job log. No-op if ``ctx.log`` is unset."""
        if self.ctx.log is not None:
            await self.ctx.log(message)

    async def process_item(self, item: Lot) -> None:
        """Count lots and, if a sink is configured, persist them."""
        self.item_count += 1
        if self.ctx.lot_sink is not None:
            status = await self.ctx.lot_sink.save(item)
            if status == ChangeStatus.NEW:
                self.new_item_count += 1
            elif status == ChangeStatus.CHANGED:
                self.changed_item_count += 1

    def stop_requested(self) -> bool:
        """Has the caller asked this crawl to wind down? Latches once it has.

        Polled between requests, never mid-request: a stop must not leave a half-read response
        behind. Whoever asked knows the crawl is being abandoned, so partial counts are the
        honest answer.
        """
        if self.cancelled:
            return True
        if self.ctx.should_stop is not None and self.ctx.should_stop():
            self.cancelled = True
        return self.cancelled

    async def crawl(self) -> int:
        """Run producer/consumer crawling with ``concurrency`` workers.

        The first error collected in ``_errors`` is re-raised after all workers finish — unless
        the crawl was cancelled, in which case there is no outcome left to report but the stop
        itself.
        """
        queue: asyncio.Queue[Request] = asyncio.Queue()
        for url in self.start_urls:
            queue.put_nowait(self.request(url))

        async def worker() -> None:
            while True:
                req = await queue.get()
                try:
                    # Once a stop is requested the queue is drained, not worked: every
                    # remaining request is a page nobody asked for any more.
                    if not self.stop_requested():
                        await self._handle(req, queue)
                except Exception as exc:  # noqa: BLE001 — collect, don't kill the worker
                    self._errors.append(exc)
                finally:
                    queue.task_done()

        n_workers = read_concurrency(self.ctx.params, self.concurrency)
        workers = [asyncio.create_task(worker()) for _ in range(n_workers)]
        await queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        if self._errors and not self.cancelled:
            raise self._errors[0]
        return self.item_count

    async def _handle(self, req: Request, queue: asyncio.Queue[Request]) -> None:
        if self.ctx.heartbeat is not None:
            self.ctx.heartbeat()
        self.request_count += 1
        raw = await self.http.request(req.method, req.url, headers=req.headers, data=req.data)
        response = Response(raw, req)
        callback = req.callback or self.parse
        async for result in callback(response):
            if isinstance(result, Request):
                queue.put_nowait(result)
            else:
                await self.process_item(result)
