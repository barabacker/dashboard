"""`Source` is a site's identity (domain, listing path, TLS quirks); a `Config` profile
references it and adds behaviour (collector, `max_pages`, ...). One `Source` can back several
named profiles."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.urls import reverse

from collectors import schemas
from control.forms import ConfigForm, SourceForm
from control.models import Config, Job, JobStatus, Source
from control.services import EnqueueRefused, enqueue

pytestmark = pytest.mark.django_db


def _source_form_data(**overrides):
    data = {
        "name": "Центр реализации",
        "domain": "https://bankrupt.centerr.ru",
        "listing_path": "",
        "extra_ca_cert": "",
        "skip_tls_verify": False,
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


class TestSourceForm:
    def test_a_source_is_just_site_identity(self):
        form = SourceForm(data=_source_form_data())
        assert form.is_valid(), form.errors
        source = form.save()

        assert source.domain == "https://bankrupt.centerr.ru"
        assert source.listing_path == ""
        assert source.skip_tls_verify is False

    def test_a_missing_domain_is_refused(self):
        form = SourceForm(data=_source_form_data(domain=""))
        assert not form.is_valid()
        assert "domain" in form.errors

    def test_a_per_site_listing_path_is_stored(self):
        form = SourceForm(
            data=_source_form_data(
                name="Объединённые системы торгов",
                domain="https://sistematorg.com",
                listing_path="tradelist.php",
            )
        )
        assert form.is_valid(), form.errors
        assert form.save().listing_path == "tradelist.php"

    def test_editing_shows_what_is_authored(self):
        source = Source.objects.create(
            name="Промконсалт", domain="https://promkonsalt.ru", listing_path="tradelist.php"
        )
        form = SourceForm(instance=source)

        assert form.initial["domain"] == "https://promkonsalt.ru"
        assert form.initial["listing_path"] == "tradelist.php"

    def test_extra_ca_cert_offers_the_shipped_certificates(self):
        choices = {value for value, _label in SourceForm().fields["extra_ca_cert"].choices}
        assert "" in choices  # "— обычный набор корневых —"


class TestConfigFormWithSource:
    def test_profile_parameters_validate_together_with_the_source(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        form = ConfigForm(
            data={
                "name": "Торги82 — fast",
                "collector_key": "tender_kendo",
                "source": source.pk,
                "parameters": "{}",
                "enabled": "on",
                "tags": "[]",
            }
        )
        assert form.is_valid(), form.errors

    def test_a_bad_profile_parameter_is_reported(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        form = ConfigForm(
            data={
                "name": "Торги82 — fast",
                "collector_key": "tender_kendo",
                "source": source.pk,
                "parameters": '{"concurrency": 99}',
                "enabled": "on",
                "tags": "[]",
            }
        )
        assert not form.is_valid()
        assert any("concurrency" in message for message in form.errors.get("parameters", []))

    def test_without_a_source_a_site_shaped_collector_is_refused(self):
        form = ConfigForm(
            data={
                "name": "Без сайта",
                "collector_key": "tender_kendo",
                "parameters": "{}",
                "enabled": "on",
                "tags": "[]",
            }
        )
        assert not form.is_valid()
        assert "source" in form.errors

    def test_a_source_on_a_non_site_collector_is_refused(self):
        """`example_api` declares no site parameters — a `source` here would silently do nothing."""
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        form = ConfigForm(
            data={
                "name": "Демо",
                "collector_key": "example_api",
                "source": source.pk,
                "parameters": '{"base_url": "https://api.example.com", "path": "/items", '
                '"page_size": 10, "pages": 2, "dataset": "orders"}',
                "enabled": "on",
                "tags": "[]",
            }
        )
        assert not form.is_valid()
        assert "source" in form.errors


class TestOneToMany:
    def test_one_source_can_back_several_named_profiles(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        default = Config.objects.create(
            name="Торги82 — default", collector_key="tender_kendo", source=source
        )
        fast = Config.objects.create(
            name="Торги82 — fast",
            collector_key="tender_kendo",
            source=source,
            parameters={"fetch_details": False},
        )

        assert set(source.configs.all()) == {default, fast}
        assert default.raw_parameters()["domain"] == fast.raw_parameters()["domain"]

    def test_editing_the_source_bumps_every_profiles_revision(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        a = Config.objects.create(name="A", collector_key="tender_kendo", source=source)
        b = Config.objects.create(name="B", collector_key="tender_kendo", source=source)
        rev_a, rev_b = a.revision, b.revision

        source.domain = "https://new.torgi82.ru"
        source.save()

        a.refresh_from_db()
        b.refresh_from_db()
        assert a.revision == rev_a + 1
        assert b.revision == rev_b + 1

    def test_editing_something_other_than_identity_does_not_bump_revision(self):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        profile = Config.objects.create(name="A", collector_key="tender_kendo", source=source)
        rev = profile.revision

        source.name = "Торги82 (переименован)"
        source.save()

        profile.refresh_from_db()
        assert profile.revision == rev


class TestEnqueue:
    def test_the_source_is_frozen_into_the_snapshot(self):
        source = Source.objects.create(name="Селтим", domain="https://bankrupt.seltim.ru")
        profile = Config.objects.create(name="Селтим", collector_key="tender_kendo", source=source)
        job = enqueue(profile)

        assert job.status == JobStatus.PENDING
        assert job.collector_key == "tender_kendo"
        assert job.effective_parameters["domain"] == "https://bankrupt.seltim.ru"
        assert job.effective_parameters["listing_path"] == "lots"
        assert job.effective_parameters["concurrency"] == 1

    def test_editing_the_source_afterwards_leaves_the_queued_run_alone(self):
        source = Source.objects.create(name="Селтим", domain="https://bankrupt.seltim.ru")
        profile = Config.objects.create(name="Селтим", collector_key="tender_kendo", source=source)
        job = enqueue(profile)

        source.domain = "https://elsewhere.example"
        source.save()

        assert Job.objects.get(pk=job.pk).effective_parameters["domain"] == (
            "https://bankrupt.seltim.ru"
        )

    def test_a_site_shaped_profile_without_a_source_refuses_to_enqueue(self):
        profile = Config.objects.create(name="Без сайта", collector_key="tender_kendo")

        with pytest.raises(EnqueueRefused) as exc_info:
            enqueue(profile)
        assert any("domain" in message for message in exc_info.value.errors)


class TestEndToEnd:
    """Source + Config profile → Job → worker → runner → engine, with only the network faked."""

    def test_a_worker_runs_a_profile_and_records_what_it_found(self, monkeypatch):
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

        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        profile = Config.objects.create(
            name="Торги82",
            collector_key="tender_kendo",
            source=source,
            parameters={"max_pages": 2},
        )
        job = enqueue(profile)

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
        # The site the engine crawled came from the snapshot, not from Source/Config directly.
        assert seen["spec"].domain == "https://lot.torgi82.ru"
        assert seen["params"]["max_pages"] == "2"

        profile.refresh_from_db()
        assert profile.last_status == JobStatus.SUCCEEDED
        assert profile.last_job_id == job.pk

    def test_a_cancelled_crawl_lands_as_a_cancelled_job(self, monkeypatch):
        from collectors.engine import CrawlOutcome
        from collectors.runners import tender_site
        from execution.worker import Worker

        def _fake_crawl_site(spec, **kwargs):
            # Someone hits "отменить" while the crawl is in flight. The engine sees it through
            # the predicate it was handed, at its next safe point. (Polling is throttled to one
            # read a second, so this asks once, after the flag is set.)
            Job.objects.filter(config_id=profile.pk).update(cancel_requested=True)
            assert kwargs["should_stop"]() is True
            return CrawlOutcome(
                source=spec.source, start_url=spec.start_url, lots=3, cancelled=True
            )

        monkeypatch.setattr(tender_site, "crawl_site", _fake_crawl_site)

        source = Source.objects.create(name="Аукционы Сибири", domain="https://ausib.ru")
        profile = Config.objects.create(
            name="Аукционы Сибири", collector_key="tender_btorg", source=source
        )
        job = enqueue(profile)

        Worker(worker_id="w1").run_once()

        job.refresh_from_db()
        assert job.status == JobStatus.CANCELLED


class TestAdmin:
    def test_the_source_tab_lists_the_site(self, client, user):
        Source.objects.create(name="Аукционы Сибири", domain="https://ausib.ru")
        client.force_login(user)
        response = client.get(reverse("admin:control_source_changelist"))

        assert response.status_code == 200
        assert "Аукционы Сибири".encode() in response.content
        assert b"https://ausib.ru" in response.content

    def test_the_add_form_asks_for_site_fields_not_json(self, client, user):
        client.force_login(user)
        response = client.get(reverse("admin:control_source_add"))

        assert response.status_code == 200
        assert b'name="domain"' in response.content
        assert b'name="skip_tls_verify"' in response.content
        assert b'name="parameters"' not in response.content

    def test_run_now_from_the_config_tab_enqueues(self, client, user):
        source = Source.objects.create(name="ЭТП Профит", domain="https://etp-profit.ru")
        profile = Config.objects.create(
            name="ЭТП Профит", collector_key="tender_btorg", source=source
        )
        client.force_login(user)
        client.post(
            reverse("admin:control_config_changelist"),
            {"action": "action_run_now", "_selected_action": [str(profile.pk)]},
            follow=True,
        )

        job = Job.objects.get()
        assert (job.config_id, job.collector_key) == (profile.pk, "tender_btorg")

    def test_the_config_add_form_can_register_a_new_source_inline(self, client, user):
        """One guided step, direction one: registering `cian.ru` and picking its collector on
        the same screen, via the `source` field's own add-popup."""
        client.force_login(user)
        response = client.get(reverse("admin:control_config_add"))

        assert response.status_code == 200
        assert b'id="add_id_source"' in response.content


