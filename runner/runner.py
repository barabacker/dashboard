"""Референсный раннер: забирает задания у control plane и выполняет их.

Живёт здесь временно — его место в репозитории парсеров. Поэтому написан
на одной стандартной библиотеке: копируется как есть, зависимостей не тянет.

    DASHBOARD_URL=http://127.0.0.1:8000 RUNNER_TOKEN=... python runner/runner.py

Что делает цикл:
    1. просит задание;
    2. находит парсер по ключу в реестре PARSERS;
    3. выполняет его, попутно отправляя логи пачками;
    4. сообщает результат: счётчики, куда легли данные, ошибку.

Сами данные в control plane не отправляются — только отчёт о запуске.
"""

import json
import logging
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import UTC, datetime

from parsers import PARSERS

BASE_URL = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("RUNNER_TOKEN", "")
DEFAULT_POLL = int(os.environ.get("POLL_INTERVAL", "10"))
BATCH_SIZE = int(os.environ.get("LOG_BATCH_SIZE", "50"))
BATCH_SECONDS = float(os.environ.get("LOG_BATCH_SECONDS", "2"))

log = logging.getLogger("runner")


def request(path, payload=None):
    """POST с токеном раннера. Возвращает разобранный JSON."""
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/{path}",
        data=data,
        headers={"Content-Type": "application/json", "X-Runner-Token": TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read() or b"{}")


class RemoteLogHandler(logging.Handler):
    """Копит записи и отправляет их в control plane пачками.

    Парсеру достаточно обычного logging.getLogger(...) — про отправку
    он ничего не знает.
    """

    def __init__(self, run_id):
        super().__init__()
        self.run_id = run_id
        self.buffer = []
        self.last_flush = time.monotonic()

    def emit(self, record):
        self.buffer.append(
            {
                "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                "level": record.levelname,
                "message": self.format(record),
            }
        )
        too_many = len(self.buffer) >= BATCH_SIZE
        too_long = time.monotonic() - self.last_flush >= BATCH_SECONDS
        if too_many or too_long:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        entries, self.buffer = self.buffer, []
        self.last_flush = time.monotonic()
        try:
            request(f"runs/{self.run_id}/logs/", {"entries": entries})
        except urllib.error.URLError as exc:
            # Логи не должны ронять запуск: пишем в stderr и работаем дальше
            print(f"не удалось отправить логи: {exc}", file=sys.stderr)


def execute(run):
    """Выполняет один запуск и возвращает отчёт для control plane."""
    parser = PARSERS.get(run["parser"])
    handler = RemoteLogHandler(run["id"])
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(getattr(logging, run.get("log_level", "INFO"), logging.INFO))

    try:
        if parser is None:
            raise LookupError(f"парсер «{run['parser']}» не найден в реестре раннера")

        log.info("Старт: источник %s, параметры %s", run["source"], run["params"])
        result = parser(run["params"])
        log.info("Готово: %s", result.get("counters", {}))

        return {
            "status": "success",
            "counters": result.get("counters", {}),
            "result_locator": result.get("locator", ""),
        }
    except Exception as exc:
        log.error("Запуск упал: %s", exc)
        log.debug(traceback.format_exc())
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        handler.flush()
        root.removeHandler(handler)


def main():
    if not TOKEN:
        sys.exit("Не задан RUNNER_TOKEN")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("Раннер запущен, control plane: %s", BASE_URL)

    once = "--once" in sys.argv

    while True:
        try:
            answer = request("runs/claim/")
        except urllib.error.URLError as exc:
            log.warning("Control plane недоступен: %s", exc)
            if once:
                sys.exit(1)
            time.sleep(DEFAULT_POLL)
            continue

        run = answer.get("run")
        if run is None:
            if once:
                log.info("Заданий нет")
                return
            time.sleep(answer.get("poll_interval", DEFAULT_POLL))
            continue

        log.info("Взял запуск #%s (%s)", run["id"], run["parser"])
        report = execute(run)
        request(f"runs/{run['id']}/complete/", report)
        log.info("Запуск #%s завершён: %s", run["id"], report["status"])

        if once:
            return


if __name__ == "__main__":
    main()
