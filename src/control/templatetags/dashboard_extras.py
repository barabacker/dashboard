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
