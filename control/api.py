"""HTTP-интерфейс для раннеров. Четыре эндпоинта, обычные вьюхи Django.

Аутентификация — токен раннера в заголовке X-Runner-Token.
Тела запросов и ответов маленькие: данные через control plane не ходят.
"""

import json
from functools import wraps

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from control.conf import control_settings
from control.models import Run, Runner
from control.services import append_logs, complete_run, extend_lease, next_run_for

TOKEN_HEADER = "X-Runner-Token"


def runner_required(view):
    """Пускает только активные раннеры с валидным токеном."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        token = request.headers.get(TOKEN_HEADER, "")
        runner = Runner.objects.filter(token=token, is_active=True).first() if token else None
        if runner is None:
            return JsonResponse({"detail": "Нужен валидный X-Runner-Token"}, status=401)

        runner.touch()
        request.runner = runner
        return view(request, *args, **kwargs)

    return wrapper


def parse_body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None


def get_run(request, run_id):
    """Запуск, выданный именно этому раннеру."""
    return get_object_or_404(Run.objects.select_related("source"), pk=run_id, runner=request.runner)


@csrf_exempt
@require_POST
@runner_required
def claim(request):
    """Забрать следующее задание. Пустой ответ — работы нет."""
    run = next_run_for(request.runner)
    poll = control_settings.POLL_INTERVAL_SECONDS

    if run is None:
        return JsonResponse({"run": None, "poll_interval": poll})

    return JsonResponse(
        {
            "run": {
                "id": run.pk,
                "source": run.source.slug,
                "parser": run.source.parser,
                "params": run.source.params,
                "log_level": run.source.log_level,
                "trigger": run.trigger,
                "lease_expires_at": run.lease_expires_at.isoformat(),
            },
            "poll_interval": poll,
        }
    )


@csrf_exempt
@require_POST
@runner_required
def logs(request, run_id):
    """Принять пачку строк лога. Заодно продлевает аренду."""
    run = get_run(request, run_id)
    payload = parse_body(request)
    if payload is None or not isinstance(payload.get("entries"), list):
        return JsonResponse({"detail": 'Ожидается {"entries": [...]}'}, status=400)

    accepted = append_logs(run, payload["entries"])
    extend_lease(run)
    return JsonResponse({"accepted": accepted})


@csrf_exempt
@require_POST
@runner_required
def heartbeat(request, run_id):
    """Раннер жив и работает — продлить аренду."""
    run = get_run(request, run_id)
    extend_lease(run)
    run.refresh_from_db()
    return JsonResponse({"lease_expires_at": run.lease_expires_at.isoformat()})


@csrf_exempt
@require_POST
@runner_required
def complete(request, run_id):
    """Завершить запуск. Повторный вызов безопасен — статус уже финальный."""
    run = get_run(request, run_id)
    payload = parse_body(request)
    if payload is None:
        return JsonResponse({"detail": "Ожидается JSON"}, status=400)

    status = payload.get("status")
    if status not in (Run.Status.SUCCESS, Run.Status.FAILED):
        return JsonResponse({"detail": "status должен быть success или failed"}, status=400)

    if payload.get("entries"):
        append_logs(run, payload["entries"])
        run.refresh_from_db()

    run = complete_run(
        run,
        status=status,
        counters=payload.get("counters") or {},
        result_locator=str(payload.get("result_locator") or ""),
        error=str(payload.get("error") or ""),
        now=timezone.now(),
    )

    return JsonResponse(
        {
            "id": run.pk,
            "status": run.status,
            "source_active": run.source.is_active,
        }
    )
