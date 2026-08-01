"""A deliberately small dashboard.

Django Admin is the primary UI; this exists for the two things a list page is bad at: seeing at a
glance what ran, and starting or stopping a run without leaving the page.

Actions are plain form POSTs that redirect. HTMX only adds the auto-refreshing job panel — if the
script fails to load, the page still works, it just stops refreshing itself.
"""

from __future__ import annotations

import json

from collections import OrderedDict

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, OuterRef, Subquery
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from collectors import schemas
from control.models import Config, Job, JobOrigin, JobStatus
from control.services import EnqueueRefused, enqueue, request_cancel
from control.services.lots import get_lot, list_lots

_RECENT_JOBS = 25

#: Shared status -> Unfold badge-pill variant. `dashboard_extras.dashboard_status_variant`
#: (a template filter) reads this same dict — one source of truth for both call sites.
STATUS_VARIANT: dict[str, str] = {
    JobStatus.PENDING: "default",
    JobStatus.RUNNING: "info",
    JobStatus.SUCCEEDED: "success",
    JobStatus.FAILED: "danger",
    JobStatus.CANCELLED: "warning",
}


def _recent_jobs():
    return Job.objects.order_by("-created_at")[:_RECENT_JOBS]


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


def _redirect_preserving_filter(request: HttpRequest) -> HttpResponse:
    url = reverse("dashboard:index")
    next_qs = request.POST.get("next_qs", "")
    if next_qs:
        url = f"{url}?{next_qs}"
    return redirect(url)


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


@staff_member_required
def index(request: HttpRequest) -> HttpResponse:
    configs_qs, q, state = _filtered_configs(request)

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

    groups: OrderedDict[str, dict[str, object]] = OrderedDict()
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


@staff_member_required
def jobs_panel(request: HttpRequest) -> HttpResponse:
    """HTMX partial: the job list refreshes itself without reloading the page."""
    return render(
        request,
        "dashboard/_jobs.html",
        {"jobs": _recent_jobs(), "counts": _status_counts()},
    )


@staff_member_required
@require_POST
def run_now(request: HttpRequest, pk: int) -> HttpResponse:
    config = get_object_or_404(Config, pk=pk)
    try:
        job = enqueue(config, origin=JobOrigin.MANUAL, requested_by=request.user)
    except EnqueueRefused as exc:
        detail = f" — {'; '.join(exc.errors)}" if exc.errors else ""
        messages.error(request, f"{config.name}: {exc}{detail}")
    else:
        messages.success(request, f"Задача #{job.pk} поставлена в очередь для «{config.name}».")
    return _redirect_preserving_filter(request)


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

    return _redirect_preserving_filter(request)


@staff_member_required
@require_POST
def cancel_job(request: HttpRequest, pk: int) -> HttpResponse:
    job = get_object_or_404(Job, pk=pk)
    outcome = request_cancel(job)
    if outcome == "cancelled":
        messages.success(request, f"Задача #{job.pk} отменена — её никто не успел взять.")
    elif outcome == "signalled":
        messages.success(
            request,
            f"Задача #{job.pk} получила сигнал отмены — остановится на ближайшей контрольной "
            f"точке сборщика.",
        )
    else:
        messages.warning(
            request, f"Задача #{job.pk} уже завершена ({job.get_status_display().lower()})."
        )
    return _redirect_preserving_filter(request)


@staff_member_required
def lots_list(request: HttpRequest) -> HttpResponse:
    source = request.GET.get("source", "").strip() or None
    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 1

    lots_page = list_lots(source=source, page=page)
    # Django templates reject leading-underscore lookups (`lot._id`), so surface a plain `id`
    # string here rather than teach the template a filter just for this one field.
    for lot in lots_page.items:
        lot["id"] = str(lot["_id"])

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
