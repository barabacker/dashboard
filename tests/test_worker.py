"""The worker (§9): resolve from the snapshot, run, write a terminal state, never retry."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from django.utils import timezone

from collectors.runners.base import Cancelled, RunResult
from collectors.runners.tender_site_v1 import _JobControl
from control.models import Config, Job, JobStatus
from control.services import enqueue, request_cancel
from execution.queue import LeaseLost, claim_job
from execution.worker import DbRunContext, Worker

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker() -> Worker:
    return Worker(worker_id="w1", lease_seconds=60, poll_seconds=0.01)


class TestHappyPath:
    def test_runs_a_job_to_success(self, config, worker):
        job = enqueue(config)

        assert worker.run_once() is True

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.SUCCEEDED
        assert reloaded.metrics["rows"] == 20  # page_size 10 x 2 pages
        assert reloaded.result["dataset"] == "orders"
        assert reloaded.finished_at is not None

    def test_reports_no_work_when_the_queue_is_empty(self, worker):
        assert worker.run_once() is False

    def test_refreshes_the_config_cache_columns(self, config, worker):
        job = enqueue(config)
        worker.run_once()

        reloaded = Config.objects.get(pk=config.pk)
        assert reloaded.last_status == JobStatus.SUCCEEDED
        assert reloaded.last_job_id == job.pk
        assert reloaded.last_run_at is not None
        assert reloaded.revision == 1, "a cache write is not an authored edit"

    def test_runs_the_version_the_snapshot_pinned_not_the_current_one(self, config, worker):
        """A Job snapshotted at v1.0 keeps running v1.0 after v2.0 shipped."""
        job = enqueue(config)
        Job.objects.filter(pk=job.pk).update(
            collector_version="1.0",
            schema_version=1,
            effective_parameters={
                "base_url": "https://x.test",
                "path": "/items",
                "page_size": 10,
                "pages": 2,
                "credential_ref": "",
            },
        )

        worker.run_once()

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.SUCCEEDED
        # v1.0 knows nothing about datasets; v2.0 would have put one in the result.
        assert "dataset" not in reloaded.result
        assert reloaded.metrics["bytes"] == 20 * 128


class TestFailures:
    def test_a_snapshot_pointing_at_missing_code_fails_loudly(self, config, worker):
        job = enqueue(config)
        Job.objects.filter(pk=job.pk).update(collector_version="9.9")

        worker.run_once()

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.FAILED
        assert reloaded.structured_error["type"] == "runner_unresolved"

    def test_an_unhandled_runner_error_becomes_a_structured_failure(
        self, config, worker, monkeypatch
    ):
        from collectors.runners import example_api_v2

        def boom(self, ctx):
            raise RuntimeError("upstream exploded")

        monkeypatch.setattr(example_api_v2.ExampleApiV2, "run", boom)
        job = enqueue(config)

        worker.run_once()

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.FAILED
        assert reloaded.structured_error["type"] == "unhandled"
        assert "upstream exploded" in reloaded.structured_error["message"]
        assert reloaded.structured_error["trace"]

    def test_a_missing_credential_is_an_environment_failure_not_a_crash(
        self, make_config, worker, monkeypatch
    ):
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        config = make_config(
            parameters={
                "base_url": "https://x.test",
                "dataset": "orders",
                "credential_ref": "MISSING_TOKEN",
            }
        )
        job = enqueue(config)

        worker.run_once()

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.FAILED
        assert reloaded.structured_error["type"] == "credential_missing"

    def test_a_secret_resolves_from_the_environment_and_is_never_stored(
        self, make_config, worker, monkeypatch
    ):
        monkeypatch.setenv("DEMO_TOKEN", "s3cr3t-value")
        config = make_config(
            parameters={
                "base_url": "https://x.test",
                "dataset": "orders",
                "credential_ref": "DEMO_TOKEN",
            }
        )
        job = enqueue(config)

        worker.run_once()

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.SUCCEEDED
        assert reloaded.result["authenticated"] is True
        assert "s3cr3t-value" not in str(reloaded.effective_parameters)
        assert "s3cr3t-value" not in str(reloaded.result)

    def test_a_failed_job_is_never_re_enqueued(self, config, worker, monkeypatch):
        from collectors.runners import example_api_v2

        monkeypatch.setattr(
            example_api_v2.ExampleApiV2,
            "run",
            lambda self, ctx: RunResult.failure(type="upstream", message="429"),
        )
        enqueue(config)
        worker.run_once()

        assert Job.objects.count() == 1
        assert worker.run_once() is False, "retry is a new Job, never an automatic re-claim"


class TestCancellation:
    def test_a_pending_job_is_cancelled_without_ever_running(self, config, worker):
        job = enqueue(config)
        assert request_cancel(job) == "cancelled"

        assert worker.run_once() is False
        assert Job.objects.get(pk=job.pk).status == JobStatus.CANCELLED

    def test_a_running_job_stops_at_the_next_checkpoint(self, config, worker):
        job = enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        # The signal arrives after the claim — the runner discovers it by polling.
        Job.objects.filter(pk=job.pk).update(cancel_requested=True)

        worker.execute(claimed)

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.CANCELLED
        assert reloaded.structured_error["type"] == "cancelled"

    def test_a_job_reclaimed_after_a_cancel_does_not_start(self, config, worker):
        job = enqueue(config)
        claim_job(worker_id="dead", lease_seconds=60)
        Job.objects.filter(pk=job.pk).update(
            cancel_requested=True, claimed_until=timezone.now() - timedelta(seconds=1)
        )

        assert worker.run_once() is True
        assert Job.objects.get(pk=job.pk).status == JobStatus.CANCELLED

    def test_check_cancelled_raises_for_the_runner(self, config):
        job = enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        Job.objects.filter(pk=job.pk).update(cancel_requested=True)

        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)
        with pytest.raises(Cancelled):
            ctx.check_cancelled()


class TestLeaseLoss:
    def test_extending_a_lost_lease_raises(self, config):
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        Job.objects.filter(pk=claimed.pk).update(claimed_by="w2")

        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)
        with pytest.raises(LeaseLost):
            ctx.extend_lease()

    def test_a_worker_that_lost_its_lease_writes_nothing(self, config, worker, monkeypatch):
        from collectors.runners import example_api_v2

        def steal_then_extend(self, ctx):
            Job.objects.filter(pk=ctx.job_id).update(claimed_by="someone-else")
            ctx.extend_lease()
            return RunResult.success()

        monkeypatch.setattr(example_api_v2.ExampleApiV2, "run", steal_then_extend)
        job = enqueue(config)

        worker.run_once()

        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.RUNNING, "the new owner keeps the job"
        assert Config.objects.get(pk=config.pk).last_status == ""


@pytest.mark.django_db(transaction=True)
class TestRunContextInsideAnEventLoop:
    """A runner is entitled to own an event loop, and the tender collectors do.

    `crawl_site` is `asyncio.run`, and the engine polls cancellation and renews the lease from
    *inside* its coroutines. Django refuses ORM access from a thread with a running loop, so both
    of the context's mid-run database methods have to cross that boundary themselves. Nothing
    else on `RunContext` touches the database: `resolve_credential` reads the environment.

    Transactional on purpose, and it must stay that way: the query runs on another thread, hence
    another connection, which can only see *committed* rows. That is not an artefact of the test
    — it is what the second connection means. In production `claim_job` has already committed by
    the time a runner starts, so the job row is there to be read.
    """

    def test_the_cancel_flag_is_readable_from_inside_an_event_loop(self, config):
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)

        async def poll() -> bool:
            return ctx.is_cancel_requested()

        assert asyncio.run(poll()) is False

    def test_a_cancellation_is_seen_from_inside_an_event_loop(self, config):
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        request_cancel(claimed)
        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)

        async def poll() -> bool:
            return ctx.is_cancel_requested()

        assert asyncio.run(poll()) is True

    def test_the_lease_is_renewable_from_inside_an_event_loop(self, config):
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)
        before = Job.objects.values_list("claimed_until", flat=True).get(pk=claimed.pk)

        async def renew() -> None:
            ctx.extend_lease(600)

        asyncio.run(renew())

        after = Job.objects.values_list("claimed_until", flat=True).get(pk=claimed.pk)
        assert after > before

    def test_a_lost_lease_still_raises_from_inside_an_event_loop(self, config):
        """The failure has to survive the thread hop, or a reclaimed job would crawl on."""
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        Job.objects.filter(pk=claimed.pk).update(claimed_by="w2")
        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)

        async def renew() -> None:
            ctx.extend_lease()

        with pytest.raises(LeaseLost):
            asyncio.run(renew())

    def test_the_tender_runners_job_control_survives_the_loop(self, config):
        """The production call shape: the two callables the engine is handed, driven from a
        coroutine the way `parser.crawl` drives them.

        `heartbeat` latches its exception instead of raising, so a broken lease renewal surfaces
        later as a lost lease. Asserting `failure is None` is what keeps a database error from
        being reported to the operator as someone else stealing the job.
        """
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        ctx = DbRunContext(claimed, worker_id="w1", lease_seconds=60)
        control = _JobControl(ctx, renew_interval=0.0)

        async def drive() -> bool:
            control.heartbeat()
            return control.should_stop()

        assert asyncio.run(drive()) is False
        assert control.failure is None


@pytest.mark.django_db(transaction=True)
def test_max_jobs_stops_the_loop(config, make_config):
    """Transactional on purpose: `run_forever` recycles DB connections between iterations, which
    is exactly what a long-lived worker process does and what a wrapped-in-atomic test cannot
    represent."""
    enqueue(config)
    enqueue(make_config(name="second"))

    worker = Worker(worker_id="w1", lease_seconds=60, poll_seconds=0.01, max_jobs=1)
    worker.run_forever()

    assert worker.jobs_done == 1
    assert Job.objects.filter(status=JobStatus.PENDING).count() == 1
