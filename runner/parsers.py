"""Демонстрационные парсеры.

Настоящие живут в отдельном репозитории; здесь два примера, чтобы прогнать
весь цикл от расписания до записи в журнале.

Парсер — обычная функция: принимает параметры, делает работу и возвращает
отчёт. Данные он сохраняет сам, куда посчитает нужным; наружу отдаёт только
счётчики и непрозрачную ссылку на результат.
"""

import json
import logging
import random
import time
import urllib.error
import urllib.request

log = logging.getLogger("parsers")


def demo_numbers(params):
    """Изображает выгрузку: пишет логи, считает элементы, может упасть."""
    count = int(params.get("count", 25))
    delay = float(params.get("delay", 0.05))
    fail_at = params.get("fail_at")

    new = updated = 0
    for index in range(1, count + 1):
        time.sleep(delay)

        if fail_at and index == int(fail_at):
            raise RuntimeError(f"источник ответил 500 на элементе {index}")

        if index % 10 == 0:
            log.info("Обработано %s из %s", index, count)
        if index % 7 == 0:
            log.warning("Элемент %s без даты публикации, пропускаю поле", index)
        log.debug("Элемент %s разобран", index)

        if random.random() < 0.3:
            updated += 1
        else:
            new += 1

    return {
        "counters": {"items_total": count, "items_new": new, "items_updated": updated},
        "locator": f"demo://storage/batch-{int(time.time())}",
    }


def demo_empty(params):
    """Возвращает пустой результат — чтобы проверить, как это выглядит в журнале."""
    log.info("Источник не отдал ни одной записи")
    return {"counters": {"items_total": 0}, "locator": ""}


def demo_mockhttp(params):
    """Ходит по нескольким эндпоинтам mockhttp.org и считает ответы.

    Живой пример HTTP-парсера: у mockhttp.org есть пути с заранее известным
    поведением (/status/503 всегда пятисотит, /delay/1 отвечает через секунду),
    поэтому на нём удобно смотреть, как в журнал ложатся успехи и ошибки.

    Параметры:
        base_url  — база, по умолчанию https://mockhttp.org
        paths     — список путей; по умолчанию небольшая подборка
        timeout   — таймаут одного запроса, с
        pause     — пауза между запросами, с
    """
    base_url = str(params.get("base_url", "https://mockhttp.org")).rstrip("/")
    paths = params.get("paths") or ["get", "json", "uuid", "headers", "delay/1", "status/503"]
    timeout = float(params.get("timeout", 15))
    pause = float(params.get("pause", 0.2))

    ok = failed = 0
    bytes_total = 0

    for index, path in enumerate(paths, start=1):
        url = f"{base_url}/{str(path).lstrip('/')}"
        request = urllib.request.Request(url, headers={"User-Agent": "dashboard-demo-parser"})
        started = time.monotonic()

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            # Ответ есть, просто не 2xx: это данные источника, а не сбой парсера
            body = exc.read()
            status = exc.code
        except urllib.error.URLError as exc:
            failed += 1
            log.warning("%s/%s %s — не ответил: %s", index, len(paths), url, exc.reason)
            continue

        elapsed_ms = int((time.monotonic() - started) * 1000)
        bytes_total += len(body)

        if 200 <= status < 300:
            ok += 1
            log.info("%s/%s %s → %s за %s мс, %s Б", index, len(paths), url, status, elapsed_ms, len(body))
        else:
            failed += 1
            log.warning("%s/%s %s → %s за %s мс", index, len(paths), url, status, elapsed_ms)

        try:
            log.debug("Тело %s: %s", url, json.loads(body))
        except ValueError:
            log.debug("Тело %s не JSON, %s Б", url, len(body))

        if pause:
            time.sleep(pause)

    log.info("Запросов %s: успешных %s, неудачных %s", len(paths), ok, failed)

    return {
        "counters": {
            "items_total": len(paths),
            "items_new": ok,
            "failed": failed,
            "bytes_total": bytes_total,
        },
        "locator": f"{base_url} ({ok}/{len(paths)} ok)",
    }


PARSERS = {
    "demo.numbers": demo_numbers,
    "demo.empty": demo_empty,
    "demo.mockhttp": demo_mockhttp,
}
