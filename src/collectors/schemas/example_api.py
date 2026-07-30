"""Schema for the `example_api` collector.

The reference collector: exercises parameter validation and cooperative cancellation without any
network I/O, so the tests that drive it stay deterministic. `dataset` is required on purpose — it
is what lets `EnqueueRefused`/`config_invalid` be exercised: a Config whose raw parameters do not
satisfy this schema (edited directly, or predating a field that became required) must fail fast
rather than produce a runnable Job.
"""

from __future__ import annotations

from collectors.schemas.base import CollectorDescriptor, ParamSpec

KEY = "example_api"

# Parameter *names* stay English — they are keys in the stored JSON and in the runner code.
# Descriptions are Russian: they are shown to whoever fills the form.
_BASE_URL = ParamSpec(
    name="base_url",
    kind="str",
    required=True,
    description="Корневой URL источника. Часть ответа на «что именно собрали» — попадает в снимок.",
)
_PATH = ParamSpec(
    name="path",
    kind="str",
    default="/items",
    description="Путь эндпоинта, дописывается к base_url.",
)
_PAGE_SIZE = ParamSpec(
    name="page_size",
    kind="int",
    default=100,
    min_value=1,
    max_value=1000,
    description="Сколько записей запрашивать на страницу.",
)
_PAGES = ParamSpec(
    name="pages",
    kind="int",
    default=1,
    min_value=1,
    max_value=100,
    description="Сколько страниц пройти. Каждая страница — контрольная точка для отмены.",
)
_CREDENTIAL_REF = ParamSpec(
    name="credential_ref",
    kind="str",
    default="",
    is_credential_ref=True,
    description=(
        "Имя переменной окружения с токеном доступа. В снимок попадает только *имя*; сам токен "
        "разрешается в момент выполнения и никогда не сохраняется в задаче."
    ),
)

DESCRIPTOR = CollectorDescriptor(
    key=KEY,
    display_name="Пример: HTTP API",
    description=(
        "Эталонный сборщик: на нём проверяются валидация параметров и кооперативная отмена. "
        "Вместо сетевых запросов он выдумывает записи, поэтому тесты остаются детерминированными."
    ),
    summary="Добавлен явный выбор набора данных; записи помечаются им.",
    params=(
        _BASE_URL,
        _PATH,
        _PAGE_SIZE,
        _PAGES,
        _CREDENTIAL_REF,
        ParamSpec(
            name="dataset",
            kind="str",
            required=True,
            description="Какой набор данных выгружать.",
        ),
        ParamSpec(
            name="since",
            kind="str",
            default="",
            description="Необязательная нижняя граница в формате ISO-8601, уходит в фильтр API.",
        ),
        ParamSpec(
            name="page_delay_seconds",
            kind="float",
            default=0.0,
            min_value=0.0,
            max_value=60.0,
            description="Искусственная пауза между страницами. Нужна, чтобы отмену можно было "
            "увидеть на запуске, который успеваешь поймать.",
        ),
    ),
)
