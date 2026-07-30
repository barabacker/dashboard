"""The source tab: a site is authored as fields, stored as a Config, snapshotted at enqueue."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from collectors import schemas
from control.forms import SourceForm
from control.models import Config, Job, JobStatus, Source
from control.services import enqueue

pytestmark = pytest.mark.django_db


def _form_data(**overrides):
    data = {
        "name": "Центр реализации",
        "collector_key": "tender_fogsoft",
        "domain": "https://bankrupt.centerr.ru",
        "listing_path": "",
        "max_pages": 0,
        "concurrency": 1,
        "only_active": "on",
        "fetch_details": "on",
        "extra_ca_cert": "",
        "tags": "[]",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


class TestForm:
    def test_site_fields_become_the_configs_parameters(self):
        form = SourceForm(data=_form_data())
        assert form.is_valid(), form.errors
        source = form.save()

        assert source.collector_key == "tender_fogsoft"
        assert source.parameters["domain"] == "https://bankrupt.centerr.ru"
        assert source.parameters["only_active"] is True
        assert source.parameters["fetch_details"] is True
        assert source.parameters["max_pages"] == 0

    def test_a_blank_listing_path_is_left_to_the_engine(self):
        """Storing today's default would freeze it into every site ever created."""
        form = SourceForm(data=_form_data())
        assert form.is_valid(), form.errors
        source = form.save()

        assert "listing_path" not in source.parameters
        effective = schemas.resolve_parameters(source.collector_key, source.parameters)
        assert effective["listing_path"] == "public/purchases-all/"

    def test_a_per_site_listing_path_is_stored(self):
        form = SourceForm(
            data=_form_data(
                name="Объединённые системы торгов",
                collector_key="tender_ruson",
                domain="https://sistematorg.com",
                listing_path="tradelist.php",
                fetch_details=None,
            )
        )
        assert form.is_valid(), form.errors
        assert form.save().parameters["listing_path"] == "tradelist.php"

    def test_a_parameter_the_engine_does_not_declare_is_not_stored(self):
        """`fetch_details` is fogsoft's; carrying it elsewhere would fail validation at enqueue."""
        form = SourceForm(
            data=_form_data(
                name="Альянс Трэйд",
                collector_key="tender_kendo",
                domain="https://trade-alliance.ru",
            )
        )
        assert form.is_valid(), form.errors
        assert "fetch_details" not in form.save().parameters

    def test_a_bad_value_is_reported_on_its_own_field(self):
        form = SourceForm(data=_form_data(concurrency=99))
        assert not form.is_valid()
        assert "concurrency" in form.errors

    def test_a_missing_domain_is_refused(self):
        form = SourceForm(data=_form_data(domain=""))
        assert not form.is_valid()
        assert "domain" in form.errors

    def test_editing_shows_what_is_authored_not_the_defaults(self):
        source = Source.objects.create(
            name="Промконсалт",
            collector_key="tender_ruson",
            parameters={"domain": "https://promkonsalt.ru", "listing_path": "tradelist.php"},
        )
        form = SourceForm(instance=source)

        assert form.fields["domain"].initial == "https://promkonsalt.ru"
        assert form.fields["listing_path"].initial == "tradelist.php"

    def test_only_the_tender_engines_are_offered(self):
        keys = {key for key, _label in SourceForm().fields["collector_key"].choices}
        assert keys == {"tender_fogsoft", "tender_kendo", "tender_btorg", "tender_ruson"}


class TestProxy:
    def test_the_tab_shows_sources_and_nothing_else(self, config):
        source = Source.objects.create(
            name="Торги82",
            collector_key="tender_kendo",
            parameters={"domain": "https://lot.torgi82.ru"},
        )

        assert list(Source.objects.all()) == [source]
        # …while the Config tab still shows both: a source *is* a Config.
        assert Config.objects.count() == 2

    def test_a_source_is_the_same_row_as_its_config(self):
        source = Source.objects.create(
            name="Торги82",
            collector_key="tender_kendo",
            parameters={"domain": "https://lot.torgi82.ru"},
        )
        assert Config.objects.get(pk=source.pk).name == "Торги82"
        assert source.domain == "https://lot.torgi82.ru"


class TestEnqueue:
    def test_the_site_is_frozen_into_the_snapshot(self):
        source = Source.objects.create(
            name="Селтим",
            collector_key="tender_kendo",
            parameters={"domain": "https://bankrupt.seltim.ru"},
        )
        job = enqueue(source)

        assert job.status == JobStatus.PENDING
        assert job.collector_key == "tender_kendo"
        assert job.effective_parameters["domain"] == "https://bankrupt.seltim.ru"
        assert job.effective_parameters["listing_path"] == "lots"
        assert job.effective_parameters["concurrency"] == 1

    def test_editing_the_site_afterwards_leaves_the_queued_run_alone(self):
        source = Source.objects.create(
            name="Селтим",
            collector_key="tender_kendo",
            parameters={"domain": "https://bankrupt.seltim.ru"},
        )
        job = enqueue(source)

        source.parameters = {"domain": "https://elsewhere.example"}
        source.save()

        assert Job.objects.get(pk=job.pk).effective_parameters["domain"] == (
            "https://bankrupt.seltim.ru"
        )


