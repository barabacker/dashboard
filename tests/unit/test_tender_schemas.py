"""The tender collectors' parameter contract — the part `control` sees.

Pure: no database, no engine. `control` validates against exactly this and snapshots the result,
so what these tests lock down is what a Job will carry.
"""

from __future__ import annotations

import pytest

from collectors import registry, schemas
from collectors.schemas.tender import (
    DEFAULT_LISTING_PATHS,
    ENGINE_KEYS,
    UnknownCertificate,
    available_certs,
    collector_key,
    engine_of,
    resolve_cert_path,
)


@pytest.mark.parametrize("engine", ENGINE_KEYS)
def test_every_engine_ships_a_collector(engine):
    key = collector_key(engine)
    descriptor = schemas.get_collector(key)
    assert descriptor.display_name.startswith("Торги: ")
    assert engine_of(key) == engine


def test_the_collectors_are_visible_to_the_projection():
    keys = {d.key for d in schemas.all_collectors()}
    assert {collector_key(e) for e in ENGINE_KEYS} <= keys


def test_every_collector_has_a_runner():
    """Every key resolves to code — the invariant, checked across both halves of the registry."""
    assert registry.check_registry() == []


@pytest.mark.parametrize("engine", ENGINE_KEYS)
def test_a_domain_is_all_a_site_must_be_told(engine):
    effective = schemas.resolve_parameters(collector_key(engine), {"domain": "https://example.com"})
    assert effective["domain"] == "https://example.com"
    assert effective["start_url"] == DEFAULT_LISTING_PATHS[engine]
    assert effective["max_pages"] == 0
    assert effective["only_active"] is True
    assert effective["concurrency"] == 1
    assert effective["extra_ca_cert"] == ""
    assert effective["skip_tls_verify"] is False


@pytest.mark.parametrize("engine", ENGINE_KEYS)
def test_the_domain_is_required(engine):
    with pytest.raises(schemas.ParameterError) as exc:
        schemas.resolve_parameters(collector_key(engine), {})
    assert any("domain" in message for message in exc.value.errors)


def test_only_fogsoft_offers_skipping_the_detail_pages():
    """For the dive engines the lots live on the detail page — the switch would be a lie."""
    fogsoft = schemas.get_collector(collector_key("fogsoft"))
    assert fogsoft.param("fetch_details") is not None

    for engine in ("kendo", "btorg", "ruson"):
        assert schemas.get_collector(collector_key(engine)).param("fetch_details") is None
        with pytest.raises(schemas.ParameterError):
            schemas.resolve_parameters(
                collector_key(engine),
                {"domain": "https://example.com", "fetch_details": False},
            )


def test_concurrency_is_bounded():
    with pytest.raises(schemas.ParameterError):
        schemas.resolve_parameters(
            collector_key("kendo"), {"domain": "https://example.com", "concurrency": 0}
        )
    with pytest.raises(schemas.ParameterError):
        schemas.resolve_parameters(
            collector_key("kendo"), {"domain": "https://example.com", "concurrency": 99}
        )


def test_no_tender_parameter_is_a_credential_reference():
    """These sites are public: nothing here should ever resolve a secret at run time."""
    for engine in ENGINE_KEYS:
        assert schemas.get_collector(collector_key(engine)).credential_ref_names == ()


def test_a_certificate_is_named_not_pathed():
    name = "meta_invest_globalsign_gcc_r3_dv_tls_ca_2020.pem"
    assert name in available_certs()
    assert resolve_cert_path(name).is_file()
    with pytest.raises(UnknownCertificate):
        resolve_cert_path("../../etc/ssl/cert.pem")
