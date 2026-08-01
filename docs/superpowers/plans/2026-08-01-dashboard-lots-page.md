# Dashboard Lots Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Лоты" page to `/dashboard/` that lists lots stored in MongoDB (filterable by source, paginated, sorted by most-recently-seen) with a per-lot detail page showing every stored field.

**Architecture:** A new `control/services/mongo.py` gives `control` its own lazily-cached `pymongo.MongoClient` — `control` cannot import `execution` (see the import-linter contract in `pyproject.toml`), so this is a second, independent client rather than a reuse of `execution.worker.mongo`. `control/services/lots.py` is a thin read-only query layer (`list_lots`, `get_lot`) on top of it, taking an optional injected `collection` for tests (the same dependency-injection shape `MongoLotSink.__init__` already uses). Two new plain-function views (`lots_list`, `lot_detail`) in the existing `control/dashboard/` app render two new templates that extend `dashboard/base.html`, matching the Unfold-styled house look already established for the configs/jobs dashboard. The list and detail pages are built together in one task because the list template links to the detail page — building them separately would leave an intermediate state where the list page's own tests can't pass.

**Tech Stack:** Django, `pymongo` (already a dependency via `execution.worker.mongo`), `mongomock` (already a dev dependency, used by `tests/test_mongo_lot_sink.py`) for tests — no new dependencies.

**Reference:** Design doc at [`docs/superpowers/specs/2026-08-01-dashboard-lots-page-design.md`](../specs/2026-08-01-dashboard-lots-page-design.md).

---

## Task 1: Read-only Mongo service layer

**Files:**
- Create: `src/control/services/mongo.py`
- Create: `src/control/services/lots.py`
- Test: `tests/test_lots_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lots_service.py`:

```python
"""Unit tests for the read-only lots query layer — mirrors test_mongo_lot_sink.py's use of
mongomock for a fake pymongo collection, but exercises reads instead of the sink's writes."""

from __future__ import annotations

from datetime import timedelta

import mongomock
import pytest
from bson import ObjectId
from django.utils import timezone

import control.services.lots as lots_module
from control.services.lots import get_lot, list_lots


@pytest.fixture
def collection():
    return mongomock.MongoClient()["dashboard-test"]["lots"]


def make_lot(collection, **overrides) -> dict:
    doc = {
        "source": "bankrupt.centerr.ru",
        "lot_id": "0025093_1",
        "lot_num": "1",
        "status": "Идут торги",
        "is_active": True,
        "price": 270000.0,
        "bidding_deadline": None,
        "attachments": [],
        "price_schedule": [],
        "extra": {},
    }
    doc.update(overrides)
    doc.setdefault("last_seen_at", timezone.now())
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


class TestListLots:
    def test_returns_all_lots_when_no_source_filter_is_given(self, collection):
        make_lot(collection, lot_id="a", source="site-a")
        make_lot(collection, lot_id="b", source="site-b")

        page = list_lots(source=None, page=1, collection=collection)

        assert page.total_count == 2
        assert {item["lot_id"] for item in page.items} == {"a", "b"}

    def test_filters_by_source(self, collection):
        make_lot(collection, lot_id="a", source="site-a")
        make_lot(collection, lot_id="b", source="site-b")

        page = list_lots(source="site-a", page=1, collection=collection)

        assert [item["lot_id"] for item in page.items] == ["a"]
        assert page.total_count == 1

    def test_orders_by_last_seen_at_descending(self, collection):
        older = timezone.now() - timedelta(days=1)
        newer = timezone.now()
        make_lot(collection, lot_id="old", last_seen_at=older)
        make_lot(collection, lot_id="new", last_seen_at=newer)

        page = list_lots(source=None, page=1, collection=collection)

        assert [item["lot_id"] for item in page.items] == ["new", "old"]

    def test_paginates_using_the_page_size(self, collection, monkeypatch):
        monkeypatch.setattr(lots_module, "PAGE_SIZE", 2)
        for i in range(5):
            make_lot(
                collection, lot_id=str(i), last_seen_at=timezone.now() + timedelta(seconds=i)
            )

        first = list_lots(source=None, page=1, collection=collection)
        second = list_lots(source=None, page=2, collection=collection)

        assert len(first.items) == 2
        assert len(second.items) == 2
        assert first.total_pages == 3
        first_ids = {item["lot_id"] for item in first.items}
        second_ids = {item["lot_id"] for item in second.items}
        assert first_ids.isdisjoint(second_ids)

    def test_out_of_range_page_clamps_to_the_last_page(self, collection):
        make_lot(collection, lot_id="only")

        page = list_lots(source=None, page=99, collection=collection)

        assert page.page == 1

    def test_lists_distinct_sources_regardless_of_the_active_filter(self, collection):
        make_lot(collection, lot_id="a", source="site-a")
        make_lot(collection, lot_id="b", source="site-b")

        page = list_lots(source="site-a", page=1, collection=collection)

        assert page.sources == ["site-a", "site-b"]


class TestGetLot:
    def test_returns_the_matching_document(self, collection):
        stored = make_lot(collection)

        found = get_lot(str(stored["_id"]), collection=collection)

        assert found["lot_id"] == "0025093_1"

    def test_returns_none_for_an_id_that_does_not_exist(self, collection):
        assert get_lot(str(ObjectId()), collection=collection) is None

    def test_returns_none_for_a_malformed_id(self, collection):
        assert get_lot("not-an-object-id", collection=collection) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_lots_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'control.services.lots'` (neither file exists yet).

