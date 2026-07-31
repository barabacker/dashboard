# Dashboard Unfold Restyle + Grouping/Search/Bulk-Run/Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle `/dashboard/` to match the Unfold-themed admin instead of its own hand-rolled CSS, and add family grouping, search/filter, bulk "run selected", and a per-row "stop" action.

**Architecture:** `src/control/dashboard/views.py` stays plain function views; `dashboard/base.html` now extends `admin/base_site.html` (the same base every other custom page in this codebase — e.g. `admin/control/job/stop_all_confirmation.html` — already extends) instead of hand-rolled HTML, picking up Unfold's sidebar/header/dark-mode/messages for free via `admin.site.each_context(request)`. The configs table becomes one `<form>` per collector family inside `<details>`, with per-row buttons targeting different endpoints via the HTML `formaction` attribute (valid, no nested forms, no JS framework). A new `run_selected` view handles bulk enqueue; the existing `cancel_job` view is reused, unchanged, as the target of the new per-row "Остановить" button.

**Tech Stack:** Django, `django-unfold` (Tailwind-based admin theme, already installed), HTMX (already used for the jobs panel's auto-refresh — untouched), no new dependencies.

**Reference:** Design doc at [`docs/superpowers/specs/2026-08-01-dashboard-unfold-redesign-design.md`](../specs/2026-08-01-dashboard-unfold-redesign-design.md).

**One deviation from that spec, decided during planning:** the spec's decision #2 says `dashboard/base.html` extends `unfold/layouts/base.html`. This plan instead extends `admin/base_site.html`, because that is the base template this exact codebase already uses for its other hand-rolled admin-adjacent pages (`src/control/templates/admin/control/job/stop_all_confirmation.html`, `purge_all_confirmation.html`), proven to work with nothing more than `{**admin_site.each_context(request), "title": ...}` in context. Using the same chain avoids introducing a second, parallel way of hooking into Unfold's chrome. The visible result (sidebar, header, dark mode, Unfold styling) is identical either way.

---

## Task 1: Foundation — status badge variant + Unfold-themed base template

**Files:**
- Create: `src/control/templatetags/__init__.py`
- Create: `src/control/templatetags/dashboard_extras.py`
- Create: `src/control/templates/dashboard/_badge.html`
- Modify: `src/control/dashboard/views.py` (add `STATUS_VARIANT`, update `_status_counts`)
- Modify: `src/control/templates/dashboard/base.html`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dashboard.py` (near the top, after existing imports):

```python
def test_index_renders_the_unfold_admin_chrome(client, user, config):
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    # "Источники" is a sidebar nav label (see UNFOLD["SIDEBAR"] in settings.py) that never
    # otherwise appears in the dashboard's own body content — its presence means
    # `admin.site.each_context` reached the template and Unfold's sidebar rendered.
    assert "Источники".encode() in response.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard.py::test_index_renders_the_unfold_admin_chrome -v`
Expected: FAIL — "Источники" not in response.content (the current hand-rolled `base.html` has no Unfold sidebar).

- [ ] **Step 3: Create the templatetags package**

`src/control/templatetags/__init__.py` (empty file).

`src/control/templatetags/dashboard_extras.py`:

```python
"""Template-side helper for turning a raw `JobStatus` value into an Unfold badge variant.

`STATUS_VARIANT` lives in `control.dashboard.views` because `_status_counts` (a plain Python
function) needs the same mapping — this filter is the template-side access to that one source of
truth, not a second copy of it.
"""

from __future__ import annotations

from django import template

from control.dashboard.views import STATUS_VARIANT

register = template.Library()


@register.filter
def dashboard_status_variant(status: str) -> str:
    return STATUS_VARIANT.get(status, "default")
```

- [ ] **Step 4: Add the badge partial**

`src/control/templates/dashboard/_badge.html` — a trimmed copy of Unfold's own
`unfold/components/label.html` color logic (same five variants, no icon/href support, which the
dashboard never needs):

```html
<span class="inline-block font-semibold rounded-default text-[11px] uppercase whitespace-nowrap h-5 leading-5 px-1.5{% if variant == "info" %} bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400{% elif variant == "danger" %} bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400{% elif variant == "warning" %} bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400{% elif variant == "success" %} bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400{% else %} bg-base-500/8 text-base-700 dark:bg-base-500/20 dark:text-base-200{% endif %}">{{ text }}</span>
```

- [ ] **Step 5: Add `STATUS_VARIANT` and use it in `_status_counts`**

In `src/control/dashboard/views.py`, add right after the `_RECENT_JOBS = 25` line:

```python
#: Shared status -> Unfold badge-pill variant. `dashboard_extras.dashboard_status_variant`
#: (a template filter) reads this same dict — one source of truth for both call sites.
STATUS_VARIANT: dict[str, str] = {
    JobStatus.PENDING: "default",
    JobStatus.RUNNING: "info",
    JobStatus.SUCCEEDED: "success",
    JobStatus.FAILED: "danger",
    JobStatus.CANCELLED: "warning",
}
```

Then change `_status_counts` to also carry `variant`:

```python
def _status_counts() -> list[dict[str, object]]:
    """One tally per status, carrying the raw value, its label, and its badge variant.

    The raw value drives the CSS class, the label is what a human reads — the template must never
    print the stored value.
    """
    rows = Job.objects.values("status").annotate(n=Count("pk"))
    counts = dict.fromkeys(JobStatus.values, 0)
    for row in rows:
        counts[row["status"]] = row["n"]
    return [
        {
            "value": status,
            "label": JobStatus(status).label,
            "variant": STATUS_VARIANT.get(status, "default"),
            "count": counts[status],
        }
        for status in JobStatus.values
    ]
```

- [ ] **Step 6: Rewrite `base.html`**

Replace the entire content of `src/control/templates/dashboard/base.html` with:

```html
{% extends "admin/base_site.html" %}

{% block content %}{% endblock %}
```

(Same block name and shape as the file already had — only the `{% extends %}` target changes, from
the old hand-rolled `dashboard/base.html` chrome to Unfold's own `admin/base_site.html`.)

- [ ] **Step 7: Pass `each_context` from the `index` view**

In `src/control/dashboard/views.py`, add `admin` to the imports:

```python
from django.contrib import admin, messages
```

In the `index` view, change the `render(...)` call's context dict to start with
`**admin.site.each_context(request)` and add a `"title"` key:

```python
    return render(
        request,
        "dashboard/index.html",
        {
            **admin.site.each_context(request),
            "title": "Панель сбора данных",
            "configs": configs,
            "active_config_ids": active_config_ids,
            "jobs": _recent_jobs(),
            "counts": _status_counts(),
        },
    )
```

(This is an intermediate state — `configs`/`active_config_ids` still exist as today; Task 2
replaces them with `grouped_configs`. Keeping this step isolated means the chrome/badge change is
independently testable before the grouping rewrite.)

- [ ] **Step 8: Run the test to verify it passes**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: All pass, including the new `test_index_renders_the_unfold_admin_chrome`. (The existing
`index.html`/`_jobs.html` still reference the old context keys and old CSS classes at this point —
that's fine, they still render without error since `configs`/`active_config_ids` are still passed;
visual re-theming of those two templates happens in Tasks 2–5.)

- [ ] **Step 9: Commit**

```bash
git add src/control/templatetags src/control/templates/dashboard/_badge.html \
        src/control/templates/dashboard/base.html src/control/dashboard/views.py \
        tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat: extend dashboard base template from Unfold's admin chrome

EOF
)"
```

---

## Task 2: Family grouping + search/filter

**Files:**
- Modify: `src/control/dashboard/views.py`
- Modify: `src/control/templates/dashboard/index.html`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard.py`:

