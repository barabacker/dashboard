"""Schemas for the `example_api` collector.

Two versions ship on purpose so version resolution is exercised end to end:

* **v1.0** — the original contract.
* **v2.0** — adds a **required** `dataset` parameter. That makes the "schedules survive collector
  upgrades, but a scheduled run with now-invalid params fails fast" invariant real and testable,
  rather than a sentence in a document.

Historical versions are never edited in place. A change to v1.0's contract would silently
invalidate every Job snapshot that references it.
"""

from __future__ import annotations

from collectors.schemas.base import CollectorDescriptor, CollectorVersionSchema, ParamSpec

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

V1 = CollectorVersionSchema(
    key=KEY,
    version="1.0",
    schema_version=1,
    summary="Постраничная выгрузка с одного эндпоинта.",
    params=(_BASE_URL, _PATH, _PAGE_SIZE, _PAGES, _CREDENTIAL_REF),
)

V2 = CollectorVersionSchema(
    key=KEY,
    version="2.0",
    schema_version=2,
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
            description="Какой набор данных выгружать. Обязателен начиная с версии 2.0.",
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

DESCRIPTOR = CollectorDescriptor(
    key=KEY,
    display_name="Пример: HTTP API",
    description=(
        "Эталонный сборщик: на нём проверяются разрешение версий, валидация параметров и "
        "кооперативная отмена. Вместо сетевых запросов он выдумывает записи, поэтому тесты "
        "остаются детерминированными."
    ),
    versions=(V1, V2),
)
