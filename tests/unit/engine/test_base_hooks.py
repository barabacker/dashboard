"""Parsers declare their own HTTP specifics via class attributes."""

from __future__ import annotations

from collectors.engine.core.spider import BaseParser
from collectors.engine.sources.fogsoft.base import TenderFogsoft
from collectors.engine.sources.fogsoft.inprotect import solve_inprotect


def test_base_parser_defaults():
    assert BaseParser.RESPONSE_HOOKS == ()
    assert BaseParser.EXTRA_CA_CERT is None
    assert BaseParser.SKIP_TLS_VERIFY is False


def test_fogsoft_declares_inprotect_hook():
    assert (solve_inprotect,) == TenderFogsoft.RESPONSE_HOOKS