```python
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


def test_a_family_with_no_matching_config_does_not_render_its_heading(client, user, make_config):
    make_config(name="Alpha", collector_key="example_api")
    make_config(
        name="Beta", collector_key="tender_fogsoft", parameters={"domain": "https://example.test"}
    )
    client.force_login(user)
    response = client.get(reverse("dashboard:index"), {"q": "Alpha"})
    assert "Пример: HTTP API".encode() in response.content
    assert "Торги: iTender (Fogsoft)".encode() not in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dashboard.py -k "groups_configs or narrows_the_list or shows_only_disabled or does_not_render_its_heading" -v`
Expected: FAIL — `index.html` doesn't render any collector label text yet, and the view has no `q`/`state` handling.

- [ ] **Step 3: Add grouping + filtering to the view**

In `src/control/dashboard/views.py`, add these imports:

```python
from collections import OrderedDict
...
from collectors import schemas
```

Add these two helpers above `index`:

```python
def _collector_label(key: str) -> str:
    """`Collector.display_name` if the code knows this key, the raw key otherwise.

    Reads `collectors.schemas` (already an allowed import here — see `control/services/enqueue.py`)
    rather than the `Collector` projection table, so a family still gets a real label even before
    `sync_collectors` has ever run.
    """
    try:
        return schemas.get_collector(key).display_name
    except schemas.UnknownCollector:
        return key


def _filtered_configs(request: HttpRequest):
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state", "all")
    if state not in ("all", "enabled", "disabled"):
        state = "all"

    qs = Config.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    if state == "enabled":
        qs = qs.filter(enabled=True)
    elif state == "disabled":
        qs = qs.filter(enabled=False)
    return qs, q, state
```

