# Rename Platform → Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `control.models.Platform` (and everything hanging off it — form, admin, manager,
seed command, tests, docs) to `Source`, and its Russian label from «Площадка»/«Площадки» to
«Источник»/«Источники», with no change in behavior.

**Architecture:** A mechanical, cross-file rename. `Source` stays a `proxy = True` model of
`Config` (D17, unchanged in substance), the manager keeps its
`collector_key__startswith='tender_'` filter, and the form keeps its fixed tender-specific field
set. The only new artifact is a migration using `RenameModel` — not the default
`DeleteModel`+`CreateModel` a non-interactive `makemigrations` would produce — because that is what
lets Django's contenttypes framework update the existing `ContentType` row in place instead of
recreating it, which would silently orphan the `control.*_platform` permissions already granted to
the `petr` user and any existing admin `LogEntry` history.

**Tech Stack:** Django 5.2, `unfold` admin theme, pytest + pytest-django, `uv`.

Design doc: `docs/superpowers/specs/2026-07-30-rename-platform-to-source-design.md` (approved).

---

## Before you start

Run this once to confirm the starting state is clean and green:

```bash
git status --short
```

Expected: no output (clean tree). If it isn't clean, stop and ask — do not start this plan on top
of uncommitted work.

```bash
uv run pytest
```

Expected: `291 passed`. If this doesn't pass first, stop — something else is broken and this plan
assumes a green baseline.

---

### Task 1: Rewrite the test suite to the target API

TDD in the usual sense (write one failing assertion, make it pass) doesn't fit a pure rename: there
is no new behavior to assert, only new names. So this task writes the *whole* target test file
first — every `Platform`/`PlatformForm` reference already renamed to `Source`/`SourceForm`, every
`reverse("admin:control_platform_...")` already renamed to `control_source_...`. Running it will
fail at **collection**, not at an assertion — that failure (`ImportError: cannot import name
'Source'`) is this task's "red", and it will not turn green until Task 10 finishes threading the
rename through every production file.

**Files:**
- Create: `tests/test_sources.py`
- Delete: `tests/test_platforms.py`

- [ ] **Step 1: Write the new test file**

Create `tests/test_sources.py` with this exact content:

```python
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
```

- [ ] **Step 2: Delete the old test file**

```bash
rm tests/test_platforms.py
```

- [ ] **Step 3: Run it to verify it fails at collection**

Run: `uv run pytest tests/test_sources.py -v`
Expected: collection error —
`ImportError: cannot import name 'SourceForm' from 'control.forms'` (or similar, naming whichever
of `Source`/`SourceForm` Python reaches first). This is the expected "red": nothing production-side
has been renamed yet.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sources.py
git rm tests/test_platforms.py
git commit -m "test: rewrite the platform tab tests against the planned Source rename"
```

---

### Task 2: Rename the model

**Files:**
- Modify: `src/control/models.py:244-274`

- [ ] **Step 1: Replace `PlatformManager`/`Platform` with `SourceManager`/`Source`**

Replace this block (currently lines 244–274 of `src/control/models.py`):

```python
class PlatformManager(models.Manager):
    """Only the Configs that describe a trading platform."""

    def get_queryset(self) -> models.QuerySet[Config]:
        return super().get_queryset().filter(collector_key__startswith=TENDER_KEY_PREFIX)


class Platform(Config):
    """A trading platform to crawl — a Config, seen through a form built for sites.

    Deliberately **not** a table of its own. A site is "what to collect": its domain, listing
    path and TLS quirks are exactly the parameters the collector's schema declares, so storing
    them anywhere but `Config.parameters` would either duplicate the authored intent or leave
    execution reading mutable state after enqueue — the one thing the snapshot exists to
    prevent.

    What this proxy adds is the surface: its own tab, and a form with a field per site attribute
    instead of a JSON blob (see `control.forms.PlatformForm`).
    """

    objects = PlatformManager()

    class Meta:
        proxy = True
        ordering = ["name"]
        verbose_name = "Площадка"
        verbose_name_plural = "Площадки"

    @property
    def domain(self) -> str:
        return str(self.parameters.get("domain") or "")
```

with:

```python
class SourceManager(models.Manager):
    """Only the Configs that describe a trading platform."""

    def get_queryset(self) -> models.QuerySet[Config]:
        return super().get_queryset().filter(collector_key__startswith=TENDER_KEY_PREFIX)


class Source(Config):
    """A site to crawl — a Config, seen through a form built for sites.

    Deliberately **not** a table of its own. A site is "what to collect": its domain, listing
    path and TLS quirks are exactly the parameters the collector's schema declares, so storing
    them anywhere but `Config.parameters` would either duplicate the authored intent or leave
    execution reading mutable state after enqueue — the one thing the snapshot exists to
    prevent.

    What this proxy adds is the surface: its own tab, and a form with a field per site attribute
    instead of a JSON blob (see `control.forms.SourceForm`).

    Named `Source` (not `Platform`, its original name): the manager still only shows tender
    trading-platform sites for now (see the `collector_key__startswith` filter below), but the
    label had to stop implying that every future kind of collected site is a "trading platform" —
    it will not be, once a non-auction source is added.
    """

    objects = SourceManager()

    class Meta:
        proxy = True
        ordering = ["name"]
        verbose_name = "Источник"
        verbose_name_plural = "Источники"

    @property
    def domain(self) -> str:
        return str(self.parameters.get("domain") or "")