class TestConfigInlineUnderSource:
    """One guided step, direction two: a *second* named profile for a site that already has
    one, added right on the Source's own page instead of hunting for it on the Config tab."""

    def _inline_post_data(self, source: Source, **overrides):
        data = {
            "name": source.name,
            "domain": source.domain,
            "listing_path": source.listing_path,
            "extra_ca_cert": source.extra_ca_cert,
            "configs-TOTAL_FORMS": "1",
            "configs-INITIAL_FORMS": "0",
            "configs-MIN_NUM_FORMS": "0",
            "configs-MAX_NUM_FORMS": "1000",
            "configs-0-name": "Торги82 — fast",
            "configs-0-collector_key": "tender_kendo",
            "configs-0-enabled": "on",
        }
        data.update(overrides)
        return data

    def test_adding_a_profile_from_the_source_page(self, client, user):
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        client.force_login(user)

        response = client.post(
            reverse("admin:control_source_change", args=[source.pk]),
            self._inline_post_data(source),
            follow=True,
        )

        assert response.status_code == 200
        profile = Config.objects.get(name="Торги82 — fast")
        assert profile.source_id == source.pk
        assert profile.collector_key == "tender_kendo"

    def test_a_non_site_collector_is_refused_from_the_inline(self, client, user):
        """`is_site` validation runs for the inline too, even though it never shows a `source`
        field — `ConfigForm.clean()` falls back to `self.instance.source`, which Django's inline
        formset machinery sets before `clean()` runs specifically so this can work."""
        source = Source.objects.create(name="Торги82", domain="https://lot.torgi82.ru")
        client.force_login(user)

        response = client.post(
            reverse("admin:control_source_change", args=[source.pk]),
            self._inline_post_data(source, **{"configs-0-collector_key": "example_api"}),
        )

        assert response.status_code == 200  # re-renders with errors, does not redirect
        assert not Config.objects.filter(name="Торги82 — fast").exists()


