"""Build a parser class from a site description.

The temporary project kept the site list in ``platforms.toml`` and registered one parser class
per entry at import time. Here the site list is authored data (a Config in the back office), so
there is no registry and no import-time table: a Job's snapshot carries the site's fields and a
class is built from them for that one run.

What stays from the old shape is the split it enforced — engine code is generic, and everything
site-specific (domain, listing path, TLS quirks) is data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from collectors.engine.core.spider import BaseParser
from collectors.engine.sources.btorg.base import TenderBtorg
from collectors.engine.sources.fogsoft.base import TenderFogsoft
from collectors.engine.sources.kendo.base import TenderKendo
from collectors.engine.sources.ruson.base import TenderRuson
from collectors.schemas.tender import DEFAULT_LISTING_PATHS

#: Engine key -> base parser class. The keys are the collector keys' suffixes and are part of
#: the stored parameter contract, so they are English and stable. The list of keys itself lives
#: in `collectors.schemas.tender`, which is pure — this table is the half that needs the code.
ENGINES: dict[str, type[BaseParser]] = {
    "fogsoft": TenderFogsoft,
    "kendo": TenderKendo,
    "btorg": TenderBtorg,
    "ruson": TenderRuson,
}

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


class UnknownEngine(LookupError):
    """No parser family is registered under this engine key."""


@dataclass(frozen=True, slots=True)
class SiteSpec:
    """One site to crawl, exactly as a Job snapshot describes it."""

    engine: str
    domain: str
    listing_path: str = ""
    extra_ca_cert: str = ""
    skip_tls_verify: bool = False

    def __post_init__(self) -> None:
        if self.engine not in ENGINES:
            raise UnknownEngine(f"unknown engine {self.engine!r} (known: {sorted(ENGINES)})")
        if not self.domain:
            raise ValueError("domain is required")

    @property
    def source(self) -> str:
        """The identity a collected lot is attributed to: the site's host.

        Derived from the snapshot rather than from the Config's name or id, so renaming the
        Config — or re-creating it — does not silently start a second stream of lots for the
        same site.
        """
        host = urlsplit(self.domain).netloc or self.domain
        return host.strip("/").lower()

    @property
    def path(self) -> str:
        return self.listing_path or DEFAULT_LISTING_PATHS[self.engine]

    @property
    def start_url(self) -> str:
        return f"{self.domain.rstrip('/')}/{self.path}"


def _class_name(source: str) -> str:
    """``bankrupt.centerr.ru`` -> ``BankruptCenterrRuParser`` (readable in logs/tracebacks)."""
    parts = [part for part in _NON_WORD_RE.split(source) if part]
    return "".join(part.capitalize() for part in parts) + "Parser"


def build_parser_class(spec: SiteSpec) -> type[BaseParser]:
    """Create a parser class for one site. Not registered anywhere — it lives for one run."""
    base = ENGINES[spec.engine]
    attrs: dict[str, Any] = {
        "name": spec.source,
        "DOMAIN": spec.domain,
        "LISTING_PATH": spec.path,
        "EXTRA_CA_CERT": spec.extra_ca_cert or None,
        "SKIP_TLS_VERIFY": spec.skip_tls_verify,
        "__doc__": f"{spec.engine} — {spec.domain}.",
        "__module__": base.__module__,
    }
    return type(_class_name(spec.source), (base,), attrs)