```

- [ ] **Step 2: Verify the file still parses and Django's app registry loads it**

Run: `uv run python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings'); django.setup(); from control.models import Source; print(Source)"`
Expected: `ModuleNotFoundError` or `ImportError` **from a different, later file** (e.g.
`control.forms.platform` still importing `Platform`) — not from `control.models` itself. If the
error names `control.models`, the edit above has a typo; fix it before moving on.

- [ ] **Step 3: Commit**

```bash
git add src/control/models.py
git commit -m "refactor: rename the Platform proxy model to Source"
```

---

### Task 3: Rename the form

**Files:**
- Create: `src/control/forms/source.py`
- Delete: `src/control/forms/platform.py`

- [ ] **Step 1: Write the new form file**

Create `src/control/forms/source.py` with this exact content:

```python
"""Authoring form for a source (a site to crawl).

A source *is* a Config — see `control.models.Source`. What differs is how it is filled in: one
field per site attribute instead of a JSON object, with the choices and defaults read from the
collector's own schema so the form cannot drift from what enqueue will accept.

The fields are the union of the four tender schemas, and `clean()` keeps only the ones the
chosen engine actually declares. That is why a Config authored here always validates: the same
`resolve_parameters` that enqueue uses runs on the assembled dict before saving.
"""

from __future__ import annotations

from typing import Any

from django import forms

from collectors import schemas
from collectors.schemas.tender import (
    DEFAULT_LISTING_PATHS,
    ENGINE_KEYS,
    available_certs,
    collector_key,
    engine_of,
)
from control.models import Source

#: Site attributes, in the order they are asked for. Every name is a parameter of at least one
#: tender schema; `_schema_params` decides which of them the chosen engine keeps.
PARAM_FIELDS = (
    "domain",
    "listing_path",
    "max_pages",
    "only_active",
    "concurrency",
    "fetch_details",
    "extra_ca_cert",
    "skip_tls_verify",
)


def _spec(engine: str, name: str):
    return schemas.get_collector(collector_key(engine)).param(name)


def _help(name: str, *, engine: str = "kendo") -> str:
    """The parameter's own description — the schema is the single source of that text."""
    for candidate in (engine, "fogsoft"):
        spec = _spec(candidate, name)
        if spec is not None:
            return spec.description
    return ""


class SourceForm(forms.ModelForm):
    collector_key = forms.ChoiceField(
        label="Движок",
        help_text="Семейство площадок, к которому относится сайт. От него зависит, "
        "как разбираются страницы.",
    )

    domain = forms.URLField(
        label="Домен",
        max_length=200,
        assume_scheme="https",
        help_text=_help("domain"),
    )
    listing_path = forms.CharField(
        label="Путь к листингу",
        max_length=200,
        required=False,
        help_text="Пусто — путь по умолчанию для выбранного движка: "
        + ", ".join(f"{engine} → {path}" for engine, path in DEFAULT_LISTING_PATHS.items()),
    )
    max_pages = forms.IntegerField(
        label="Максимум страниц",
        min_value=0,
        initial=0,
        help_text=_help("max_pages"),
    )
    only_active = forms.BooleanField(
        label="Только незавершённые торги",
        required=False,
        initial=True,
        help_text=_help("only_active"),
    )
    concurrency = forms.IntegerField(
        label="Параллельных запросов",
        min_value=1,
        max_value=16,
        initial=1,
        help_text=_help("concurrency"),
    )
    fetch_details = forms.BooleanField(
        label="Заходить в карточку лота",
        required=False,
        initial=True,
        help_text=_help("fetch_details", engine="fogsoft")
        + " Применимо только к движку iTender (Fogsoft); для остальных игнорируется.",
    )
    extra_ca_cert = forms.ChoiceField(
        label="Доп. сертификат",
        required=False,
        help_text=_help("extra_ca_cert"),
    )
    skip_tls_verify = forms.BooleanField(
        label="Не проверять сертификат",
        required=False,
        help_text=_help("skip_tls_verify"),
    )

    class Meta:
        model = Source
        fields = ["name", "collector_key", "enabled", "archived", "tags", "owner"]
        labels = {"name": "Название источника"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["collector_key"].choices = [
            (collector_key(engine), schemas.get_collector(collector_key(engine)).display_name)
            for engine in ENGINE_KEYS
        ]
        self.fields["extra_ca_cert"].choices = [("", "— обычный набор корневых —")] + [
            (name, name) for name in available_certs()
        ]

        # Fill the site fields from the stored parameters, so editing shows what is authored
        # rather than the form's defaults.
        parameters = getattr(self.instance, "parameters", None) or {}
        for name in PARAM_FIELDS:
            if name in parameters and parameters[name] is not None:
                self.fields[name].initial = parameters[name]

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        key = cleaned.get("collector_key")
        if not key:
            return cleaned

        parameters = self._collect_parameters(key, cleaned)
        try:
            schemas.resolve_parameters(key, parameters)
        except schemas.UnknownCollector:
            self.add_error("collector_key", f"Сборщика {key!r} нет в кодовой базе.")
            return cleaned
        except schemas.ParameterError as exc:
            for message in exc.errors:
                # Point at the field when the message names one; otherwise show it on the form.
                field = message.split(":", 1)[0]
                self.add_error(field if field in self.fields else None, message)
            return cleaned

        cleaned["parameters"] = parameters
        return cleaned

    def _collect_parameters(self, key: str, cleaned: dict[str, Any]) -> dict[str, Any]:
        """The form's site fields → the parameter dict this collector declares.

        Two things are dropped rather than stored: values for parameters the chosen engine does
        not declare (`fetch_details` outside fogsoft), and a blank `listing_path`, which means
        "whatever the engine's default is" — storing the resolved value would freeze today's
        default into every site.
        """
        engine = engine_of(key)
        parameters: dict[str, Any] = {}
        for name in PARAM_FIELDS:
            if _spec(engine, name) is None:
                continue
            value = cleaned.get(name)
            if name in {"listing_path", "extra_ca_cert"} and not value:
                continue
            parameters[name] = value
        return parameters

    def save(self, commit: bool = True) -> Source:
        source = super().save(commit=False)
        source.parameters = self.cleaned_data.get("parameters", source.parameters)
        if commit:
            source.save()
            self.save_m2m()
        return source
```

