"""Настройки control plane с разумными значениями по умолчанию.

Переопределяются словарём CONTROL в settings.py.
"""

from django.conf import settings

DEFAULTS = {
    # сколько живёт аренда задания, если раннер молчит
    "LEASE_SECONDS": 600,
    # сколько хранить строки логов и сами запуски
    "LOG_RETENTION_DAYS": 30,
    "RUN_RETENTION_DAYS": 365,
    # ограничители, чтобы один болтливый парсер не забил базу
    "MAX_LOG_LINES_PER_RUN": 10_000,
    "MAX_LOG_MESSAGE_LENGTH": 4_000,
    "MAX_LOG_BATCH": 500,
    # рекомендуемый интервал опроса — раннер читает его из ответа
    "POLL_INTERVAL_SECONDS": 10,
    # сколько строк лога показывать на странице запуска
    "LOG_TAIL_LINES": 500,
}


class ControlSettings:
    def __getattr__(self, name):
        if name not in DEFAULTS:
            raise AttributeError(name)
        return getattr(settings, "CONTROL", {}).get(name, DEFAULTS[name])


control_settings = ControlSettings()