class TestSeed:
    def test_it_creates_the_carried_over_sources(self):
        call_command("seed_sources", verbosity=0)

        assert Source.objects.count() == 33
        assert Config.objects.count() == 33
        centerr = Source.objects.get(name="Центр реализации")
        profile = Config.objects.get(name="Центр реализации")
        assert profile.collector_key == "tender_fogsoft"
        assert profile.source_id == centerr.pk
        assert centerr.domain == "https://bankrupt.centerr.ru"

    def test_sites_that_were_switched_off_stay_switched_off(self):
        call_command("seed_sources", verbosity=0)
        assert Config.objects.get(name="uTender").enabled is False

    def test_per_site_quirks_survive_the_carry_over(self):
        call_command("seed_sources", verbosity=0)

        assert Source.objects.get(name="АРБбитЛот").skip_tls_verify is True
        assert Source.objects.get(name="МЕТА-ИНВЕСТ").extra_ca_cert.endswith(".pem")
        assert Source.objects.get(name="Промконсалт").listing_path == "tradelist.php"

    def test_re_running_it_changes_nothing(self):
        call_command("seed_sources", verbosity=0)
        Source.objects.filter(name="Торги82").update(name="Торги82 (наш)")
        call_command("seed_sources", verbosity=0)

        assert Source.objects.count() == 33
        assert not Source.objects.filter(name="Торги82").exists()

    def test_every_carried_over_profile_is_enqueueable(self):
        """A profile the seed created must satisfy its collector's schema — all 33 of them."""
        call_command("seed_sources", verbosity=0)

        for profile in Config.objects.all():
            schemas.resolve_parameters(profile.collector_key, profile.raw_parameters())