- [ ] **Step 4: Rewrite the `index` view to group and pass filter state**

Replace the whole `index` function body with:

```python
@staff_member_required
def index(request: HttpRequest) -> HttpResponse:
    configs_qs, q, state = _filtered_configs(request)

    latest_job = Job.objects.filter(config_id=OuterRef("pk")).order_by("-created_at")
    configs = list(
        configs_qs.annotate(
            latest_job_status=Subquery(latest_job.values("status")[:1]),
            latest_job_id=Subquery(latest_job.values("id")[:1]),
            latest_job_at=Subquery(latest_job.values("created_at")[:1]),
        ).order_by("name")
    )

    groups: "OrderedDict[str, dict[str, object]]" = OrderedDict()
    for c in configs:
        c.latest_job_label = JobStatus(c.latest_job_status).label if c.latest_job_status else ""
        group = groups.setdefault(
            c.collector_key, {"label": _collector_label(c.collector_key), "configs": []}
        )
        group["configs"].append(c)
    grouped_configs = [groups[key] for key in sorted(groups)]

    return render(
        request,
        "dashboard/index.html",
        {
            **admin.site.each_context(request),
            "title": "Панель сбора данных",
            "grouped_configs": grouped_configs,
            "jobs": _recent_jobs(),
            "counts": _status_counts(),
            "q": q,
            "state": state,
        },
    )
```

This drops the old `active_config_ids` query and the `latest_job_id`-based active check — Task 3
replaces it with a proper per-config `active_job_id` annotation.

- [ ] **Step 5: Rewrite `index.html`**

Replace the whole content of `src/control/templates/dashboard/index.html`:

```html
{% extends "dashboard/base.html" %}
{% load dashboard_extras %}

{% block content %}
  <h1 class="text-lg font-semibold text-important mb-4">Панель сбора данных</h1>

  <form method="get" class="mb-4 flex flex-wrap items-end gap-3">
    <div>
      <label class="block text-xs font-medium text-base-500 dark:text-base-400 mb-1" for="q">Название</label>
      <input type="text" id="q" name="q" value="{{ q }}" placeholder="Поиск по названию"
             class="border border-base-200 bg-white font-medium placeholder-base-400 rounded-default shadow-xs text-sm focus:outline-2 focus:-outline-offset-2 focus:outline-primary-600 dark:bg-base-900 dark:border-base-700 dark:text-font-default-dark px-3 py-2">
    </div>
    <div>
      <label class="block text-xs font-medium text-base-500 dark:text-base-400 mb-1" for="state">Состояние</label>
      <select id="state" name="state"
              class="border border-base-200 bg-white font-medium rounded-default shadow-xs text-sm dark:bg-base-900 dark:border-base-700 dark:text-font-default-dark px-3 py-2 pr-8">
        <option value="all" {% if state == "all" %}selected{% endif %}>Все</option>
        <option value="enabled" {% if state == "enabled" %}selected{% endif %}>Включённые</option>
        <option value="disabled" {% if state == "disabled" %}selected{% endif %}>Отключённые</option>
      </select>
    </div>
    <button type="submit" class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-3 py-2 border border-base-200 bg-white shadow-xs text-important dark:border-base-700 dark:bg-transparent hover:bg-base-100/80 dark:hover:bg-base-800/80">
      Применить
    </button>
    {% if q or state != "all" %}
      <a href="{% url 'dashboard:index' %}" class="text-sm text-base-500 dark:text-base-400 underline">Сбросить</a>
    {% endif %}
  </form>

  {% for group in grouped_configs %}
    <details open class="mb-4 rounded-default border border-base-200 shadow-xs dark:border-base-800 bg-white dark:bg-base-900 overflow-hidden">
      <summary class="cursor-pointer select-none px-3 py-2 font-semibold text-important border-b border-base-200 dark:border-base-800">
        {{ group.label }}
        <span class="text-base-400 dark:text-base-500 font-normal">({{ group.configs|length }})</span>
      </summary>
      <div class="overflow-x-auto">
        <table class="w-full border-spacing-none border-separate whitespace-nowrap">
          <thead>
            <tr>
              <th class="align-middle font-semibold py-2 px-3 text-left text-important">Название</th>
              <th class="align-middle font-semibold py-2 px-3 text-left text-important">Состояние</th>
              <th class="align-middle font-semibold py-2 px-3 text-left text-important">Последний запуск</th>
              <th class="align-middle font-semibold py-2 px-3 text-left text-important">Когда</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {% for config in group.configs %}
              <tr class="border-t border-base-200 dark:border-base-800">
                <td class="px-3 py-2">
                  <a href="{% url 'admin:control_config_change' config.pk %}" class="text-important hover:underline">{{ config.name }}</a>
                </td>
                <td class="px-3 py-2">
                  {% if config.enabled %}
                    <span class="text-important">включена</span>
                  {% else %}
                    <span class="text-base-400 dark:text-base-500">отключена</span>
                  {% endif %}
                </td>
                <td class="px-3 py-2">
                  {% if config.latest_job_status %}
                    {% include "dashboard/_badge.html" with variant=config.latest_job_status|dashboard_status_variant text=config.latest_job_label %}
                    <a class="ml-1 text-base-400 dark:text-base-500 hover:underline" href="{% url 'admin:control_job_change' config.latest_job_id %}">#{{ config.latest_job_id }}</a>
                  {% else %}
                    <span class="text-base-400 dark:text-base-500">не запускалась</span>
                  {% endif %}
                </td>
                <td class="px-3 py-2 text-base-500 dark:text-base-400">{{ config.latest_job_at|default:"—" }}</td>
                <td class="px-3 py-2 text-right">
                  <form method="post" action="{% url 'dashboard:run_now' config.pk %}">
                    {% csrf_token %}
                    <button type="submit" {% if not config.enabled %}disabled{% endif %}
                            class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap {% if not config.enabled %}cursor-not-allowed opacity-50{% else %}cursor-pointer{% endif %} px-2.5 py-1.5 text-sm border border-base-200 bg-white shadow-xs text-important dark:border-base-700 dark:bg-transparent hover:bg-base-100/80 dark:hover:bg-base-800/80">
                      Запустить
                    </button>
                  </form>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </details>
  {% empty %}
    <p class="text-base-500 dark:text-base-400">Ничего не найдено.</p>
  {% endfor %}

  {% include "dashboard/_jobs.html" %}
{% endblock %}
```

(The per-row action cell still uses one `<form>` per row here — Task 3/4 replace this with the
single wrapping bulk-run `<form>` plus `formaction` buttons. Keeping it as one-form-per-row for now
means this task's tests can pass without pulling in Task 3/4's changes.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/control/dashboard/views.py src/control/templates/dashboard/index.html tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat: group dashboard configs by collector family, add name/state filter

EOF
)"
```

---

## Task 3: Stop button on the config row

**Files:**
- Modify: `src/control/dashboard/views.py`
- Modify: `src/control/templates/dashboard/index.html`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dashboard.py -k "shows_a_stop_button or shows_no_stop_button" -v`
Expected: FAIL — nothing in the view or template today renders a Stop button.

- [ ] **Step 3: Add the `active_job_id` / `active_job_cancel_requested` annotations**

In `src/control/dashboard/views.py`, inside `index`, add an `active_job` subquery next to
`latest_job` and two more annotations:

```python
    latest_job = Job.objects.filter(config_id=OuterRef("pk")).order_by("-created_at")
    active_job = Job.objects.filter(
        config_id=OuterRef("pk"), status__in=JobStatus.active()
    ).order_by("-created_at")
    configs = list(
        configs_qs.annotate(
            latest_job_status=Subquery(latest_job.values("status")[:1]),
            latest_job_id=Subquery(latest_job.values("id")[:1]),
            latest_job_at=Subquery(latest_job.values("created_at")[:1]),
            active_job_id=Subquery(active_job.values("id")[:1]),
            active_job_cancel_requested=Subquery(active_job.values("cancel_requested")[:1]),
        ).order_by("name")
    )
```

- [ ] **Step 4: Replace the action cell in `index.html`**

