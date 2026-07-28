"""Claim, lease and reclaim (§7) — including two workers actually racing."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connection, connections
from django.utils import timezone

from control.models import Job, JobStatus
from control.services import enqueue
from execution.queue import claim_job, finish_job, read_cancel_flag, renew_lease

pytestmark = pytest.mark.django_db

LEASE = 60


class TestClaim:
    def test_claims_a_pending_job_and_marks_it_running(self, config):
        job = enqueue(config)

        claimed = claim_job(worker_id="w1", lease_seconds=LEASE)

        assert claimed is not None
        assert claimed.pk == job.pk
        assert claimed.status == JobStatus.RUNNING
        assert claimed.claimed_by == "w1"
        assert claimed.attempt_no == 1
        assert claimed.claimed_until > timezone.now()

    def test_returns_none_when_there_is_nothing_to_do(self, config):
        assert claim_job(worker_id="w1", lease_seconds=LEASE) is None

    def test_never_hands_the_same_job_to_two_workers(self, config):
        enqueue(config)

        first = claim_job(worker_id="w1", lease_seconds=LEASE)
        second = claim_job(worker_id="w2", lease_seconds=LEASE)

        assert first is not None
        assert second is None

    def test_ignores_a_job_that_is_not_available_yet(self, config):
        enqueue(config, available_at=timezone.now() + timedelta(hours=1))
        assert claim_job(worker_id="w1", lease_seconds=LEASE) is None

    def test_ignores_a_pending_job_that_was_cancelled(self, config):
        job = enqueue(config)
        Job.objects.filter(pk=job.pk).update(cancel_requested=True)
        assert claim_job(worker_id="w1", lease_seconds=LEASE) is None

    def test_ignores_terminal_jobs(self, config):
        job = enqueue(config)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.FAILED)
        assert claim_job(worker_id="w1", lease_seconds=LEASE) is None

    def test_higher_priority_goes_first(self, config, make_config):
        low = enqueue(config, priority=0)
        high = enqueue(make_config(name="urgent"), priority=10)

        assert claim_job(worker_id="w1", lease_seconds=LEASE).pk == high.pk
        assert claim_job(worker_id="w2", lease_seconds=LEASE).pk == low.pk


class TestReclaim:
    """An expired lease *is* the dead-worker recovery. There is no reaper."""

    def test_an_expired_lease_makes_the_job_claimable_again(self, config):
        job = enqueue(config)
        claim_job(worker_id="dead-worker", lease_seconds=LEASE)
        Job.objects.filter(pk=job.pk).update(claimed_until=timezone.now() - timedelta(seconds=1))

        reclaimed = claim_job(worker_id="live-worker", lease_seconds=LEASE)

        assert reclaimed is not None
        assert reclaimed.pk == job.pk
        assert reclaimed.claimed_by == "live-worker"

    def test_a_reclaim_increments_attempt_no(self, config):
        job = enqueue(config)
        claim_job(worker_id="w1", lease_seconds=LEASE)
        assert Job.objects.get(pk=job.pk).attempt_no == 1

        Job.objects.filter(pk=job.pk).update(claimed_until=timezone.now() - timedelta(seconds=1))
        claim_job(worker_id="w2", lease_seconds=LEASE)

        assert Job.objects.get(pk=job.pk).attempt_no == 2

    def test_a_live_lease_is_not_reclaimed(self, config):
        enqueue(config)
        claim_job(worker_id="w1", lease_seconds=LEASE)
        assert claim_job(worker_id="w2", lease_seconds=LEASE) is None

    def test_a_reclaimed_job_is_still_the_same_job_not_a_retry(self, config):
        job = enqueue(config)
        claim_job(worker_id="w1", lease_seconds=LEASE)
        Job.objects.filter(pk=job.pk).update(claimed_until=timezone.now() - timedelta(seconds=1))
        claim_job(worker_id="w2", lease_seconds=LEASE)

        assert Job.objects.count() == 1


class TestLease:
    def test_renewal_pushes_the_expiry_out(self, config):
        enqueue(config)
        job = claim_job(worker_id="w1", lease_seconds=10)
        before = job.claimed_until

        assert renew_lease(job_id=job.pk, worker_id="w1", lease_seconds=600) is True
        assert Job.objects.get(pk=job.pk).claimed_until > before

    def test_renewal_fails_once_the_job_was_reclaimed(self, config):
        enqueue(config)
        job = claim_job(worker_id="w1", lease_seconds=10)
        Job.objects.filter(pk=job.pk).update(claimed_by="w2")

        assert renew_lease(job_id=job.pk, worker_id="w1", lease_seconds=600) is False


class TestFinish:
    def test_writes_the_outcome_for_the_owning_worker(self, config):
        enqueue(config)
        job = claim_job(worker_id="w1", lease_seconds=LEASE)

        assert finish_job(
            job_id=job.pk,
            worker_id="w1",
            status=JobStatus.SUCCEEDED,
            result={"ok": True},
            metrics={"rows": 5},
        )
        reloaded = Job.objects.get(pk=job.pk)
        assert reloaded.status == JobStatus.SUCCEEDED
        assert reloaded.metrics == {"rows": 5}
        assert reloaded.finished_at is not None

    def test_a_worker_that_lost_the_claim_cannot_write_an_outcome(self, config):
        enqueue(config)
        job = claim_job(worker_id="w1", lease_seconds=LEASE)
        Job.objects.filter(pk=job.pk).update(claimed_by="w2")

        assert not finish_job(job_id=job.pk, worker_id="w1", status=JobStatus.SUCCEEDED)
        assert Job.objects.get(pk=job.pk).status == JobStatus.RUNNING

    def test_a_terminal_job_is_never_overwritten(self, config):
        enqueue(config)
        job = claim_job(worker_id="w1", lease_seconds=LEASE)
        finish_job(job_id=job.pk, worker_id="w1", status=JobStatus.FAILED)

        assert not finish_job(job_id=job.pk, worker_id="w1", status=JobStatus.SUCCEEDED)
        assert Job.objects.get(pk=job.pk).status == JobStatus.FAILED


def test_read_cancel_flag(config):
    job = enqueue(config)
    assert read_cancel_flag(job.pk) is False
    Job.objects.filter(pk=job.pk).update(cancel_requested=True)
    assert read_cancel_flag(job.pk) is True


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_never_claim_the_same_row(make_config):
    """The real race: four threads on four connections, competing for six jobs.

    `FOR UPDATE SKIP LOCKED` is what makes this safe — without it the threads would either
    serialise or double-claim.
    """
    from control.services import enqueue as _enqueue

    jobs = [_enqueue(make_config(name=f"cfg-{i}")) for i in range(6)]
    expected = {job.pk for job in jobs}

    claimed: list[int] = []
    lock = threading.Lock()
    start = threading.Barrier(4)

    def worker(worker_id: str) -> None:
        try:
            start.wait(timeout=10)
            while True:
                job = claim_job(worker_id=worker_id, lease_seconds=LEASE)
                if job is None:
                    return
                with lock:
                    claimed.append(job.pk)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(claimed) == sorted(expected), "every job claimed exactly once"
    assert len(claimed) == len(set(claimed)), "no job claimed twice"
    connection.close()
