"""Логика control plane: расписание, выдача заданий, приём результатов.

Фоновых процессов нет — планирование происходит в момент, когда раннер
приходит за заданием.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from control.conf import control_settings
from control.models import Run, RunLog, Source


def expire_stale_runs(now=None):
    """Возвращает зависшие запуски: раннер взял задание и пропал.

    Вызывается перед выдачей задания, а также командой обслуживания.
    """
    now = now or timezone.now()
    stale = Run.objects.filter(status=Run.Status.RUNNING, lease_expires_at__lt=now).select_related("source")

    expired = 0
    for run in stale:
        updated = Run.objects.filter(pk=run.pk, status=Run.Status.RUNNING).update(
            status=Run.Status.EXPIRED,
            finished_at=now,
            error="Раннер не подавал признаков жизни дольше срока аренды",
        )
        if updated:
            register_failure(run.source)
            expired += 1
    return expired


def schedule_due_runs(now=None):
    """Создаёт запуски для источников, которым пора.

    Источник с незавершённым запуском пропускается: пусть предыдущий
    сначала закончится, иначе на медленном источнике задания накопятся.
    """
    now = now or timezone.now()
    created = []

    due = Source.objects.filter(is_active=True, next_run_at__lte=now)
    for source in due:
        has_active = Run.objects.filter(
            source=source, status__in=(Run.Status.PENDING, Run.Status.RUNNING)
        ).exists()

        # next_run сдвигаем в любом случае, иначе источник будет «просрочен» вечно
        Source.objects.filter(pk=source.pk).update(next_run_at=source.compute_next_run(now))

        if has_active:
            continue

        created.append(Run.objects.create(source=source, trigger=Run.Trigger.SCHEDULE))

    return created


def claim_run(runner, now=None):
    """Отдаёт раннеру одно задание, помечая его выполняющимся.

    Захват атомарный: UPDATE с условием по статусу. Если два раннера
    пришли одновременно, задание достанется ровно одному.
    """
    now = now or timezone.now()

    candidates = Run.objects.filter(status=Run.Status.PENDING).order_by("created_at")[:10]
    for run in candidates:
        lease = now + timezone.timedelta(seconds=run.source.lease_seconds)
        claimed = Run.objects.filter(pk=run.pk, status=Run.Status.PENDING).update(
            status=Run.Status.RUNNING,
            runner=runner,
            started_at=now,
            lease_expires_at=lease,
        )
        if claimed:
            run.refresh_from_db()
            return run
    return None


def next_run_for(runner, now=None):
    """Полный цикл выдачи: подчистить зависшее, создать что пора, отдать одно."""
    now = now or timezone.now()
    expire_stale_runs(now)
    schedule_due_runs(now)
    return claim_run(runner, now)


def extend_lease(run, now=None):
    now = now or timezone.now()
    Run.objects.filter(pk=run.pk).update(
        lease_expires_at=now + timezone.timedelta(seconds=run.source.lease_seconds)
    )


def append_logs(run, entries):
    """Сохраняет пачку строк лога с учётом лимитов.

    Возвращает количество принятых строк. Лишние отбрасываются: один
    зациклившийся парсер не должен забивать базу.
    """
    limit = control_settings.MAX_LOG_LINES_PER_RUN
    max_length = control_settings.MAX_LOG_MESSAGE_LENGTH

    # Счётчики читаем из базы: в памяти может лежать значение до предыдущей пачки
    current = Run.objects.filter(pk=run.pk).values("log_lines").first()
    already = current["log_lines"] if current else 0
    if already >= limit:
        return 0

    entries = entries[: control_settings.MAX_LOG_BATCH]
    room = limit - already
    accepted = entries[:room]

    objects = []
    warnings = 0
    for offset, entry in enumerate(accepted, start=1):
        level = str(entry.get("level", RunLog.Level.INFO)).upper()
        if level not in RunLog.Level.values:
            level = RunLog.Level.INFO
        if level in (RunLog.Level.WARNING, RunLog.Level.ERROR, RunLog.Level.CRITICAL):
            warnings += 1

        message = str(entry.get("message", ""))
        if len(message) > max_length:
            message = message[:max_length] + " …обрезано"

        ts = entry.get("ts")
        parsed_ts = timezone.datetime.fromisoformat(ts) if ts else timezone.now()
        if timezone.is_naive(parsed_ts):
            parsed_ts = timezone.make_aware(parsed_ts)

        objects.append(
            RunLog(
                run=run,
                seq=already + offset,
                ts=parsed_ts,
                level=level,
                message=message,
                context=entry.get("context") or {},
            )
        )

    if not objects:
        return 0

    with transaction.atomic():
        RunLog.objects.bulk_create(objects)
        Run.objects.filter(pk=run.pk).update(
            log_lines=F("log_lines") + len(objects),
            warnings_count=F("warnings_count") + warnings,
        )

    limit_reached = already + len(objects) >= limit
    if limit_reached and not RunLog.objects.filter(run=run, seq=limit + 1).exists():
        RunLog.objects.create(
            run=run,
            seq=limit + 1,
            ts=timezone.now(),
            level=RunLog.Level.WARNING,
            message=f"Достигнут лимит в {limit} строк лога, дальнейшие строки отброшены",
        )

    return len(objects)


def register_failure(source):
    """Учитывает неудачу и отключает источник, если их подряд слишком много."""
    source.refresh_from_db()
    failures = source.consecutive_failures + 1
    fields = {"consecutive_failures": failures}

    if source.max_failures and failures >= source.max_failures:
        fields["is_active"] = False

    Source.objects.filter(pk=source.pk).update(**fields)
    return fields.get("is_active", source.is_active)


def complete_run(run, *, status, counters=None, result_locator="", error="", now=None):
    """Закрывает запуск. Повторный вызов ничего не меняет."""
    now = now or timezone.now()
    if not run.is_active:
        return run

    counters = counters or {}
    known = {"items_total", "items_new", "items_updated"}
    extra = {key: value for key, value in counters.items() if key not in known}

    Run.objects.filter(pk=run.pk).update(
        status=status,
        finished_at=now,
        items_total=int(counters.get("items_total", 0)),
        items_new=int(counters.get("items_new", 0)),
        items_updated=int(counters.get("items_updated", 0)),
        counters=extra,
        result_locator=result_locator[:500],
        error=error,
    )

    Source.objects.filter(pk=run.source_id).update(last_run_at=now)
    if status == Run.Status.SUCCESS:
        Source.objects.filter(pk=run.source_id).update(consecutive_failures=0)
    else:
        register_failure(run.source)

    run.refresh_from_db()
    return run


def trigger_manual_run(source):
    """Кнопка «Запустить сейчас»: задание подхватит раннер при следующем опросе."""
    return Run.objects.create(source=source, trigger=Run.Trigger.MANUAL)