- [ ] **Step 3: Create the `control`-side Mongo client**

Create `src/control/services/mongo.py`:

```python
"""A second Mongo client, for the web process's read path.

`execution.worker.mongo` owns the worker's client, but `control` may not import `execution` (see
the "control does not import execution" contract in `pyproject.toml`) — the web process and the
worker process are separate processes anyway, so this is its own lazily-cached
`pymongo.MongoClient`, mirroring that module's pattern rather than reusing its code.
"""

from __future__ import annotations

from django.conf import settings
from pymongo import MongoClient
from pymongo.collection import Collection

_client: MongoClient | None = None


def get_lots_collection() -> Collection:
    global _client
    if _client is None:
        _client = MongoClient(settings.MONGO_URI, tz_aware=True)
    return _client[settings.MONGO_DB_NAME]["lots"]
```

- [ ] **Step 4: Create the lots query layer**

Create `src/control/services/lots.py`:

```python
"""Read-only queries against the `lots` Mongo collection, for the dashboard's lots page.

Nothing here writes — `execution.worker.mongo_lot_sink.MongoLotSink` owns that. `collection` is an
optional injected `pymongo.collection.Collection`, the same dependency-injection shape
`MongoLotSink.__init__` already uses, so tests can pass a `mongomock` collection directly instead of
monkeypatching `get_lots_collection`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.collection import Collection

from control.services.mongo import get_lots_collection

#: Fixed page size for the lots list — no UI to change it, so a plain module constant.
PAGE_SIZE = 50


@dataclass
class LotsPage:
    items: list[dict]
    page: int
    total_pages: int
    total_count: int
    sources: list[str]

    @property
    def page_range(self) -> range:
        return range(1, self.total_pages + 1)


def list_lots(
    *, source: str | None, page: int, collection: Collection | None = None
) -> LotsPage:
    collection = collection if collection is not None else get_lots_collection()
    query: dict[str, object] = {"source": source} if source else {}

    total_count = collection.count_documents(query)
    total_pages = max(1, ceil(total_count / PAGE_SIZE))
    page = min(max(page, 1), total_pages)

    items = list(
        collection.find(query)
        .sort("last_seen_at", -1)
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    sources = sorted(collection.distinct("source"))

    return LotsPage(
        items=items,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        sources=sources,
    )


def get_lot(id: str, *, collection: Collection | None = None) -> dict | None:
    collection = collection if collection is not None else get_lots_collection()
    try:
        object_id = ObjectId(id)
    except InvalidId:
        return None
    return collection.find_one({"_id": object_id})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_lots_service.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/control/services/mongo.py src/control/services/lots.py tests/test_lots_service.py
git commit -m "$(cat <<'EOF'
feat: add a read-only Mongo query layer for lots

EOF
)"
```

---

## Task 2: Lots list and detail pages

**Files:**
- Modify: `src/control/dashboard/views.py`
- Modify: `src/control/dashboard/urls.py`
- Create: `src/control/templates/dashboard/lots.html`
- Create: `src/control/templates/dashboard/lot_detail.html`
- Modify: `src/project/settings.py`
- Test: `tests/test_dashboard_lots.py`

