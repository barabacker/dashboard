"""Spider-style parser base classes: Request/Response/ParserContext/BaseParser."""

from __future__ import annotations

from collectors.engine.core.spider.context import ParserContext
from collectors.engine.core.spider.dive import DiveParser
from collectors.engine.core.spider.parser import BaseParser
from collectors.engine.core.spider.request import Request
from collectors.engine.core.spider.response import Response

__all__ = ["BaseParser", "DiveParser", "ParserContext", "Request", "Response"]