- [ ] **Step 2: Delete the old form file**

```bash
rm src/control/forms/platform.py
```

- [ ] **Step 3: Verify it imports on its own**

Run: `uv run python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings'); django.setup(); from control.forms.source import SourceForm; print(SourceForm)"`
Expected: prints the class — this file only depends on `control.models.Source`, already renamed
in Task 2, so this import should succeed cleanly (unlike Task 2's check, which still hit a
downstream failure).

- [ ] **Step 4: Commit**

```bash
git add src/control/forms/source.py
git rm src/control/forms/platform.py
git commit -m "refactor: rename PlatformForm to SourceForm"
```

---

### Task 4: Update the forms package export

**Files:**
- Modify: `src/control/forms/__init__.py`

- [ ] **Step 1: Replace the file content**

Replace the full content of `src/control/forms/__init__.py` (currently):

```python
from control.forms.config import ConfigForm
from control.forms.platform import PlatformForm

__all__ = ["ConfigForm", "PlatformForm"]
```

with:

```python
from control.forms.config import ConfigForm
from control.forms.source import SourceForm

__all__ = ["ConfigForm", "SourceForm"]
```

- [ ] **Step 2: Verify**

Run: `uv run python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings'); django.setup(); from control.forms import SourceForm; print(SourceForm)"`
Expected: prints the class, no error.

- [ ] **Step 3: Commit**

```bash
git add src/control/forms/__init__.py
git commit -m "refactor: export SourceForm from control.forms"
```

---

### Task 5: Rename the admin registration

**Files:**
- Modify: `src/control/admin.py:24-33` (imports)
- Modify: `src/control/admin.py:287-368` (the `PlatformAdmin` class)

- [ ] **Step 1: Update the imports**

Replace (currently lines 24–34):

```python
from collectors import schemas
from control.forms import ConfigForm, PlatformForm
from control.models import (
    Collector,
    Config,
    Job,
    JobOrigin,
    JobStatus,
    Platform,
    Schedule,
)
```

with:

```python
from collectors import schemas
from control.forms import ConfigForm, SourceForm
from control.models import (
    Collector,
    Config,
    Job,
    JobOrigin,
    JobStatus,
    Schedule,
    Source,
)
```

- [ ] **Step 2: Rename the admin class and its Russian labels**

Replace the whole `PlatformAdmin` class (currently lines 287–368):

