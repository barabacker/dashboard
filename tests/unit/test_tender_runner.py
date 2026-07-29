"""The runner is a translator: snapshot → crawl → RunResult. These tests hold it to that.

The crawl itself is faked out — what is under test is the seam, not the parsers (they have their
own fixture-driven suite in `tests/unit/engine`).
"""

from __future__ import annotations

import pytest

from collectors import registry
from collectors.engine import CrawlOutcome
from collectors.runners import tender_site_v1
from collectors.runners.base import RunContext, RunResult
from collectors.schemas import resolve_parameters
from collectors.schemas.tender import UnknownCertificate, collector_key


class FakeContext(RunContext):
    """A RunContext that answers from memory, the way DbRunContext answers from a Job."""

    def __init__(self, key: str, parameters: dict, *, cancelled: bool = False, lease=None):
        super().__init__(
            job_id=1,
            attempt_no=1,
            collector_key=key,
            collector_version="1.0",
            schema_version=1,
            parameters=parameters,
        )
        self.cancelled = cancelled
        self.lease_error = lease
        self.lease_calls = 0

    def is_cancel_requested(self) -> bool:
        return self.cancelled

    def resolve_credential(self, reference: str) -> str:  # pragma: no cover - never used
        raise AssertionError("tender collectors never resolve credentials")

    def extend_lease(self, seconds: int | None = None) -> None:
        self.lease_calls += 1
        if self.lease_error is not None:
            raise self.lease_error


def _params(engine: str, **overrides):
    return resolve_parameters(
        collector_key(engine), "1.0", {"domain": "https://example.com", **overrides}
    )


def _run(engine: str, monkeypatch, *, outcome=None, raises=None, ctx=None, **overrides):
    """Run the collector with `crawl_site` faked out; return (result, captured call)."""
    seen: dict = {}

    def _fake_crawl_site(spec, **kwargs):
        seen["spec"] = spec
        seen.update(kwargs)
        if raises is not None:
            raise raises
        return outcome or CrawlOutcome(source=spec.source, start_url=spec.start_url)

    monkeypatch.setattr(tender_site_v1, "crawl_site", _fake_crawl_site)
    runner = registry.resolve(collector_key(engine), "1.0")
    context = ctx or FakeContext(collector_key(engine), _params(engine, **overrides))
    return runner.run(context), seen


@pytest.mark.parametrize("engine", ["fogsoft", "kendo", "btorg", "ruson"])
def test_the_snapshot_becomes_a_site_spec(engine, monkeypatch):
    _result, seen = _run(engine, monkeypatch, domain="https://Lot.Torgi82.RU")

    assert seen["spec"].engine == engine
    assert seen["spec"].domain == "https://Lot.Torgi82.RU"
    assert seen["spec"].source == "lot.torgi82.ru"


def test_typed_parameters_become_the_engines_string_params(monkeypatch):
    _result, seen = _run("kendo", monkeypatch, max_pages=3, only_active=False, concurrency=4)

    assert seen["params"] == {"only_active": "0", "concurrency": "4", "max_pages": "3"}


def test_no_page_cap_is_absence_not_zero(monkeypatch):
    """`max_pages=0` means "no limit" — sending "0" would mean "no pages"."""
    _result, seen = _run("kendo", monkeypatch, max_pages=0)

    assert "max_pages" not in seen["params"]


def test_counts_become_metrics_and_a_readable_result(monkeypatch):
    outcome = CrawlOutcome(
        source="nistp.ru",
        start_url="https://nistp.ru/bankrot/trade_list.php",
        lots=42,
        requests=17,
        listing_pages=3,
        sample=("A-1", "A-2"),
    )
    result, _seen = _run("ruson", monkeypatch, outcome=outcome)

    assert result.status == RunResult.SUCCEEDED
    assert result.metrics == {"rows": 42, "calls": 17, "listing_pages": 3}
    assert result.result["source"] == "nistp.ru"
    assert result.result["sample_lot_ids"] == ["A-1", "A-2"]
    # Nothing was persisted, and the Job says so rather than implying otherwise.
    assert result.result["stored"] is False


def test_a_cancelled_crawl_reports_cancelled_with_its_partial_counts(monkeypatch):
    outcome = CrawlOutcome(
        source="nistp.ru", start_url="https://nistp.ru/x", lots=7, cancelled=True
    )
    result, _seen = _run("ruson", monkeypatch, outcome=outcome)

    assert result.status == RunResult.CANCELLED
    assert result.metrics["rows"] == 7


def test_the_cancellation_flag_is_what_the_engine_polls(monkeypatch):
    ctx = FakeContext(collector_key("kendo"), _params("kendo"), cancelled=True)
    _result, seen = _run("kendo", monkeypatch, ctx=ctx)

    assert seen["should_stop"]() is True


def test_the_heartbeat_extends_the_lease_but_not_on_every_request(monkeypatch):
    ctx = FakeContext(collector_key("kendo"), _params("kendo"))
    _result, seen = _run("kendo", monkeypatch, ctx=ctx)

    heartbeat = seen["heartbeat"]
    for _ in range(100):
        heartbeat()
    assert ctx.lease_calls == 1


def test_a_lost_lease_stops_the_crawl_and_is_re_raised(monkeypatch):
    class LeaseLost(RuntimeError):
        pass

    ctx = FakeContext(collector_key("kendo"), _params("kendo"), lease=LeaseLost("gone"))

    def _fake_crawl_site(spec, **kwargs):
        kwargs["heartbeat"]()
        # Once the lease is lost the engine must be told to wind down, not keep fetching.
        assert kwargs["should_stop"]() is True
        return CrawlOutcome(source=spec.source, start_url=spec.start_url, cancelled=True)

    monkeypatch.setattr(tender_site_v1, "crawl_site", _fake_crawl_site)
    runner = registry.resolve(collector_key("kendo"), "1.0")

    with pytest.raises(LeaseLost):
        runner.run(ctx)


def test_fogsoft_can_skip_the_detail_pages(monkeypatch):
    """No sink is how the fogsoft engine is told no listing row is worth a detail request."""
    _result, with_details = _run("fogsoft", monkeypatch, fetch_details=True)
    assert with_details["sink"] is not None

    _result, without = _run("fogsoft", monkeypatch, fetch_details=False)
    assert without["sink"] is None


@pytest.mark.parametrize("engine", ["kendo", "btorg", "ruson"])
def test_the_dive_engines_always_get_a_sink(engine, monkeypatch):
    _result, seen = _run(engine, monkeypatch)
    assert seen["sink"] is not None


def test_a_site_the_snapshot_cannot_describe_fails_without_a_traceback(monkeypatch):
    ctx = FakeContext(collector_key("kendo"), {**_params("kendo"), "domain": ""})
    result, _seen = _run("kendo", monkeypatch, ctx=ctx)

    assert result.status == RunResult.FAILED
    assert result.structured_error["type"] == "site_invalid"


def test_an_unreachable_site_gets_a_type_an_operator_can_filter_on(monkeypatch):
    from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

    result, _seen = _run("kendo", monkeypatch, raises=CurlConnectionError("boom"))

    assert result.status == RunResult.FAILED
    assert result.structured_error["type"] == "site_unreachable"
    assert result.result["start_url"].startswith("https://example.com")


def test_a_missing_certificate_is_reported_as_such(monkeypatch):
    result, _seen = _run("fogsoft", monkeypatch, raises=UnknownCertificate("nope.pem"))

    assert result.status == RunResult.FAILED
    assert result.structured_error["type"] == "certificate_missing"
