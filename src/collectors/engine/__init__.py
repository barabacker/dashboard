"""The scraping engine — async Spider core, HTTP layer and the per-family parsers.

Vendored from the temporary `coll-temp` project and kept framework-free: nothing here imports
Django, `control` or `execution`, which is what lets it live inside the `collectors` leaf
package. Two things changed on the way in:

* the site list is no longer a TOML file registered at import time — a site is authored in the
  back office and arrives as a Job snapshot, from which `build_parser_class` makes a class for
  that one run;
* a crawl can be stopped and can extend a lease, through the two plain callables on
  `ParserContext` (`should_stop` / `heartbeat`). The engine calls them and knows nothing else
  about the job control around it.
"""

from collectors.engine.build import ENGINES, SiteSpec, UnknownEngine, build_parser_class
from collectors.engine.core.lot import Lot
from collectors.engine.core.spider import BaseParser, ParserContext, Request, Response
from collectors.engine.core.storage.contracts import ChangeStatus
from collectors.engine.core.storage.counting import CountingSink
from collectors.engine.core.storage.sink import LotSink
from collectors.engine.run import CrawlOutcome, crawl_site

__all__ = [
    "ENGINES",
    "BaseParser",
    "ChangeStatus",
    "CountingSink",
    "CrawlOutcome",
    "Lot",
    "LotSink",
    "ParserContext",
    "Request",
    "Response",
    "SiteSpec",
    "UnknownEngine",
    "build_parser_class",
    "crawl_site",
]