```python
@admin.register(Platform)
class PlatformAdmin(ConfigAdmin):
    """The platform tab: the same Configs, asked for as sites.

    Everything behind it — enqueue, snapshots, schedules, history — is `ConfigAdmin`'s, which is
    why this subclasses it rather than reimplementing the surface. What changes is the form and
    the shape of the page.
    """

    form = PlatformForm
    list_display = (
        "name",
        "engine",
        "site",
        "enabled",
        "archived",
        "last_status_badge",
        "last_run_at",
        "last_job_link",
    )
    list_filter = ("collector_key", "enabled", "archived", "last_status")
    search_fields = ("name",)
    fieldsets = (
        ("Площадка", {"fields": ("name", "collector_key", "domain", "listing_path")}),
        ("Обход", {"fields": ("max_pages", "only_active", "concurrency", "fetch_details")}),
        (
            "TLS",
            {
                "fields": ("extra_ca_cert", "skip_tls_verify"),
                "classes": ("collapse",),
                "description": "Костыли под сайты со сломанной цепочкой сертификатов. "
                "По умолчанию не нужны.",
            },
        ),
        ("Состояние", {"fields": ("enabled", "archived", "tags", "owner")}),
        (
            "Что уйдёт в задачу",
            {"fields": ("resolved_preview",), "classes": ("collapse",)},
        ),
        (
            "Последний запуск (кэш-колонки)",
            {"fields": ("last_status", "last_run_at", "last_job_link"), "classes": ("collapse",)},
        ),
        (
            "Аудит",
            {
                "fields": ("revision", "created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Движок", ordering="collector_key")
    def engine(self, obj: Platform) -> str:
        try:
            return schemas.get_collector(obj.collector_key).display_name
        except schemas.UnknownCollector:
            return f"{obj.collector_key} — нет в кодовой базе"

    @admin.display(description="Сайт")
    def site(self, obj: Platform) -> str:
        return obj.domain or "—"

    @admin.action(description="Включить выбранные площадки")
    def action_enable(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, enabled=True)
        self.message_user(request, f"Включено площадок: {n}.", messages.SUCCESS)

    @admin.action(description="Выключить выбранные площадки")
    def action_disable(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, enabled=False)
        self.message_user(request, f"Выключено площадок: {n}.", messages.SUCCESS)

    @admin.action(description="В архив (мягкое удаление)")
    def action_archive(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, archived=True)
        self.message_user(request, f"Отправлено в архив: {n}.", messages.SUCCESS)

    @admin.action(description="Вернуть из архива")
    def action_unarchive(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, archived=False)
        self.message_user(request, f"Возвращено из архива: {n}.", messages.SUCCESS)
```

with:

```python
@admin.register(Source)
class SourceAdmin(ConfigAdmin):
    """The source tab: the same Configs, asked for as sites.

    Everything behind it — enqueue, snapshots, schedules, history — is `ConfigAdmin`'s, which is
    why this subclasses it rather than reimplementing the surface. What changes is the form and
    the shape of the page.
    """

    form = SourceForm
    list_display = (
        "name",
        "engine",
        "site",
        "enabled",
        "archived",
        "last_status_badge",
        "last_run_at",
        "last_job_link",
    )
    list_filter = ("collector_key", "enabled", "archived", "last_status")
    search_fields = ("name",)
    fieldsets = (
        ("Источник", {"fields": ("name", "collector_key", "domain", "listing_path")}),
        ("Обход", {"fields": ("max_pages", "only_active", "concurrency", "fetch_details")}),
        (
            "TLS",
            {
                "fields": ("extra_ca_cert", "skip_tls_verify"),
                "classes": ("collapse",),
                "description": "Костыли под сайты со сломанной цепочкой сертификатов. "
                "По умолчанию не нужны.",
            },
        ),
        ("Состояние", {"fields": ("enabled", "archived", "tags", "owner")}),
        (
            "Что уйдёт в задачу",
            {"fields": ("resolved_preview",), "classes": ("collapse",)},
        ),
        (
            "Последний запуск (кэш-колонки)",
            {"fields": ("last_status", "last_run_at", "last_job_link"), "classes": ("collapse",)},
        ),
        (
            "Аудит",
            {
                "fields": ("revision", "created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Движок", ordering="collector_key")
    def engine(self, obj: Source) -> str:
        try:
            return schemas.get_collector(obj.collector_key).display_name
        except schemas.UnknownCollector:
            return f"{obj.collector_key} — нет в кодовой базе"

    @admin.display(description="Сайт")
    def site(self, obj: Source) -> str:
        return obj.domain or "—"

    @admin.action(description="Включить выбранные источники")
    def action_enable(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, enabled=True)
        self.message_user(request, f"Включено источников: {n}.", messages.SUCCESS)

    @admin.action(description="Выключить выбранные источники")
    def action_disable(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, enabled=False)
        self.message_user(request, f"Выключено источников: {n}.", messages.SUCCESS)

    @admin.action(description="В архив (мягкое удаление)")
    def action_archive(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, archived=True)
        self.message_user(request, f"Отправлено в архив: {n}.", messages.SUCCESS)

    @admin.action(description="Вернуть из архива")
    def action_unarchive(self, request: HttpRequest, queryset: QuerySet[Config]) -> None:
        n = self._bulk(request, queryset, archived=False)
        self.message_user(request, f"Возвращено из архива: {n}.", messages.SUCCESS)
```

- [ ] **Step 3: Verify Django's admin registry loads**

Run: `uv run python src/manage.py check`
Expected: `System check identified no issues (0 silenced).` — this is the first point in the plan
where the whole `control` app must import cleanly (admin.py touches models, forms, and the
templates it points at), so this check only passes once every earlier task's rename is
self-consistent.

- [ ] **Step 4: Commit**

```bash
git add src/control/admin.py
git commit -m "refactor: rename PlatformAdmin to SourceAdmin and its Russian labels"
```

---

### Task 6: Rename the seed command

**Files:**
- Create: `src/control/management/commands/seed_sources.py`
- Delete: `src/control/management/commands/seed_platforms.py`