In `src/control/templates/dashboard/index.html`, replace the action `<td>` (the one containing
the "Запустить" form) with:

```html
                <td class="px-3 py-2 text-right">
                  {% if config.active_job_id %}
                    {% if config.active_job_cancel_requested %}
                      <span class="text-base-400 dark:text-base-500 text-sm">останавливается…</span>
                    {% else %}
                      <form method="post" action="{% url 'dashboard:cancel_job' config.active_job_id %}">
                        {% csrf_token %}
                        <button type="submit" class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-2.5 py-1.5 text-sm border border-red-600 bg-red-600 text-white hover:bg-red-600/80">
                          Остановить
                        </button>
                      </form>
                    {% endif %}
                  {% else %}
                    <form method="post" action="{% url 'dashboard:run_now' config.pk %}">
                      {% csrf_token %}
                      <button type="submit" {% if not config.enabled %}disabled{% endif %}
                              class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap {% if not config.enabled %}cursor-not-allowed opacity-50{% else %}cursor-pointer{% endif %} px-2.5 py-1.5 text-sm border border-base-200 bg-white shadow-xs text-important dark:border-base-700 dark:bg-transparent hover:bg-base-100/80 dark:hover:bg-base-800/80">
                        Запустить
                      </button>
                    </form>
                  {% endif %}
                </td>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/control/dashboard/views.py src/control/templates/dashboard/index.html tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat: show a Stop button on a config row with an active job

EOF
)"
```

---

## Task 4: Bulk "Запустить выбранные"

**Files:**
- Modify: `src/control/dashboard/views.py`
- Modify: `src/control/dashboard/urls.py`
- Modify: `src/control/templates/dashboard/index.html`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dashboard.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dashboard.py -k run_selected -v`
Expected: FAIL — `reverse("dashboard:run_selected")` raises `NoReverseMatch` (the URL doesn't exist yet).

- [ ] **Step 3: Add the `run_selected` view**

In `src/control/dashboard/views.py`, add this view after `run_now`:

```python
@staff_member_required
@require_POST
def run_selected(request: HttpRequest) -> HttpResponse:
    """Bulk "Запустить выбранные": one `enqueue()` per checked config, one summary message."""
    ids = []
    for raw in request.POST.getlist("config_id"):
        try:
            ids.append(int(raw))
        except ValueError:
            continue

    enqueued, refused = 0, 0
    for config in Config.objects.filter(pk__in=ids):
        try:
            enqueue(config, origin=JobOrigin.MANUAL, requested_by=request.user)
        except EnqueueRefused:
            refused += 1
        else:
            enqueued += 1

    if not ids:
        messages.warning(request, "Ничего не выбрано.")
    else:
        if enqueued:
            messages.success(request, f"Поставлено в очередь: {enqueued}.")
        if refused:
            messages.warning(request, f"Отказано: {refused} — проверьте состояние конфигураций.")

    return redirect("dashboard:index")
```

- [ ] **Step 4: Add the URL**

In `src/control/dashboard/urls.py`, add a line inside `urlpatterns`, before the `run_now` line
(routing order doesn't matter here, but this keeps the "configs" paths together):

```python
    path("configs/run-selected/", views.run_selected, name="run_selected"),
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
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_dashboard.py -k run_selected -v`
Expected: PASS.

- [ ] **Step 6: Wire the checkboxes and bulk button into `index.html`**

This step turns the per-row `<form>`s from Task 2/3 into one wrapping `<form>` with per-row
`formaction` buttons, plus checkboxes and a "select all" control. Replace the whole
`{% block content %}...{% endblock %}` body in `src/control/templates/dashboard/index.html`
with:

```html
{% extends "dashboard/base.html" %}
{% load dashboard_extras %}

