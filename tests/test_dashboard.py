"""The dashboard surface: it produces work and requests cancellation, nothing more."""

from __future__ import annotations

import pytest
from django.urls import reverse

from control.models import Job, JobStatus

pytestmark = pytest.mark.django_db


def test_index_renders_the_unfold_admin_chrome(client, user, config):
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    # "Источники" is a sidebar nav label (see UNFOLD["SIDEBAR"] in settings.py) that never
    # otherwise appears in the dashboard's own body content — its presence means
    # `admin.site.each_context` reached the template and Unfold's sidebar rendered.
    assert "Источники".encode() in response.content


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


def test_index_groups_configs_by_collector_display_name(client, user, config):
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    # `config` fixture defaults to collector_key="example_api", whose display_name is set in
    # collectors/schemas/example_api.py.
    assert "Пример: HTTP API".encode() in response.content


def test_search_by_name_narrows_the_list(client, user, make_config):
    make_config(name="Alpha")
    make_config(name="Beta")
    client.force_login(user)
    response = client.get(reverse("dashboard:index"), {"q": "Alpha"})
    assert b"Alpha" in response.content
    assert b"Beta" not in response.content


def test_state_filter_shows_only_disabled(client, user, make_config):
    make_config(name="Included", enabled=False)
    make_config(name="Excluded", enabled=True)
    client.force_login(user)
    response = client.get(reverse("dashboard:index"), {"state": "disabled"})
    assert b"Included" in response.content
    assert b"Excluded" not in response.content


def test_a_config_with_an_active_job_shows_a_stop_button(client, user, config):
    from control.services import enqueue

    job = enqueue(config)
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert reverse("dashboard:cancel_job", args=[job.pk]).encode() in response.content
    assert "Остановить".encode() in response.content


def test_a_config_whose_active_job_is_already_being_cancelled_shows_no_stop_button(
    client, user, config
):
    from control.services import enqueue

    job = enqueue(config)
    Job.objects.filter(pk=job.pk).update(status=JobStatus.RUNNING, cancel_requested=True)
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert "останавливается".encode() in response.content
    assert reverse("dashboard:cancel_job", args=[job.pk]).encode() not in response.content


def test_a_family_with_no_matching_config_does_not_render_its_heading(client, user, make_config):
    make_config(name="Alpha", collector_key="example_api")
    make_config(
        name="Beta", collector_key="tender_fogsoft", parameters={"domain": "https://example.test"}
    )
    client.force_login(user)
    response = client.get(reverse("dashboard:index"), {"q": "Alpha"})
    assert "Пример: HTTP API".encode() in response.content
    assert "Торги: iTender (Fogsoft)".encode() not in response.content


def test_run_selected_enqueues_a_job_for_each_selected_config(client, user, make_config):
    a = make_config(name="a")
    b = make_config(name="b")
    client.force_login(user)
    response = client.post(
        reverse("dashboard:run_selected"), {"config_id": [a.pk, b.pk]}, follow=True
    )
    assert response.status_code == 200
    assert Job.objects.filter(config_id=a.pk, status=JobStatus.PENDING).count() == 1
    assert Job.objects.filter(config_id=b.pk, status=JobStatus.PENDING).count() == 1


def test_run_selected_refuses_a_disabled_config_without_creating_a_job(client, user, make_config):
    disabled = make_config(name="off", enabled=False)
    client.force_login(user)
    response = client.post(
        reverse("dashboard:run_selected"), {"config_id": [disabled.pk]}, follow=True
    )
    assert Job.objects.count() == 0
    assert "Отказано".encode() in response.content


def test_run_selected_with_nothing_checked_creates_no_job(client, user):
    client.force_login(user)
    response = client.post(reverse("dashboard:run_selected"), {}, follow=True)
    assert Job.objects.count() == 0
    assert "Ничего не выбрано".encode() in response.content


def test_run_selected_redirect_preserves_the_current_filter(client, user, make_config):
    a = make_config(name="a")
    client.force_login(user)
    response = client.post(
        reverse("dashboard:run_selected"),
        {"config_id": [a.pk], "next_qs": "q=Alpha&state=enabled"},
    )
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('dashboard:index')}?q=Alpha&state=enabled"


def test_cancel_job_redirect_preserves_the_current_filter(client, user, config):
    from control.services import enqueue

    job = enqueue(config)
    client.force_login(user)
    response = client.post(
        reverse("dashboard:cancel_job", args=[job.pk]), {"next_qs": "state=disabled"}
    )
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('dashboard:index')}?state=disabled"
