"""build_http_client wires hooks and TLS from the parser class, engine-agnostic."""

from __future__ import annotations

from typing import Any

import pytest

from collectors.engine import SiteSpec, build_parser_class
from collectors.engine.core.spider import BaseParser
from collectors.engine.sources.fogsoft.inprotect import solve_inprotect
from collectors.schemas.tender import UnknownCertificate, available_certs

CENTERR = build_parser_class(SiteSpec(engine="fogsoft", domain="https://bankrupt.centerr.ru"))
ARBBITLOT = build_parser_class(
    SiteSpec(engine="fogsoft", domain="https://torgi.arbbitlot.ru", skip_tls_verify=True)
)
META_INVEST = build_parser_class(
    SiteSpec(
        engine="fogsoft",
        domain="https://meta-invest.ru",
        extra_ca_cert="meta_invest_globalsign_gcc_r3_dv_tls_ca_2020.pem",
    )
)


class _Bare(BaseParser):
    name = "_bare_test"

    async def parse(self, response: Any):  # pragma: no cover - never run
        yield {}


@pytest.fixture
def captured(monkeypatch):
    """Capture AsyncSession kwargs and the resolved extra-cert path."""
    seen: dict[str, Any] = {}

    class _FakeSession:
        def __init__(self, **kwargs: Any):
            seen["session_kwargs"] = kwargs

        async def close(self) -> None:  # pragma: no cover
            pass

    monkeypatch.setattr("collectors.engine.http.factory.AsyncSession", _FakeSession)
    monkeypatch.setattr(
        "collectors.engine.http.factory.ca_bundle_with_extra_cert",
        lambda path: seen.setdefault("cert_path", path) or "/tmp/fake-bundle.pem",
    )
    return seen


def test_fogsoft_site_gets_the_inprotect_hook(captured):
    from collectors.engine.http.factory import build_http_client

    client = build_http_client(CENTERR)
    assert solve_inprotect in client.middleware.response_middleware


def test_bare_parser_has_no_inprotect_hook(captured):
    from collectors.engine.http.factory import build_http_client

    client = build_http_client(_Bare)
    assert solve_inprotect not in client.middleware.response_middleware


def test_skip_tls_verify_disables_verification(captured):
    from collectors.engine.http.factory import build_http_client

    build_http_client(ARBBITLOT)
    assert captured["session_kwargs"].get("verify") is False


def test_extra_ca_cert_is_resolved_from_the_shipped_certs(captured):
    from collectors.engine.http.factory import build_http_client

    build_http_client(META_INVEST)
    cert_path = captured["cert_path"].replace("\\", "/")
    assert cert_path.endswith("collectors/certs/meta_invest_globalsign_gcc_r3_dv_tls_ca_2020.pem")


def test_the_shipped_certificate_is_offered_as_a_choice():
    assert "meta_invest_globalsign_gcc_r3_dv_tls_ca_2020.pem" in available_certs()


@pytest.mark.parametrize(
    "name",
    ["../../../etc/ssl/cert.pem", "/etc/ssl/cert.pem", "nope.pem"],
)
def test_a_cert_outside_the_shipped_set_is_refused(captured, name):
    """The value comes from a form: a path must never reach the CA bundle."""
    from collectors.engine.http.factory import build_http_client

    cls = build_parser_class(
        SiteSpec(engine="fogsoft", domain="https://example.com", extra_ca_cert=name)
    )
    with pytest.raises(UnknownCertificate):
        build_http_client(cls)