- [ ] **Step 1: Write the new command file**

Create `src/control/management/commands/seed_sources.py` with this exact content (identical to
the old file except the docstring, the `Platform` import/usage, and the command's own `help` text
and success message — the `SOURCES` data and the domain-based idempotency check are untouched):

```python
"""Initial data: the sites the temporary parser project already crawled.

Typing thirty-one sites into a form is nobody's idea of onboarding, so the list the temporary
project kept in `platforms.toml` is carried over once, here. This is *initial data*, not a source
of truth: after the first run the sites live in the database and are edited in the admin.
Re-running the command adds what is missing and leaves existing sites alone — it never
overwrites an edit.

Sites the temporary project had switched off are created switched off, with the reason printed
rather than stored: `Config` has nowhere to keep a note, and inventing a column for one is worse
than a line in the log.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from collectors.schemas.tender import collector_key
from control.models import Config, Source

#: (engine, title, domain, extras). Extras carry only what differs from the engine defaults.
SOURCES: list[dict[str, Any]] = [
    # --- iTender / Fogsoft -------------------------------------------------------------
    {"engine": "fogsoft", "title": "Центр реализации", "domain": "https://bankrupt.centerr.ru"},
    {
        "engine": "fogsoft",
        "title": "uTender",
        "domain": "http://utender.ru",
        "enabled": False,
        "note": "Пагинация не двигается — перекачивает первую страницу. Включить после фикса.",
    },
    {"engine": "fogsoft", "title": "АЛЬФАЛОТ", "domain": "https://bankrupt.alfalot.ru"},
    {
        "engine": "fogsoft",
        "title": "Уральская электронная торговая площадка",
        "domain": "https://bankrupt.etpu.ru",
    },
    {
        "engine": "fogsoft",
        "title": "Балтийская электронная площадка",
        "domain": "https://bankruptcy.bepspb.ru",
    },
    {
        "engine": "fogsoft",
        "title": "АРБбитЛот",
        "domain": "https://torgi.arbbitlot.ru",
        "params": {"skip_tls_verify": True},
        "note": "Сертификат сайта просрочен на их стороне — набор CA не помогает.",
    },
    {"engine": "fogsoft", "title": "Арбитат", "domain": "http://arbitat.ru"},
    {
        "engine": "fogsoft",
        "title": "Объединённая торговая площадка",
        "domain": "https://bankrupt.utpl.ru",
    },
    {"engine": "fogsoft", "title": "Tender Technologies", "domain": "https://bankrupt.tender.one"},
    {"engine": "fogsoft", "title": "ЭТП Югра", "domain": "https://etpugra.ru"},
    {"engine": "fogsoft", "title": "ТЕНДЕР ГАРАНТ", "domain": "https://tendergarant.com"},
    {"engine": "fogsoft", "title": "ЮЭТП", "domain": "https://torgibankrot.ru"},
    {
        "engine": "fogsoft",
        "title": "МЕТА-ИНВЕСТ",
        "domain": "https://meta-invest.ru",
        "params": {"extra_ca_cert": "meta_invest_globalsign_gcc_r3_dv_tls_ca_2020.pem"},
        "note": "Сервер не отдаёт промежуточный сертификат цепочки — подставляем свой.",
    },
    {
        "engine": "fogsoft",
        "title": "Property Trade",
        "domain": "https://propertytrade.ru",
        "enabled": False,
        "note": "Было выключено во временном проекте без указания причины — проверить.",
    },
    {
        "engine": "fogsoft",
        "title": "ЭТП Регион (GloriaService)",
        "domain": "https://gloriaservice.ru",
    },
    {
        "engine": "fogsoft",
        "title": "ЭТП Заказ РФ",
        "domain": "http://bankrot.zakazrf.ru",
        "enabled": False,
        "note": "Пагинация работает исправно (проверено вживую 2026-07-30), но за 200 страниц "
        "нашёлся только один лот, не помеченный как завершённый, — площадка фактически архив "
        "закрытых торгов. Включить, если появятся живые лоты.",
    },
    {"engine": "fogsoft", "title": "ЕЭТП / ets24.ru", "domain": "http://bankrupt.ets24.ru"},
    # --- Kendo-ETP ---------------------------------------------------------------------
    {"engine": "kendo", "title": "Альянс Трэйд", "domain": "https://trade-alliance.ru"},
    {"engine": "kendo", "title": "Селтим", "domain": "https://bankrupt.seltim.ru"},
    {
        "engine": "kendo",
        "title": "Электро-Торги",
        "domain": "https://bankrotstvo.electro-torgi.ru",
    },
    {"engine": "kendo", "title": "Торги82", "domain": "https://lot.torgi82.ru"},
    {
        "engine": "kendo",
        "title": "ВЭТП",
        "domain": "https://банкрот.вэтп.рф",
        "note": "IDN-домен, хранится в Unicode — curl_cffi кодирует в punycode сам.",
    },
    # --- btorg / edoc-ETP --------------------------------------------------------------
    {"engine": "btorg", "title": "Аукционный тендерный центр", "domain": "https://atctrade.ru"},
    {"engine": "btorg", "title": "Аукционы Сибири", "domain": "https://ausib.ru"},
    {"engine": "btorg", "title": "ЭТП Профит", "domain": "https://etp-profit.ru"},
    {"engine": "btorg", "title": "Аукционный центр", "domain": "https://aukcioncenter.ru"},
    {"engine": "btorg", "title": "Региональная торговая площадка", "domain": "https://regtorg.com"},
    {"engine": "btorg", "title": "ПТП-Центр", "domain": "https://ptp-center.ru"},
    # --- rus-on ------------------------------------------------------------------------
    {"engine": "ruson", "title": "Новые информационные сервисы", "domain": "https://nistp.ru"},
    {"engine": "ruson", "title": "Электронные торги", "domain": "https://el-torg.com"},
    {"engine": "ruson", "title": "РОССИЯ ОнЛайн", "domain": "https://rus-on.ru"},
    {
        "engine": "ruson",
        "title": "Объединённые системы торгов",
        "domain": "https://sistematorg.com",
        "params": {"listing_path": "tradelist.php"},
    },
    {
        "engine": "ruson",
        "title": "Промконсалт",
        "domain": "https://promkonsalt.ru",
        "params": {"listing_path": "tradelist.php"},
    },
]


class Command(BaseCommand):
    help = "Create the sources carried over from the temporary parser project (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        created, kept = 0, 0

        for spec in SOURCES:
            key = collector_key(spec["engine"])
            domain = spec["domain"]
            parameters = {"domain": domain, **spec.get("params", {})}

            # The domain is the identity: a source renamed in the admin must not be re-created
            # here under its old name.
            if Config.objects.filter(parameters__domain=domain).exists():
                kept += 1
                continue

            created += 1
            self.stdout.write(f"+ {spec['title']} ({domain})")
            if spec.get("note"):
                self.stdout.write(f"    {spec['note']}")
            if not dry_run:
                Source.objects.create(
                    name=spec["title"],
                    collector_key=key,
                    parameters=parameters,
                    enabled=spec.get("enabled", True),
                )

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(f"{prefix}источников создано: {created}, уже было: {kept}")
        )
        if dry_run:
            transaction.set_rollback(True)
```