{% block content %}
  <h1 class="text-lg font-semibold text-important mb-4">Панель сбора данных</h1>

  <form method="get" class="mb-4 flex flex-wrap items-end gap-3">
    <div>
      <label class="block text-xs font-medium text-base-500 dark:text-base-400 mb-1" for="q">Название</label>
      <input type="text" id="q" name="q" value="{{ q }}" placeholder="Поиск по названию"
             class="border border-base-200 bg-white font-medium placeholder-base-400 rounded-default shadow-xs text-sm focus:outline-2 focus:-outline-offset-2 focus:outline-primary-600 dark:bg-base-900 dark:border-base-700 dark:text-font-default-dark px-3 py-2">
    </div>
    <div>
      <label class="block text-xs font-medium text-base-500 dark:text-base-400 mb-1" for="state">Состояние</label>
      <select id="state" name="state"
              class="border border-base-200 bg-white font-medium rounded-default shadow-xs text-sm dark:bg-base-900 dark:border-base-700 dark:text-font-default-dark px-3 py-2 pr-8">
        <option value="all" {% if state == "all" %}selected{% endif %}>Все</option>
        <option value="enabled" {% if state == "enabled" %}selected{% endif %}>Включённые</option>
        <option value="disabled" {% if state == "disabled" %}selected{% endif %}>Отключённые</option>
      </select>
    </div>
    <button type="submit" class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-3 py-2 border border-base-200 bg-white shadow-xs text-important dark:border-base-700 dark:bg-transparent hover:bg-base-100/80 dark:hover:bg-base-800/80">
      Применить
    </button>
    {% if q or state != "all" %}
      <a href="{% url 'dashboard:index' %}" class="text-sm text-base-500 dark:text-base-400 underline">Сбросить</a>
    {% endif %}
  </form>

  <form method="post" action="{% url 'dashboard:run_selected' %}">
    {% csrf_token %}
    <input type="hidden" name="next_qs" value="{{ request.GET.urlencode }}">

    <div class="mb-3 flex items-center gap-3">
      <label class="inline-flex items-center gap-1.5 text-sm text-important">
        <input type="checkbox" onclick="dashboardToggleAll(this)"> Выбрать все
      </label>
      <button type="submit" class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-3 py-2 border border-base-200 bg-primary-600 border-transparent text-white hover:bg-primary-600/80">
        Запустить выбранные
      </button>
    </div>

    {% for group in grouped_configs %}
      <details open class="mb-4 rounded-default border border-base-200 shadow-xs dark:border-base-800 bg-white dark:bg-base-900 overflow-hidden">
        <summary class="cursor-pointer select-none px-3 py-2 font-semibold text-important border-b border-base-200 dark:border-base-800">
          {{ group.label }}
          <span class="text-base-400 dark:text-base-500 font-normal">({{ group.configs|length }})</span>
        </summary>
        <div class="overflow-x-auto">
          <table class="w-full border-spacing-none border-separate whitespace-nowrap">
            <thead>
              <tr>
                <th class="w-px px-3 py-2"></th>
                <th class="align-middle font-semibold py-2 px-3 text-left text-important">Название</th>
                <th class="align-middle font-semibold py-2 px-3 text-left text-important">Состояние</th>
                <th class="align-middle font-semibold py-2 px-3 text-left text-important">Последний запуск</th>
                <th class="align-middle font-semibold py-2 px-3 text-left text-important">Когда</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {% for config in group.configs %}
                <tr class="border-t border-base-200 dark:border-base-800">
                  <td class="px-3 py-2">
                    <input type="checkbox" name="config_id" value="{{ config.pk }}"
                           {% if not config.enabled or config.active_job_id %}disabled{% endif %}>
                  </td>
                  <td class="px-3 py-2">
                    <a href="{% url 'admin:control_config_change' config.pk %}" class="text-important hover:underline">{{ config.name }}</a>
                    {% if config.active_job_id %}
                      {% include "dashboard/_badge.html" with variant="info" text="в работе" %}
                    {% endif %}
                  </td>
                  <td class="px-3 py-2">
                    {% if config.enabled %}
                      <span class="text-important">включена</span>
                    {% else %}
                      <span class="text-base-400 dark:text-base-500">отключена</span>
                    {% endif %}
                  </td>
                  <td class="px-3 py-2">
                    {% if config.latest_job_status %}
                      {% include "dashboard/_badge.html" with variant=config.latest_job_status|dashboard_status_variant text=config.latest_job_label %}
                      <a class="ml-1 text-base-400 dark:text-base-500 hover:underline" href="{% url 'admin:control_job_change' config.latest_job_id %}">#{{ config.latest_job_id }}</a>
                    {% else %}
                      <span class="text-base-400 dark:text-base-500">не запускалась</span>
                    {% endif %}
                  </td>
                  <td class="px-3 py-2 text-base-500 dark:text-base-400">{{ config.latest_job_at|default:"—" }}</td>
                  <td class="px-3 py-2 text-right">
                    {% if config.active_job_id %}
                      {% if config.active_job_cancel_requested %}
                        <span class="text-base-400 dark:text-base-500 text-sm">останавливается…</span>
                      {% else %}
                        <button type="submit" formaction="{% url 'dashboard:cancel_job' config.active_job_id %}"
                                class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-2.5 py-1.5 text-sm border border-red-600 bg-red-600 text-white hover:bg-red-600/80">
                          Остановить
                        </button>
                      {% endif %}
                    {% else %}
                      <button type="submit" formaction="{% url 'dashboard:run_now' config.pk %}"
                              {% if not config.enabled %}disabled{% endif %}
                              class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap {% if not config.enabled %}cursor-not-allowed opacity-50{% else %}cursor-pointer{% endif %} px-2.5 py-1.5 text-sm border border-base-200 bg-white shadow-xs text-important dark:border-base-700 dark:bg-transparent hover:bg-base-100/80 dark:hover:bg-base-800/80">
                        Запустить
                      </button>
                    {% endif %}
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </details>
    {% empty %}
      <p class="text-base-500 dark:text-base-400">Ничего не найдено.</p>
    {% endfor %}
  </form>

  {% include "dashboard/_jobs.html" %}

  <script>
    function dashboardToggleAll(master) {
      master.form.querySelectorAll('input[name="config_id"]:not(:disabled)').forEach(function (cb) {
        cb.checked = master.checked;
      });
    }
  </script>
{% endblock %}
```

Note what changed structurally: the per-row "Запустить"/"Остановить" buttons are now
`type="submit" formaction="..."` inside the *one* `run_selected`-targeted form, instead of each
being its own nested `<form>` (which Task 2/3 used temporarily and which HTML does not allow
nested inside the new bulk-select form). `formaction` overrides the destination URL for that one
button's submit while reusing the same form's method (POST) and CSRF token.

- [ ] **Step 7: Preserve the current filter across every action's redirect**

Right now `run_now`, `run_selected`, and `cancel_job` always redirect to a bare
`dashboard:index`, dropping any `?q=`/`?state=` the user had applied. Add one shared helper and use
it in all three views. In `src/control/dashboard/views.py`, add the import:

```python
from django.urls import reverse
```

Add the helper (near the other module-level helpers):

```python
def _redirect_preserving_filter(request: HttpRequest) -> HttpResponse:
    url = reverse("dashboard:index")
    next_qs = request.POST.get("next_qs", "")
    if next_qs:
        url = f"{url}?{next_qs}"
    return redirect(url)
