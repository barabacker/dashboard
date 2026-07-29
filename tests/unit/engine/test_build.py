"""A site is data: `SiteSpec` -> a parser class for one run.

This replaces the temporary project's `platforms.toml` tests. The behavior they locked down —
per-site listing paths, TLS quirks, derived start URLs — is the same; only its source changed
from a file in the repository to a Job snapshot.
"""

from __future__ import annotations

import pytest

from collectors.engine import ENGINES, SiteSpec, UnknownEngine, build_parser_class
from collectors.engine.sources.fogsoft.base import TenderFogsoft
from collectors.engine.sources.fogsoft.inprotect import solve_inprotect
from collectors.engine.sources.kendo.base import TenderKendo
from collectors.engine.sources.ruson.base import TenderRuson
from collectors.schemas.tender import DEFAULT_LISTING_PATHS, ENGINE_KEYS


def test_every_declared_engine_has_a_parser_family():
    """The pure schema module and the engine's class table must not drift apart."""
    assert set(ENGINE_KEYS) == set(ENGINES)
    assert set(ENGINE_KEYS) == set(DEFAULT_LISTING_PATHS)


def test_listing_path_defaults_per_engine():
    spec = SiteSpec(engine="kendo", domain="https://trade-alliance.ru")
    assert spec.path == "lots"
    assert spec.start_url == "https://trade-alliance.ru/lots"


def test_listing_path_can_be_overridden_per_site():
    spec = SiteSpec(engine="ruson", domain="https://sistematorg.com", listing_path="tradelist.php")
    assert spec.start_url == "https://sistematorg.com/tradelist.php"


def test_source_is_the_host_not_the_url():
    """Lots are attributed to the site's host, so a renamed Config keeps one stream."""
    assert SiteSpec(engine="kendo", domain="https://Lot.Torgi82.RU/").source == "lot.torgi82.ru"


def test_unknown_engine_is_refused_at_construction():
    with pytest.raises(UnknownEngine, match="unknown engine"):
        SiteSpec(engine="nope", domain="https://example.com")


def test_domain_is_required():
    with pytest.raises(ValueError, match="domain is required"):
        SiteSpec(engine="kendo", domain="")


def test_built_class_derives_urls_and_keeps_its_family():
    cls = build_parser_class(SiteSpec(engine="kendo", domain="https://trade-alliance.ru"))
    assert issubclass(cls, TenderKendo)
    assert cls.name == "trade-alliance.ru"
    assert cls.BASE_URL == "https://trade-alliance.ru/lots"
    assert cls.start_urls == ["https://trade-alliance.ru/lots"]
    assert cls.RESPONSE_HOOKS == ()


def test_fogsoft_sites_keep_the_inprotect_hook():
    cls = build_parser_class(SiteSpec(engine="fogsoft", domain="https://bankrupt.centerr.ru"))
    assert issubclass(cls, TenderFogsoft)
    assert cls.BASE_URL == "https://bankrupt.centerr.ru/public/purchases-all/"
    assert solve_inprotect in cls.RESPONSE_HOOKS


def test_tls_quirks_reach_the_class_and_default_to_off():
    plain = build_parser_class(SiteSpec(engine="fogsoft", domain="https://bankrupt.centerr.ru"))
    assert plain.SKIP_TLS_VERIFY is False
    assert plain.EXTRA_CA_CERT is None

    quirky = build_parser_class(
        SiteSpec(
            engine="fogsoft",
            domain="https://torgi.arbbitlot.ru",
            skip_tls_verify=True,
        )
    )
    assert quirky.SKIP_TLS_VERIFY is True


def test_class_name_is_readable_in_a_traceback():
    cls = build_parser_class(SiteSpec(engine="ruson", domain="https://nistp.ru"))
    assert issubclass(cls, TenderRuson)
    assert cls.__name__ == "NistpRuParser"