- [ ] **Step 2: Delete the old command file**

```bash
rm src/control/management/commands/seed_platforms.py
```

- [ ] **Step 3: Verify the command is registered**

Run: `uv run python src/manage.py help seed_sources`
Expected: prints the command's help text (`Create the sources carried over from the temporary
parser project (idempotent)... --dry-run ...`), not an "Unknown command" error.

- [ ] **Step 4: Commit**

```bash
git add src/control/management/commands/seed_sources.py
git rm src/control/management/commands/seed_platforms.py
git commit -m "refactor: rename seed_platforms command to seed_sources"
```

---

### Task 7: Write the migration

**Files:**
- Create: `src/control/migrations/0006_rename_platform_to_source.py`

- [ ] **Step 1: Write the migration**

Create `src/control/migrations/0006_rename_platform_to_source.py` with this exact content:

```python
from django.db import migrations


class Migration(migrations.Migration):
    """Renames the proxy model, not a table: `Platform` has never had one of its own.

    A single `RenameModel` operation — not the `DeleteModel` + `CreateModel` a non-interactive
    `makemigrations` would generate for a plain class rename — because `RenameModel` is what lets
    Django's contenttypes framework update the existing `ContentType` row in place instead of
    replacing it. Replacing it would orphan every `control.*_platform` permission already granted
    (e.g. to the `petr` user) and any admin `LogEntry` history recorded against the old
    `ContentType` row.
    """

    dependencies = [
        ("control", "0005_remove_job_collector_version_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Platform",
            new_name="Source",
        ),
    ]
```

- [ ] **Step 2: Verify Django has nothing further to detect**

Run: `uv run python src/manage.py makemigrations --check --dry-run`
Expected: `No changes detected` — proves the hand-written migration's end state matches exactly
what `models.py` now declares, with nothing left over.

- [ ] **Step 3: Commit**

```bash
git add src/control/migrations/0006_rename_platform_to_source.py
git commit -m "migrate: rename the Platform proxy model to Source via RenameModel"
```

---

### Task 8: Update the admin sidebar

**Files:**
- Modify: `src/project/settings.py:143-147`

- [ ] **Step 1: Update the sidebar entry**

Replace (currently within `UNFOLD["SIDEBAR"]["navigation"]`, the "Сбор данных" group's first
item):

```python
(
    {
        "title": "Площадки",
        "icon": "language",
        "link": reverse_lazy("admin:control_platform_changelist"),
    },
)
```

with:

```python
(
    {
        "title": "Источники",
        "icon": "language",
        "link": reverse_lazy("admin:control_source_changelist"),
    },
)
```

- [ ] **Step 2: Verify**

Run: `uv run python src/manage.py check`
Expected: `System check identified no issues (0 silenced).` (a bad `reverse_lazy` target would
only fail when actually resolved at request time, not at `check` — Task 11's admin smoke test is
what actually exercises this URL name).

- [ ] **Step 3: Commit**

```bash
git add src/project/settings.py
git commit -m "refactor: rename the sidebar's Площадки entry to Источники"
```

---

### Task 9: Update the Makefile

**Files:**
- Modify: `Makefile:14` (`.PHONY` line)
- Modify: `Makefile:42-43` (the `platforms` target)

- [ ] **Step 1: Update the `.PHONY` declaration**

Replace:

```makefile
.PHONY: help install env check migrations migrate seed platforms collectors run worker scheduler tick \
        shell superuser test test-unit lint fmt contracts verify \
        up down restart build logs ps db docker-migrate docker-seed docker-shell clean reset-db