class TestEndToEnd:
    """Source → Job → worker → runner → engine, with only the network faked out."""

    def test_a_worker_runs_a_source_and_records_what_it_found(self, monkeypatch):
        from collectors.engine import CrawlOutcome
        from collectors.runners import tender_site
        from execution.worker import Worker

        seen = {}

        def _fake_crawl_site(spec, **kwargs):
            seen["spec"] = spec
            seen["params"] = kwargs["params"]
            return CrawlOutcome(
                source=spec.source, start_url=spec.start_url, lots=12, requests=5, listing_pages=2
            )

        monkeypatch.setattr(tender_site, "crawl_site", _fake_crawl_site)

        source = Source.objects.create(
            name="Торги82",
            collector_key="tender_kendo",
            parameters={"domain": "https://lot.torgi82.ru", "max_pages": 2},
        )
        job = enqueue(source)

        assert Worker(worker_id="w1").run_once() is True

        job.refresh_from_db()
        assert job.status == JobStatus.SUCCEEDED
        assert job.metrics == {
            "rows": 12,
            "calls": 5,
            "listing_pages": 2,
            "new": 0,
            "changed": 0,
        }
        assert job.result["source"] == "lot.torgi82.ru"
        assert job.result["stored"] is True
        # The site the engine crawled came from the snapshot, not from the Config.
        assert seen["spec"].domain == "https://lot.torgi82.ru"
        assert seen["params"]["max_pages"] == "2"

        source.refresh_from_db()
        assert source.last_status == JobStatus.SUCCEEDED
        assert source.last_job_id == job.pk

    def test_a_cancelled_crawl_lands_as_a_cancelled_job(self, monkeypatch):
        from collectors.engine import CrawlOutcome
        from collectors.runners import tender_site
        from execution.worker import Worker

        def _fake_crawl_site(spec, **kwargs):
            # Someone hits "отменить" while the crawl is in flight. The engine sees it through
            # the predicate it was handed, at its next safe point. (Polling is throttled to one
            # read a second, so this asks once, after the flag is set.)
            Job.objects.filter(config_id=source.pk).update(cancel_requested=True)
            assert kwargs["should_stop"]() is True
            return CrawlOutcome(
                source=spec.source, start_url=spec.start_url, lots=3, cancelled=True
            )

        monkeypatch.setattr(tender_site, "crawl_site", _fake_crawl_site)

        source = Source.objects.create(
            name="Аукционы Сибири",
            collector_key="tender_btorg",
            parameters={"domain": "https://ausib.ru"},
        )
        job = enqueue(source)

        Worker(worker_id="w1").run_once()

        job.refresh_from_db()
        assert job.status == JobStatus.CANCELLED


class TestAdmin:
    def test_the_tab_is_reachable_and_lists_the_site(self, client, user):
        Source.objects.create(
            name="Аукционы Сибири",
            collector_key="tender_btorg",
            parameters={"domain": "https://ausib.ru"},
        )
        client.force_login(user)
        response = client.get(reverse("admin:control_source_changelist"))

        assert response.status_code == 200
        assert "Аукционы Сибири".encode() in response.content
        assert b"https://ausib.ru" in response.content

    def test_the_add_form_asks_for_a_site_not_for_json(self, client, user):
        client.force_login(user)
        response = client.get(reverse("admin:control_source_add"))

        assert response.status_code == 200
        assert b'name="domain"' in response.content
        assert b'name="skip_tls_verify"' in response.content
        assert b'name="parameters"' not in response.content

    def test_run_now_from_the_tab_enqueues(self, client, user):
        source = Source.objects.create(
            name="ЭТП Профит",
            collector_key="tender_btorg",
            parameters={"domain": "https://etp-profit.ru"},
        )
        client.force_login(user)
        client.post(
            reverse("admin:control_source_changelist"),
            {"action": "action_run_now", "_selected_action": [str(source.pk)]},
            follow=True,
        )

        job = Job.objects.get()
        assert (job.config_id, job.collector_key) == (source.pk, "tender_btorg")


class TestSeed:
    def test_it_creates_the_carried_over_sources(self):
        call_command("seed_sources", verbosity=0)

        assert Source.objects.count() == 33
        centerr = Source.objects.get(name="Центр реализации")
        assert centerr.collector_key == "tender_fogsoft"
        assert centerr.parameters == {"domain": "https://bankrupt.centerr.ru"}

    def test_sites_that_were_switched_off_stay_switched_off(self):
        call_command("seed_sources", verbosity=0)
        assert Source.objects.get(name="uTender").enabled is False

    def test_per_site_quirks_survive_the_carry_over(self):
        call_command("seed_sources", verbosity=0)

        assert Source.objects.get(name="АРБбитЛот").parameters["skip_tls_verify"] is True
        assert Source.objects.get(name="МЕТА-ИНВЕСТ").parameters["extra_ca_cert"].endswith(".pem")
        assert Source.objects.get(name="Промконсалт").parameters["listing_path"] == (
            "tradelist.php"
        )

    def test_re_running_it_changes_nothing(self):
        call_command("seed_sources", verbosity=0)
        Source.objects.filter(name="Торги82").update(name="Торги82 (наш)")
        call_command("seed_sources", verbosity=0)

        assert Source.objects.count() == 33
        assert not Source.objects.filter(name="Торги82").exists()

    def test_every_carried_over_source_is_enqueueable(self):
        """A source the seed created must satisfy its collector's schema — all 33 of them."""
        call_command("seed_sources", verbosity=0)

        for source in Source.objects.all():
            schemas.resolve_parameters(source.collector_key, source.parameters)
