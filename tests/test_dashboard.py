"""The dashboard surface: it produces work and requests cancellation, nothing more."""

from __future__ import annotations

import pytest
from django.urls import reverse

from control.models import Job, JobStatus

pytestmark = pytest.mark.django_db


def test_index_requires_staff(client):
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 302


def test_index_lists_configs(client, user, config):
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    assert config.name.encode() in response.content


def test_run_now_creates_a_pending_job(client, user, config):
    client.force_login(user)
    response = client.post(reverse("dashboard:run_now", args=[config.pk]), follow=True)
    assert response.status_code == 200

    job = Job.objects.get()
    assert (job.status, job.config_id) == (JobStatus.PENDING, config.pk)


def test_run_now_surfaces_a_refusal_without_creating_anything(client, user, make_config):
    config = make_config(enabled=False)
    client.force_login(user)
    response = client.post(reverse("dashboard:run_now", args=[config.pk]), follow=True)

    assert Job.objects.count() == 0
    assert "отключена".encode() in response.content


def test_cancelling_a_pending_job_cancels_it_outright(client, user, config):
    from control.services import enqueue

    job = enqueue(config)
    client.force_login(user)
    client.post(reverse("dashboard:cancel_job", args=[job.pk]), follow=True)

    reloaded = Job.objects.get(pk=job.pk)
    assert reloaded.status == JobStatus.CANCELLED
    assert reloaded.cancel_requested is True


def test_cancelling_a_running_job_only_signals_it(client, user, config):
    from control.services import enqueue

    job = enqueue(config)
    Job.objects.filter(pk=job.pk).update(status=JobStatus.RUNNING)

    client.force_login(user)
    client.post(reverse("dashboard:cancel_job", args=[job.pk]), follow=True)

    reloaded = Job.objects.get(pk=job.pk)
    assert reloaded.status == JobStatus.RUNNING
    assert reloaded.cancel_requested is True


def test_jobs_panel_renders_on_its_own(client, user, config):
    client.force_login(user)
    response = client.get(reverse("dashboard:jobs_panel"))
    assert response.status_code == 200
    assert b"jobs-panel" in response.content
