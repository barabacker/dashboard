"""Демонстрационные парсеры.

Настоящие живут в отдельном репозитории; здесь два примера, чтобы прогнать
весь цикл от расписания до записи в журнале.

Парсер — обычная функция: принимает параметры, делает работу и возвращает
отчёт. Данные он сохраняет сам, куда посчитает нужным; наружу отдаёт только
счётчики и непрозрачную ссылку на результат.
"""

import logging
import random
import time

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


PARSERS = {
    "demo.numbers": demo_numbers,
    "demo.empty": demo_empty,
}