The list template links each row to its detail page, so both views/URLs/templates are built in one
pass — a list-only intermediate state would `NoReverseMatch` on its own tests the moment a row is
rendered.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_lots.py`:

```python
"""HTTP-level tests for the read-only lots pages — mirrors test_dashboard.py's shape, with a
mongomock collection injected in place of `control.services.lots.get_lots_collection`."""

from __future__ import annotations

import mongomock
import pytest
from bson import ObjectId
from django.urls import reverse
from django.utils import timezone

import control.services.lots as lots_module

pytestmark = pytest.mark.django_db


@pytest.fixture
def lots_collection(monkeypatch):
    collection = mongomock.MongoClient()["dashboard-test"]["lots"]
    monkeypatch.setattr(lots_module, "get_lots_collection", lambda: collection)
    return collection


def make_lot(collection, **overrides) -> dict:
    doc = {
        "source": "bankrupt.centerr.ru",
        "lot_id": "0025093_1",
        "lot_num": "1",
        "status": "Идут торги",
        "is_active": True,
        "price": 270000.0,
        "bidding_deadline": None,
        "debtor": None,
        "lot_url": None,
        "attachments": [],
        "price_schedule": [],
        "extra": {},
    }
    doc.update(overrides)
    doc.setdefault("last_seen_at", timezone.now())
    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def test_lots_list_requires_staff(client, lots_collection):
    response = client.get(reverse("dashboard:lots_list"))
    assert response.status_code == 302


def test_lots_list_renders_the_unfold_admin_chrome(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"))
    assert response.status_code == 200
    assert "Источники".encode() in response.content


def test_lots_list_shows_stored_lots(client, user, lots_collection):
    make_lot(lots_collection, lot_num="42")
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"))
    assert b"42" in response.content


def test_lots_list_filters_by_source(client, user, lots_collection):
    make_lot(lots_collection, lot_id="a", source="site-a", lot_num="AAA")
    make_lot(lots_collection, lot_id="b", source="site-b", lot_num="BBB")
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"), {"source": "site-a"})
    assert b"AAA" in response.content
    assert b"BBB" not in response.content


def test_lots_list_page_links_preserve_the_source_filter(
    client, user, lots_collection, monkeypatch
):
    monkeypatch.setattr(lots_module, "PAGE_SIZE", 1)
    make_lot(lots_collection, lot_id="a", source="site-a")
    make_lot(lots_collection, lot_id="b", source="site-a")
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"), {"source": "site-a"})
    assert b"source=site-a&page=2" in response.content


def test_lots_list_shows_the_navigation_link(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert reverse("dashboard:lots_list").encode() in response.content
    assert "Лоты".encode() in response.content


def test_lots_list_links_to_the_detail_page(client, user, lots_collection):
    stored = make_lot(lots_collection)
    client.force_login(user)
    response = client.get(reverse("dashboard:lots_list"))
    assert reverse("dashboard:lot_detail", args=[str(stored["_id"])]).encode() in response.content


def test_lot_detail_renders_the_main_fields(client, user, lots_collection):
    stored = make_lot(
        lots_collection,
        debtor="ООО «Должник»",
        lot_url="https://bankrupt.centerr.ru/lot/1",
    )
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=[str(stored["_id"])]))
    assert response.status_code == 200
    assert "ООО «Должник»".encode() in response.content
    assert b"https://bankrupt.centerr.ru/lot/1" in response.content


def test_lot_detail_renders_json_fields(client, user, lots_collection):
    stored = make_lot(lots_collection, attachments=[{"name": "file.pdf"}])
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=[str(stored["_id"])]))
    assert b"file.pdf" in response.content


def test_lot_detail_404s_for_an_unknown_id(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=[str(ObjectId())]))
    assert response.status_code == 404


def test_lot_detail_404s_for_a_malformed_id(client, user, lots_collection):
    client.force_login(user)
    response = client.get(reverse("dashboard:lot_detail", args=["not-an-id"]))
    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dashboard_lots.py -v`
Expected: FAIL — `reverse("dashboard:lots_list")` raises `NoReverseMatch` (neither URL exists yet).

- [ ] **Step 3: Add the two views**

In `src/control/dashboard/views.py`, add `import json` above the other imports:

```python
from __future__ import annotations

import json

