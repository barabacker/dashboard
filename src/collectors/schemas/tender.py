"""Schemas for the tender-site collectors — one per parser family.

A *collector* here is an engine: the code that knows how a family of trading platforms builds
its pages (fogsoft, kendo, btorg, ruson). A *site* is authored data — its domain, listing path
and TLS quirks are parameters of a Config, so adding a platform is filling in a form, not
editing a file and deploying.

That split is what keeps snapshot completeness intact: everything site-specific is resolved into
`effective_parameters` at enqueue, and a run needs nothing beyond its snapshot. It is also why
this module stays pure — `control` imports it, so it must not drag the engine (and curl_cffi,
and lxml) into the web process. The engine imports the constants *from here*, not the reverse.
"""

from __future__ import annotations

from pathlib import Path

from collectors.schemas.base import CollectorDescriptor, CollectorVersionSchema, ParamSpec

__all__ = [
    "CERTS_DIR",
    "DEFAULT_LISTING_PATHS",
    "DESCRIPTORS",
    "ENGINE_KEYS",
    "ENGINE_LABELS",
    "UnknownCertificate",
    "available_certs",
    "collector_key",
    "engine_of",
    "resolve_cert_path",
]

#: Every collector key in this module is `tender_<engine>`. The prefix keeps the tender family
#: recognisable in the projection, the job list and the metrics next to collectors of any other
#: kind that may ship later.
KEY_PREFIX = "tender_"

ENGINE_LABELS: dict[str, str] = {
    "fogsoft": "iTender (Fogsoft)",
    "kendo": "Kendo-ETP",
    "btorg": "btorg / edoc-ETP",
    "ruson": "rus-on",
}

ENGINE_KEYS: tuple[str, ...] = tuple(ENGINE_LABELS)

#: Each family's usual listing path. It is a *default*, not a constant: sites within a family
#: differ (sistematorg and promkonsalt serve `tradelist.php`, not `bankrot/trade_list.php`).
DEFAULT_LISTING_PATHS: dict[str, str] = {
    "fogsoft": "public/purchases-all/",
    "kendo": "lots",
    "btorg": "etp/trade/list.html",
    "ruson": "bankrot/trade_list.php",
}

#: Extra intermediate certificates shipped with the code. A site names a *file* here, never a
#: path: the value arrives from an authored form, and an arbitrary path would let whoever fills
#: it splice any readable file into the trusted CA bundle.
CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


class UnknownCertificate(LookupError):
    """`extra_ca_cert` does not name a PEM file shipped in `collectors/certs`."""


def available_certs() -> tuple[str, ...]:
    """PEM file names the code ships — the choices an authoring form can offer."""
    if not CERTS_DIR.is_dir():
        return ()
    return tuple(sorted(path.name for path in CERTS_DIR.glob("*.pem")))


def resolve_cert_path(name: str) -> Path:
    """`"meta_invest_….pem"` → its absolute path under `CERTS_DIR`.

    Raises `UnknownCertificate` for anything that is not a plain file name present there.
    """
    if Path(name).name != name:
        raise UnknownCertificate(f"{name!r}: ожидается имя файла из collectors/certs")
    path = CERTS_DIR / name
    if not path.is_file():
        raise UnknownCertificate(f"{name!r}: такого сертификата нет в collectors/certs")
    return path


def collector_key(engine: str) -> str:
    return f"{KEY_PREFIX}{engine}"


def engine_of(key: str) -> str:
    """`tender_kendo` → `kendo`. The inverse of `collector_key`."""
    if not key.startswith(KEY_PREFIX):
        raise ValueError(f"{key!r} is not a tender collector key")
    return key[len(KEY_PREFIX) :]


# --- the parameters every tender site has -----------------------------------------------
# Names stay English (they are keys in stored JSON and in the engine's own parameter dict);
# descriptions are Russian because they are what the person filling the form reads.