```

with:

```makefile
.PHONY: help install env check migrations migrate seed sources collectors run worker scheduler tick \
        shell superuser test test-unit lint fmt contracts verify \
        up down restart build logs ps db docker-migrate docker-seed docker-shell clean reset-db
```

- [ ] **Step 2: Rename the target**

Replace:

```makefile
platforms:  ## Create the trading platforms carried over from the parser project (idempotent)
	$(MANAGE) seed_platforms
```

with:

```makefile
sources:  ## Create the sources carried over from the parser project (idempotent)
	$(MANAGE) seed_sources
```

- [ ] **Step 3: Verify**

Run: `make help | grep sources`
Expected: `  sources          Create the sources carried over from the parser project (idempotent)`

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "refactor: rename make platforms to make sources"
```

---

### Task 10: Update the READMEs

**Files:**
- Modify: `README.md:96, 112, 130`
- Modify: `README.ru.md:98, 116, 135`

- [ ] **Step 1: Update `README.md` line 96**

Replace:

```
* **`/admin/control/platform/`** — «Площадки»: the trading platforms to crawl. The same Configs,
  asked for as sites — domain, listing path, TLS quirks — instead of as a JSON object.
```

with:

```
* **`/admin/control/source/`** — «Источники»: the trading platforms to crawl. The same Configs,
  asked for as sites — domain, listing path, TLS quirks — instead of as a JSON object.
```

- [ ] **Step 2: Update `README.md` line 112 (only the command name, not the surrounding prose)**

Replace:

```
ordinary parameters, so adding a platform is filling in a form — there is no site list in the
repository. `make platforms` carries over the thirty-three sites the parser project already
crawled; after that they live in the admin.
```

with:

```
ordinary parameters, so adding a source is filling in a form — there is no site list in the
repository. `make sources` carries over the thirty-three sites the parser project already
crawled; after that they live in the admin.
```

- [ ] **Step 3: Update `README.md` line 130**

Replace:

```
| `make platforms` | `seed_platforms` | Create the 33 trading platforms carried over from the parser project. Initial data, not a source of truth — after this they are edited in the admin. Idempotent, `--dry-run` available. |
```

with:

```
| `make sources` | `seed_sources` | Create the 33 trading platforms carried over from the parser project. Initial data, not a source of truth — after this they are edited in the admin. Idempotent, `--dry-run` available. |
```

- [ ] **Step 4: Update `README.ru.md` line 98**

Replace:

```
* **`/admin/control/platform/`** — «Площадки»: сайты торговых площадок, которые обходят парсеры.
  Это те же `Config`, но спрашиваются как сайт — домен, путь к листингу, костыли под TLS —
  а не как JSON-объект.
```

with:

```
* **`/admin/control/source/`** — «Источники»: сайты торговых площадок, которые обходят парсеры.
  Это те же `Config`, но спрашиваются как сайт — домен, путь к листингу, костыли под TLS —
  а не как JSON-объект.
```

- [ ] **Step 5: Update `README.ru.md` line 116**

Replace:

```
**Сборщик — это движок, а площадка — это данные.** Домен, путь к листингу и костыли под TLS —
обычные параметры, поэтому добавить площадку значит заполнить форму: списка сайтов в репозитории
нет. `make platforms` переносит 33 площадки, которые уже обходил временный проект; дальше они
живут в админке.
```

with:

```
**Сборщик — это движок, а источник — это данные.** Домен, путь к листингу и костыли под TLS —
обычные параметры, поэтому добавить источник значит заполнить форму: списка сайтов в репозитории
нет. `make sources` переносит 33 источника, которые уже обходил временный проект; дальше они
живут в админке.
```

- [ ] **Step 6: Update `README.ru.md` line 135**

Replace:

```
| `make platforms` | `seed_platforms` | Создаёт 33 торговые площадки, перенесённые из временного проекта парсеров. Это стартовые данные, а не источник правды: дальше площадки правятся в админке. Идемпотентно, есть `--dry-run`. |
```

with:

```
| `make sources` | `seed_sources` | Создаёт 33 торговые площадки, перенесённые из временного проекта парсеров. Это стартовые данные, а не источник правды: дальше источники правятся в админке. Идемпотентно, есть `--dry-run`. |
```

- [ ] **Step 7: Verify no stale references remain in either README**

