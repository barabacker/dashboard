"""The two bulk buttons on the job list: stop everything, then clear everything.

They are deliberately a pair. Stopping is cooperative — a running Job is only *signalled*, and
the worker winds its crawl down at its next safe point — so clearing refuses while anything is
still active rather than deleting a row a worker is holding. Deleting it would not stop the
crawl; it would only make the traffic pointless and the outcome unwritable.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from control.models import Config, Job, JobStatus
from control.services import enqueue
from execution.queue import claim_job

pytestmark = pytest.mark.django_db

STOP_ALL = "admin:control_job_stop_all"
PURGE_ALL = "admin:control_job_purge_all"


def _terminal_job(config: Config, status: str = JobStatus.SUCCEEDED) -> Job:
    job = enqueue(config)
    Job.objects.filter(pk=job.pk).update(status=status, finished_at=timezone.now())
    return Job.objects.get(pk=job.pk)


class TestStopAll:
    def test_it_cancels_a_pending_job_outright(self, client, user, config):
        job = enqueue(config)
        client.force_login(user)

        client.post(reverse(STOP_ALL), follow=True)

        job.refresh_from_db()
        assert job.status == JobStatus.CANCELLED

    def test_it_only_signals_a_running_job(self, client, user, config):
        enqueue(config)
        claimed = claim_job(worker_id="w1", lease_seconds=60)
        client.force_login(user)

        client.post(reverse(STOP_ALL), follow=True)

        claimed.refresh_from_db()
        assert claimed.status == JobStatus.RUNNING, "nothing kills a run from outside"
        assert claimed.cancel_requested is True

    def test_it_leaves_a_terminal_job_alone(self, client, user, config):
        done = _terminal_job(config)
        client.force_login(user)

        client.post(reverse(STOP_ALL), follow=True)

        done.refresh_from_db()
        assert done.status == JobStatus.SUCCEEDED

    def test_it_asks_before_doing_anything(self, client, user, config):
        job = enqueue(config)
        client.force_login(user)

        response = client.get(reverse(STOP_ALL))

        assert response.status_code == 200
        job.refresh_from_db()
        assert job.status == JobStatus.PENDING, "GET must not mutate"

    def test_it_refuses_an_anonymous_visitor(self, client, config):
        job = enqueue(config)

        response = client.post(reverse(STOP_ALL))

        assert response.status_code == 302
        job.refresh_from_db()
        assert job.status == JobStatus.PENDING


class TestPurgeAll:
    def test_it_refuses_while_a_job_is_still_active(self, client, user, config):
        enqueue(config)
        client.force_login(user)

        client.post(reverse(PURGE_ALL), follow=True)

        assert Job.objects.count() == 1, "an active job must be stopped, not deleted under a worker"

    def test_it_deletes_every_terminal_job(self, client, user, config, make_config):
        _terminal_job(config)
        _terminal_job(make_config(name="second"), status=JobStatus.FAILED)
        client.force_login(user)

        client.post(reverse(PURGE_ALL), follow=True)

        assert Job.objects.count() == 0

    def test_it_asks_before_doing_anything(self, client, user, config):
        _terminal_job(config)
        client.force_login(user)

        response = client.get(reverse(PURGE_ALL))

        assert response.status_code == 200
        assert Job.objects.count() == 1, "GET must not delete"

    def test_it_refuses_an_anonymous_visitor(self, client, config):
        _terminal_job(config)

        response = client.post(reverse(PURGE_ALL))

        assert response.status_code == 302
        assert Job.objects.count() == 1


class TestTheButtonsAreReachable:
    def test_the_job_list_offers_both(self, client, user):
        client.force_login(user)

        response = client.get(reverse("admin:control_job_changelist"))

        assert response.status_code == 200
        assert reverse(STOP_ALL).encode() in response.content
        assert reverse(PURGE_ALL).encode() in response.content