from collections import OrderedDict
```

Change the `django.http` import to also bring in `Http404`:

```python
from django.http import Http404, HttpRequest, HttpResponse
```

Add this import alongside the other `control` imports (after `from control.services import
EnqueueRefused, enqueue, request_cancel`):

```python
from control.services.lots import get_lot, list_lots
```

Add these two views at the end of the file, after `_status_counts`:

```python
@staff_member_required
def lots_list(request: HttpRequest) -> HttpResponse:
    source = request.GET.get("source", "").strip() or None
    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 1

    lots_page = list_lots(source=source, page=page)

    return render(
        request,
        "dashboard/lots.html",
        {
            **admin.site.each_context(request),
            "title": "Лоты",
            "lots_page": lots_page,
            "source": source or "",
        },
    )


@staff_member_required
def lot_detail(request: HttpRequest, id: str) -> HttpResponse:
    lot = get_lot(id)
    if lot is None:
        raise Http404("Лот не найден.")

    fields_json = {
        name: json.dumps(lot.get(name), indent=2, ensure_ascii=False, default=str)
        for name in ("attachments", "price_schedule", "extra")
    }

    return render(
        request,
        "dashboard/lot_detail.html",
        {
            **admin.site.each_context(request),
            "title": f"Лот {lot.get('lot_num') or lot['_id']}",
            "lot": lot,
            "fields_json": fields_json,
        },
    )
```

- [ ] **Step 4: Add the URLs**

In `src/control/dashboard/urls.py`, add two lines inside `urlpatterns`:

```python
    path("lots/", views.lots_list, name="lots_list"),
    path("lots/<str:id>/", views.lot_detail, name="lot_detail"),
```

Full file after the change:

```python
from django.urls import path

from control.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("jobs/", views.jobs_panel, name="jobs_panel"),
    path("configs/run-selected/", views.run_selected, name="run_selected"),
    path("configs/<int:pk>/run/", views.run_now, name="run_now"),
    path("jobs/<int:pk>/cancel/", views.cancel_job, name="cancel_job"),
    path("lots/", views.lots_list, name="lots_list"),
    path("lots/<str:id>/", views.lot_detail, name="lot_detail"),
]
```

- [ ] **Step 5: Add the `lots.html` template**

Create `src/control/templates/dashboard/lots.html`:

```html
{% extends "dashboard/base.html" %}

{% block content %}
  <h1 class="text-lg font-semibold text-important mb-4">Лоты</h1>

  <form method="get" class="mb-4 flex flex-wrap items-end gap-3">
    <div>
      <label class="block text-xs font-medium text-base-500 dark:text-base-400 mb-1" for="source">Источник</label>
      <select id="source" name="source"
              class="border border-base-200 bg-white font-medium rounded-default shadow-xs text-sm dark:bg-base-900 dark:border-base-700 dark:text-font-default-dark px-3 py-2 pr-8">
        <option value="">Все</option>
        {% for s in lots_page.sources %}
          <option value="{{ s }}" {% if s == source %}selected{% endif %}>{{ s }}</option>
        {% endfor %}
      </select>
    </div>
    <button type="submit" class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-3 py-2 border border-base-200 bg-white shadow-xs text-important dark:border-base-700 dark:bg-transparent hover:bg-base-100/80 dark:hover:bg-base-800/80">
      Применить
    </button>
    {% if source %}
      <a href="{% url 'dashboard:lots_list' %}" class="text-sm text-base-500 dark:text-base-400 underline">Сбросить</a>
    {% endif %}
  </form>

  <div class="overflow-x-auto rounded-default border border-base-200 shadow-xs dark:border-base-800 bg-white dark:bg-base-900">
    <table class="w-full border-spacing-none border-separate whitespace-nowrap">
      <thead>
        <tr>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Источник</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Номер лота</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Статус</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Цена</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Дедлайн торгов</th>
        </tr>
      </thead>
      <tbody>
        {% for lot in lots_page.items %}
          <tr class="border-t border-base-200 dark:border-base-800">
            <td class="px-3 py-2">
              <a href="{% url 'dashboard:lot_detail' lot._id %}" class="text-important hover:underline">{{ lot.source }}</a>
            </td>
            <td class="px-3 py-2">{{ lot.lot_num|default:"—" }}</td>
            <td class="px-3 py-2">
              {% include "dashboard/_badge.html" with variant=lot.is_active|yesno:"success,default" text=lot.status|default:"—" %}
            </td>
            <td class="px-3 py-2">{{ lot.price|default:"—" }}</td>
            <td class="px-3 py-2 text-base-500 dark:text-base-400">{{ lot.bidding_deadline|default:"—" }}</td>
          </tr>
        {% empty %}
          <tr><td colspan="5" class="px-3 py-4 text-base-500 dark:text-base-400">Ничего не найдено.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if lots_page.total_pages > 1 %}
    <div class="mt-4 flex items-center gap-2 text-sm">
      {% for page_num in lots_page.page_range %}
        <a href="?source={{ source|urlencode }}&page={{ page_num }}"
           class="px-2.5 py-1 rounded-default {% if page_num == lots_page.page %}bg-primary-600 text-white{% else %}border border-base-200 text-important dark:border-base-700{% endif %}">
          {{ page_num }}
        </a>
      {% endfor %}
    </div>
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Add the `lot_detail.html` template**