Run: `grep -n "control/platform/\|make platforms\|seed_platforms" README.md README.ru.md`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add README.md README.ru.md
git commit -m "docs: update the READMEs for the Source rename"
```

---

### Task 11: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:34, 36, 146`

- [ ] **Step 1: Update the repo map's `models.py` line**

Replace:

```
    models.py             Collector projection, Config, Platform (proxy), Schedule, Job
```

with:

```
    models.py             Collector projection, Config, Source (proxy), Schedule, Job
```

- [ ] **Step 2: Update the repo map's `forms/` line**

Replace:

```
    forms/                authoring forms: Config (JSON) and Platform (a field per site attribute)
```

with:

```
    forms/                authoring forms: Config (JSON) and Source (a field per site attribute)
```

- [ ] **Step 3: Update D17**

Replace:

```
| D17 | The «Площадки» tab is `control.models.Platform`, a **proxy of Config** with its own form, not a table. | A platform *is* "what to collect". A second table would duplicate authored intent and need syncing back into the Config that actually runs. The proxy adds a tab and a per-field form with no new state. |
```

with:

```
| D17 | The «Источники» tab is `control.models.Source` (renamed from `Platform` on 2026-07-30 — the manager still only shows tender trading-platform sites, but the label had to stop implying every future source will be one), a **proxy of Config** with its own form, not a table. | A source *is* "what to collect". A second table would duplicate authored intent and need syncing back into the Config that actually runs. The proxy adds a tab and a per-field form with no new state. |
```

Note: this is a rename, not a reversal of the decision's substance — D17 is edited in place, the
way D16/D19 distinguish "the decision changed" (which gets struck through and marked superseded)
from "the name changed" (which doesn't need that ceremony).

- [ ] **Step 4: Verify no stale reference to the old name remains in CLAUDE.md**

Run: `grep -n "Platform\b" CLAUDE.md`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for the Platform -> Source rename"
```

---

### Task 12: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full local test suite**

Run: `uv run pytest`
Expected: `291 passed`. This is the point where Task 1's rewritten `tests/test_sources.py`
finally goes green — every production file it depends on has now been renamed consistently.

- [ ] **Step 2: Run the rest of `make verify`**

Run: `make verify`
Expected: `check` clean, `makemigrations --check --dry-run` reports `No changes detected`,
`ruff check .` and `ruff format --check .` both clean, `lint-imports` reports all 4 contracts
`KEPT`, then the same `291 passed`.

- [ ] **Step 3: Grep the whole repo for anything left over**

Run: `grep -rn "Platform\|PlatformForm\|PlatformAdmin\|PlatformManager\|seed_platforms\|control_platform_" src/ tests/ README.md README.ru.md CLAUDE.md Makefile 2>/dev/null`
Expected: no output. (Historical files are expected to still say "platform": `docs/architecture/adr/0002-tender-site-collectors.md`, `src/control/migrations/0003_platform.py`'s filename and its own content, and `0004_lot.py`'s dependency string naming that old migration file — none of those are in the grep's path list, so a clean result here does not need to touch them.)

- [ ] **Step 4: Apply the migration on the live containers and verify the ContentType survived the rename**

```bash
docker compose exec -T web python src/manage.py migrate control
```

Expected: `Applying control.0006_rename_platform_to_source... OK`

```bash
docker compose exec -T web python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')
django.setup()
from django.contrib.contenttypes.models import ContentType
from control.models import Source
ct = ContentType.objects.get_for_model(Source)
print('content type model name:', ct.model)
print('source rows:', Source.objects.count())
from django.contrib.auth import get_user_model
petr = get_user_model().objects.get(username='petr')
print('petr can view sources:', petr.has_perm('control.view_source'))
"
```

Expected: `content type model name: source`, `source rows: 33`, `petr can view sources: True`.
If `petr can view sources` prints `False`, the `RenameModel` did not carry the permission the way
this plan assumes — stop and investigate before continuing (do not silently re-grant the
permission under the new codename, since that would mask whether the rename actually preserved
identity).

- [ ] **Step 5: Restart the containers and smoke-test the admin**

```bash
docker compose restart web worker scheduler
```

```bash
docker compose exec -T web python src/manage.py shell -c "
from django.test import Client
from django.contrib.auth import get_user_model
c = Client()
admin = get_user_model().objects.get(username='admin')
c.force_login(admin)
for path in ['/admin/', '/admin/control/source/', '/admin/control/source/add/']:
    r = c.get(path)
    print(path, r.status_code)
body = c.get('/admin/').content.decode()
print('sidebar says Источники:', 'Источники' in body)
print('sidebar no longer says Площадки:', 'Площадки' not in body)
"
```

Expected: all three paths return `200`, `sidebar says Источники: True`,
`sidebar no longer says Площадки: True`.

- [ ] **Step 6: Final commit if anything was adjusted during verification**

If Steps 1–5 required no code changes, there is nothing to commit — the twelve commits from
Tasks 1–11 already cover the whole rename. If any fix was needed, commit it now with a message
describing what verification caught.