```

Then replace every `return redirect("dashboard:index")` in `run_now`, `run_selected`, and
`cancel_job` with `return _redirect_preserving_filter(request)`.

- [ ] **Step 8: Run the full dashboard test suite**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: All pass (existing + new).

- [ ] **Step 9: Commit**

```bash
git add src/control/dashboard/views.py src/control/dashboard/urls.py \
        src/control/templates/dashboard/index.html tests/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat: bulk "run selected" for dashboard configs, preserve filter across redirects

EOF
)"
```

---

## Task 5: Re-theme the jobs panel

**Files:**
- Modify: `src/control/templates/dashboard/_jobs.html`

No behavior changes here — `hx-get`/`hx-trigger`, the tally, and the cancel form all keep working
exactly as before; only the markup/classes change to match the rest of the page. The existing
`test_jobs_panel_renders_on_its_own` test (asserting `b"jobs-panel"` is in the response) already
covers this — no new test needed.

- [ ] **Step 1: Rewrite `_jobs.html`**

Replace the whole file with:

```html
{% comment %}
Refreshed in place by HTMX every few seconds. Keep the id and the hx-* attributes on the root
element — they are what makes the swap re-arm itself.
{% endcomment %}
{% load dashboard_extras %}
<div id="jobs-panel" hx-get="{% url 'dashboard:jobs_panel' %}" hx-trigger="every 5s" hx-swap="outerHTML">
  <h2 class="text-sm font-semibold uppercase tracking-wide text-base-500 dark:text-base-400 mt-8 mb-2">
    Последние задачи
  </h2>

  <ul class="flex flex-wrap gap-4 mb-3 text-sm">
    {% for tally in counts %}
      <li class="flex items-center gap-1.5">
        {% include "dashboard/_badge.html" with variant=tally.variant text=tally.label %}
        <span class="text-base-500 dark:text-base-400">{{ tally.count }}</span>
      </li>
    {% endfor %}
  </ul>

  <div class="rounded-default border border-base-200 shadow-xs dark:border-base-800 bg-white dark:bg-base-900 overflow-x-auto">
    <table class="w-full border-spacing-none border-separate whitespace-nowrap">
      <thead>
        <tr>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">#</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Статус</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Сборщик</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Источник</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Попытка</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Создана</th>
          <th class="align-middle font-semibold py-2 px-3 text-left text-important">Длительность</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for job in jobs %}
          <tr class="border-t border-base-200 dark:border-base-800">
            <td class="px-3 py-2">
              <a class="text-important hover:underline" href="{% url 'admin:control_job_change' job.pk %}">{{ job.pk }}</a>
            </td>
            <td class="px-3 py-2">
              {% include "dashboard/_badge.html" with variant=job.status|dashboard_status_variant text=job.get_status_display %}
              {% if job.cancel_requested and job.status == 'running' %}
                <span class="text-base-400 dark:text-base-500 text-sm">· отменяется</span>
              {% endif %}
            </td>
            <td class="px-3 py-2 font-mono text-sm text-base-500 dark:text-base-400">{{ job.collector_key }}</td>
            <td class="px-3 py-2 text-base-500 dark:text-base-400">{{ job.get_origin_display }}</td>
            <td class="px-3 py-2 text-base-500 dark:text-base-400">{{ job.attempt_no }}</td>
            <td class="px-3 py-2 text-base-500 dark:text-base-400">{{ job.created_at }}</td>
            <td class="px-3 py-2 text-base-500 dark:text-base-400">
              {% if job.duration_seconds %}{{ job.duration_seconds|floatformat:1 }} с{% else %}—{% endif %}
            </td>
            <td class="px-3 py-2 text-right">
              {% if job.is_active and not job.cancel_requested %}
                <form method="post" action="{% url 'dashboard:cancel_job' job.pk %}">
                  {% csrf_token %}
                  <button type="submit" class="font-medium inline-flex items-center gap-1 rounded-default justify-center whitespace-nowrap cursor-pointer px-2.5 py-1.5 text-sm border border-red-600 bg-red-600 text-white hover:bg-red-600/80">
                    Отменить
                  </button>
                </form>
              {% endif %}
            </td>
          </tr>
        {% empty %}
          <tr><td colspan="8" class="px-3 py-6 text-center text-base-400 dark:text-base-500">Ещё ничего не запускалось.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
