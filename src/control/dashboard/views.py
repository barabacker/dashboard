"""A deliberately small dashboard.

Django Admin is the primary UI; this exists for the two things a list page is bad at: seeing at a
glance what ran, and starting or stopping a run without leaving the page.

Actions are plain form POSTs that redirect. HTMX only adds the auto-refreshing job panel — if the
script fails to load, the page still works, it just stops refreshing itself.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from control.models import Config, Job, JobOrigin, JobStatus
from control.services import EnqueueRefused, enqueue, request_cancel

_RECENT_JOBS = 25


def _recent_jobs():
    return Job.objects.order_by("-created_at")[:_RECENT_JOBS]


@staff_member_required
def index(request: HttpRequest) -> HttpResponse:
    configs = Config.objects.filter(archived=False).order_by("name")
    # Job→Config is a soft reference, so "does this config have something in flight?" is a second
    # query rather than a join. One extra query for the whole page is the right trade here.
    active_config_ids = set(
        Job.objects.filter(status__in=JobStatus.active()).values_list("config_id", flat=True)
    )
    return render(
        request,
        "dashboard/index.html",
        {
            "configs": configs,
            "active_config_ids": active_config_ids,
            "jobs": _recent_jobs(),
            "counts": _status_counts(),
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
        messages.success(request, f"Queued job #{job.pk} for {config.name}.")
    return redirect("dashboard:index")


@staff_member_required
@require_POST
def cancel_job(request: HttpRequest, pk: int) -> HttpResponse:
    job = get_object_or_404(Job, pk=pk)
    outcome = request_cancel(job)
    if outcome == "cancelled":
        messages.success(request, f"Job #{job.pk} cancelled before it was claimed.")
    elif outcome == "signalled":
        messages.success(
            request, f"Job #{job.pk} signalled — it stops at the runner's next checkpoint."
        )
    else:
        messages.warning(request, f"Job #{job.pk} already finished ({job.status}).")
    return redirect("dashboard:index")


def _status_counts() -> dict[str, int]:
    rows = Job.objects.values("status").annotate(n=Count("pk"))
    counts = dict.fromkeys(JobStatus.values, 0)
    for row in rows:
        counts[row["status"]] = row["n"]
    return counts