_DOMAIN = ParamSpec(
    name="domain",
    kind="str",
    required=True,
    description="Корень сайта площадки со схемой и без завершающего слэша, "
    "например https://bankrupt.centerr.ru. По его хосту лоты приписываются к источнику.",
)
_MAX_PAGES = ParamSpec(
    name="max_pages",
    kind="int",
    default=0,
    min_value=0,
    max_value=10000,
    description="Ограничение на число страниц листинга. 0 — без ограничения (обходить до "
    "последней страницы). Страницы листинга дёшевы, а живые лоты встречаются и за сотой "
    "страницей, поэтому ограничение — это про отладку, а не про экономию.",
)
_ONLY_ACTIVE = ParamSpec(
    name="only_active",
    kind="bool",
    default=True,
    description="Заходить только в незавершённые торги. Листинг всё равно пролистывается "
    "целиком — выключение флага добавляет к сбору архив, а не страницы.",
)
_CONCURRENCY = ParamSpec(
    name="concurrency",
    kind="int",
    default=1,
    min_value=1,
    max_value=16,
    description="Сколько запросов к одному сайту идёт параллельно. 1 — последовательно. "
    "Поднимать осторожно: это нагрузка на чужой сайт.",
)
_EXTRA_CA_CERT = ParamSpec(
    name="extra_ca_cert",
    kind="str",
    default="",
    description="Имя PEM-файла из collectors/certs с промежуточным сертификатом, который сайт "
    "не отдаёт сам. Пусто — обычный набор корневых сертификатов.",
)
_SKIP_TLS_VERIFY = ParamSpec(
    name="skip_tls_verify",
    kind="bool",
    default=False,
    description="Полностью отключить проверку сертификата. Только для сайтов, у которых "
    "сертификат сломан на их стороне и набор CA не помогает: снимает защиту от подмены "
    "трафика для этого сайта.",
)
_FETCH_DETAILS = ParamSpec(
    name="fetch_details",
    kind="bool",
    default=True,
    description="Заходить в карточку лота за подробностями (разделы, документы, график "
    "снижения цены). Выключение оставляет только табличные поля листинга, зато обход "
    "становится в разы дешевле.",
)

#: Human text per engine: what the family is and how a crawl of it behaves.
_SUMMARIES: dict[str, str] = {
    "fogsoft": "Листинг ASP.NET с постраничной навигацией через ViewState; строка листинга — "
    "это сам лот, подробности берутся с его карточки.",
    "kendo": "Листинг карточек торгов; лоты и авторитетные поля торга берутся с его страницы.",
    "btorg": "HTML-таблица торгов; лоты подгружаются AJAX-фрагментом по каждому торгу.",
    "ruson": "Разнородный листинг сводится к ссылкам на trade_view.php; эта страница "
    "единообразна и отдаёт и торг, и все его лоты.",
}

_DESCRIPTIONS: dict[str, str] = {
    "fogsoft": "Семейство площадок на движке iTender (Fogsoft): «Центр реализации», "
    "«АЛЬФАЛОТ», «Балтийская электронная площадка» и другие.",
    "kendo": "Семейство площадок на движке Kendo-ETP: «Альянс Трэйд», «Селтим», «Торги82» "
    "и другие.",
    "btorg": "Семейство площадок btorg / edoc-ETP: «Аукционный тендерный центр», "
    "«Аукционы Сибири», «ЭТП Профит» и другие.",
    "ruson": "Семейство площадок rus-on: «Новые информационные сервисы», «Электронные торги», "
    "«РОССИЯ ОнЛайн» и другие.",
}


def _params_for(engine: str) -> tuple[ParamSpec, ...]:
    """The parameter set of one engine.

    Everything is shared except two things that are genuinely engine-specific: the listing path
    default, and `fetch_details` — which only fogsoft can honour. For the three dive engines the
    lots *live* on the detail page, so "skip the details" would mean "collect nothing"; offering
    the switch there would be offering a lie.
    """
    listing_path = ParamSpec(
        name="listing_path",
        kind="str",
        default=DEFAULT_LISTING_PATHS[engine],
        description=f"Путь к листингу относительно домена. По умолчанию "
        f"{DEFAULT_LISTING_PATHS[engine]!r} — менять только тем сайтам семейства, "
        f"которые отдают листинг по другому адресу.",
    )
    common = (
        _DOMAIN,
        listing_path,
        _MAX_PAGES,
        _ONLY_ACTIVE,
        _CONCURRENCY,
        _EXTRA_CA_CERT,
        _SKIP_TLS_VERIFY,
    )
    return (*common, _FETCH_DETAILS) if engine == "fogsoft" else common


def _descriptor_for(engine: str) -> CollectorDescriptor:
    key = collector_key(engine)
    return CollectorDescriptor(
        key=key,
        display_name=f"Торги: {ENGINE_LABELS[engine]}",
        description=_DESCRIPTIONS[engine],
        versions=(
            CollectorVersionSchema(
                key=key,
                version="1.0",
                schema_version=1,
                summary=_SUMMARIES[engine],
                params=_params_for(engine),
            ),
        ),
    )


DESCRIPTORS: tuple[CollectorDescriptor, ...] = tuple(
    _descriptor_for(engine) for engine in ENGINE_KEYS
)