```

- [ ] **Step 2: Run the dashboard test suite**

Run: `uv run pytest tests/test_dashboard.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add src/control/templates/dashboard/_jobs.html
git commit -m "$(cat <<'EOF'
style: re-theme the dashboard jobs panel to match the rest of the page

EOF
)"
```

---

## Task 6: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass (322+ previously, plus the ~10 added across Tasks 1–4).

- [ ] **Step 2: Lint and import contracts**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
```
Expected: no findings. If `ruff format --check` flags any of the files this plan touched, run
`uv run ruff format <file>` and re-run the check.

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

- [ ] **Step 5: Live smoke-test in a browser**

Log in at `http://localhost:8000/admin/login/` (seeded `admin`/`admin`), then open
`http://localhost:8000/dashboard/` and confirm, in order:

1. The page shows the same sidebar/header as `/admin/` (no leftover custom CSS look).
2. Configs are grouped under collapsible family headings with a count each.
3. Typing into the search box and clicking "Применить" narrows the list; "Сбросить" clears it.
4. Selecting the "Состояние" dropdown to "Отключённые" shows only disabled configs.
5. Checking a couple of rows and clicking "Запустить выбранные" enqueues jobs for both (check the
   jobs panel below, or `/admin/control/job/`) and shows a summary message.
6. On a config with an active job, "Остановить" is shown instead of "Запустить"; clicking it either
   removes the job outright (if it was still pending) or replaces the button with
   "останавливается…" (if a worker had already claimed it).
7. The jobs panel below still auto-refreshes every 5 seconds and its own "Отменить" buttons still
   work.

If any step fails, fix the underlying template/view code (not by disabling the check) before
proceeding — this is the point in the plan where template-rendering issues that unit tests can't
catch (e.g. a stray Unfold context requirement) would surface.

- [ ] **Step 6: Final commit (only if Step 5 required fixes)**

If Step 5 required any code changes, commit them now with a message describing what the smoke test
caught. If Step 5 passed with no changes needed, skip this step — there is nothing to commit.