Create `src/control/templates/dashboard/lot_detail.html`:

```html
{% extends "dashboard/base.html" %}

{% block content %}
  <p class="mb-2">
    <a href="{% url 'dashboard:lots_list' %}" class="text-sm text-base-500 dark:text-base-400 hover:underline">&larr; Назад к списку лотов</a>
  </p>
  <h1 class="text-lg font-semibold text-important mb-4">{{ lot.source }} — лот {{ lot.lot_num|default:"—" }}</h1>

  <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 mb-6">
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Источник</dt><dd class="text-important">{{ lot.source }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">ID лота</dt><dd class="text-important">{{ lot.lot_id }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Номер лота</dt><dd class="text-important">{{ lot.lot_num|default:"—" }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Номер торгов</dt><dd class="text-important">{{ lot.trade_number|default:"—" }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Тип торгов</dt><dd class="text-important">{{ lot.trade_type|default:"—" }}</dd></div>
    <div>
      <dt class="text-xs font-medium text-base-500 dark:text-base-400">Статус</dt>
      <dd>{% include "dashboard/_badge.html" with variant=lot.is_active|yesno:"success,default" text=lot.status|default:"—" %}</dd>
    </div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Цена</dt><dd class="text-important">{{ lot.price|default:"—" }} ({{ lot.price_raw|default:"—" }})</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Должник</dt><dd class="text-important">{{ lot.debtor|default:"—" }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Организатор</dt><dd class="text-important">{{ lot.organizer|default:"—" }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Дедлайн торгов</dt><dd class="text-important">{{ lot.bidding_deadline|default:"—" }} ({{ lot.bidding_date_raw|default:"—" }})</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Дата результата</dt><dd class="text-important">{{ lot.result_date|default:"—" }} ({{ lot.event_date_raw|default:"—" }})</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Впервые замечен</dt><dd class="text-important">{{ lot.first_seen_at|default:"—" }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Последний раз замечен</dt><dd class="text-important">{{ lot.last_seen_at|default:"—" }}</dd></div>
    <div><dt class="text-xs font-medium text-base-500 dark:text-base-400">Задача</dt><dd class="text-important">{{ lot.last_job_id|default:"—" }}</dd></div>
    <div class="sm:col-span-2">
      <dt class="text-xs font-medium text-base-500 dark:text-base-400">Ссылка на лот</dt>
      <dd>{% if lot.lot_url %}<a href="{{ lot.lot_url }}" target="_blank" rel="noopener" class="text-primary-600 hover:underline">{{ lot.lot_url }}</a>{% else %}—{% endif %}</dd>
    </div>
    <div class="sm:col-span-2"><dt class="text-xs font-medium text-base-500 dark:text-base-400">Описание</dt><dd class="text-important whitespace-pre-wrap">{{ lot.description|default:"—" }}</dd></div>
  </dl>

  <div class="mb-4">
    <h2 class="text-sm font-semibold text-important mb-1">Вложения</h2>
    <pre class="text-xs bg-base-100 dark:bg-base-800 border border-base-200 dark:border-base-700 rounded-default p-3 overflow-x-auto">{{ fields_json.attachments }}</pre>
  </div>
  <div class="mb-4">
    <h2 class="text-sm font-semibold text-important mb-1">График цены</h2>
    <pre class="text-xs bg-base-100 dark:bg-base-800 border border-base-200 dark:border-base-700 rounded-default p-3 overflow-x-auto">{{ fields_json.price_schedule }}</pre>
  </div>
  <div class="mb-4">
    <h2 class="text-sm font-semibold text-important mb-1">Прочее</h2>
    <pre class="text-xs bg-base-100 dark:bg-base-800 border border-base-200 dark:border-base-700 rounded-default p-3 overflow-x-auto">{{ fields_json.extra }}</pre>
  </div>
{% endblock %}
```

- [ ] **Step 7: Add the navigation link**

In `src/project/settings.py`, inside `UNFOLD["SIDEBAR"]["navigation"]`, find the "Сбор данных" group
and add a new item after "Задачи":

```python
                    {
                        "title": "Задачи",
                        "icon": "list_alt",
                        "link": reverse_lazy("admin:control_job_changelist"),
                    },
                    {
                        "title": "Лоты",
                        "icon": "inventory_2",
                        "link": reverse_lazy("dashboard:lots_list"),
                    },
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dashboard_lots.py tests/test_dashboard.py -v`
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add src/control/dashboard/views.py src/control/dashboard/urls.py \
        src/control/templates/dashboard/lots.html src/control/templates/dashboard/lot_detail.html \
        src/project/settings.py tests/test_dashboard_lots.py
git commit -m "$(cat <<'EOF'
feat: add read-only lots list and detail pages to the dashboard

EOF
)"
```

---

## Task 3: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass, including every test added in Tasks 1–2.

- [ ] **Step 2: Lint and import contracts**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
```
Expected: no findings. `lint-imports` in particular must stay clean — it is the check that would
catch `control/services/lots.py` accidentally importing `execution`. If `ruff format --check` flags
any file this plan touched, run `uv run ruff format <file>` and re-run the check.

- [ ] **Step 3: Django system check**

Run: `uv run python src/manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 4: Rebuild and restart the Docker web container**

The dashboard runs inside the `web` service (`docker/compose.yaml`); the source is baked into the
image (not bind-mounted), so a code change needs a rebuild:

```bash
docker compose -f docker/compose.yaml build web
docker compose -f docker/compose.yaml up -d web
```

- [ ] **Step 5: Seed at least one lot to see in the browser**

If the `lots` collection in the environment's real Mongo is empty, the page will only show "Ничего
не найдено." — still a valid smoke test of the empty state, but insert one manually first if you
want to see the populated list and detail page:

```bash
docker compose -f docker/compose.yaml exec web python src/manage.py shell
```

Then, in the shell:

```python
from control.services.mongo import get_lots_collection
from django.utils import timezone

get_lots_collection().insert_one({
    "source": "smoke-test.example",
    "lot_id": "smoke-1",
    "lot_num": "1",
    "status": "Идут торги",
    "is_active": True,
    "price": 100.0,
    "bidding_deadline": timezone.now(),
    "debtor": "Смоук-тест",
    "attachments": [{"name": "test.pdf"}],
    "price_schedule": [],
    "extra": {},
    "last_seen_at": timezone.now(),
})
```

- [ ] **Step 6: Live smoke-test in a browser**

Log in at `http://localhost:8000/admin/login/` (seeded `admin`/`admin`), then open
`http://localhost:8000/dashboard/lots/` and confirm, in order:

1. "Лоты" appears in the sidebar under "Сбор данных" and clicking it lands on this page.
2. The seeded lot (or existing real lots, if any) appears in the table with source, lot number,
   status badge, price, and bidding deadline.
3. The "Источник" dropdown lists the distinct sources present; selecting one and clicking
   "Применить" narrows the table to that source, and "Сбросить" clears it back to all.
4. Clicking a row's source link opens `/dashboard/lots/<id>/` and shows every field, including
   "Вложения" as pretty-printed JSON matching what was seeded.
5. The "Ссылка на лот" link (if `lot_url` is set) opens in a new tab.
6. "← Назад к списку лотов" returns to the filtered list.

If any step fails, fix the underlying template/view/service code (not by disabling the check) before
proceeding.

- [ ] **Step 7: Final commit (only if Step 6 required fixes)**

If Step 6 required any code changes, commit them now with a message describing what the smoke test
caught. If Step 6 passed with no changes needed, skip this step — there is nothing to commit.
