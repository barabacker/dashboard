"""Initial data: the sites the temporary parser project already crawled.

Typing thirty-one sites into a form is nobody's idea of onboarding, so the list the temporary
project kept in `platforms.toml` is carried over once, here. This is *initial data*, not a source
of truth: after the first run the sites live in the database and are edited in the admin.
Re-running the command adds what is missing and leaves existing sites alone — it never
overwrites an edit.

Each entry becomes one `Source` (domain, listing path, TLS quirks) and one `Config` profile
referencing it (collector, name, `enabled`) — none of these carried-over sites need more than one
profile, so the split is invisible here; it only matters once a site needs a second named profile,
which the admin handles from then on.

Sites the temporary project had switched off are created switched off, with the reason printed
rather than stored: neither model has anywhere to keep a note, and inventing a column for one is
worse than a line in the log.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from collectors.schemas.tender import collector_key
from control.models import Config, Source

#: (engine, title, domain, extras). Extras carry only what differs from the engine defaults.
SOURCES: list[dict[str, Any]] = [
    # --- iTender / Fogsoft -------------------------------------------------------------
    {"engine": "fogsoft", "title": "Центр реализации", "domain": "https://bankrupt.centerr.ru"},
    {
        "engine": "fogsoft",
        "title": "uTender",
        "domain": "http://utender.ru",
        "enabled": False,
        "note": "Пагинация не двигается — перекачивает первую страницу. Включить после фикса.",
    },
    {"engine": "fogsoft", "title": "АЛЬФАЛОТ", "domain": "https://bankrupt.alfalot.ru"},
    {
        "engine": "fogsoft",
        "title": "Уральская электронная торговая площадка",
        "domain": "https://bankrupt.etpu.ru",
    },
    {
        "engine": "fogsoft",
        "title": "Балтийская электронная площадка",
        "domain": "https://bankruptcy.bepspb.ru",
    },
    {
        "engine": "fogsoft",
        "title": "АРБбитЛот",
        "domain": "https://torgi.arbbitlot.ru",
        "params": {"skip_tls_verify": True},
        "note": "Сертификат сайта просрочен на их стороне — набор CA не помогает.",
    },
    {"engine": "fogsoft", "title": "Арбитат", "domain": "http://arbitat.ru"},
    {
        "engine": "fogsoft",
        "title": "Объединённая торговая площадка",
        "domain": "https://bankrupt.utpl.ru",
    },
    {"engine": "fogsoft", "title": "Tender Technologies", "domain": "https://bankrupt.tender.one"},
    {"engine": "fogsoft", "title": "ЭТП Югра", "domain": "https://etpugra.ru"},
    {"engine": "fogsoft", "title": "ТЕНДЕР ГАРАНТ", "domain": "https://tendergarant.com"},
    {"engine": "fogsoft", "title": "ЮЭТП", "domain": "https://torgibankrot.ru"},
    {
        "engine": "fogsoft",
        "title": "МЕТА-ИНВЕСТ",
        "domain": "https://meta-invest.ru",
        "params": {"extra_ca_cert": "meta_invest_globalsign_gcc_r3_dv_tls_ca_2020.pem"},
        "note": "Сервер не отдаёт промежуточный сертификат цепочки — подставляем свой.",
    },
    {
        "engine": "fogsoft",
        "title": "Property Trade",
        "domain": "https://propertytrade.ru",
        "enabled": False,
        "note": "Было выключено во временном проекте без указания причины — проверить.",
    },
    {
        "engine": "fogsoft",
        "title": "ЭТП Регион (GloriaService)",
        "domain": "https://gloriaservice.ru",
    },
    {
        "engine": "fogsoft",
        "title": "ЭТП Заказ РФ",
        "domain": "http://bankrot.zakazrf.ru",
        "enabled": False,
        "note": "Пагинация работает исправно (проверено вживую 2026-07-30), но за 200 страниц "
        "нашёлся только один лот, не помеченный как завершённый, — площадка фактически архив "
        "закрытых торгов. Включить, если появятся живые лоты.",
    },
    {"engine": "fogsoft", "title": "ЕЭТП / ets24.ru", "domain": "http://bankrupt.ets24.ru"},
    # --- Kendo-ETP ---------------------------------------------------------------------
    {"engine": "kendo", "title": "Альянс Трэйд", "domain": "https://trade-alliance.ru"},
    {"engine": "kendo", "title": "Селтим", "domain": "https://bankrupt.seltim.ru"},
    {
        "engine": "kendo",
        "title": "Электро-Торги",
        "domain": "https://bankrotstvo.electro-torgi.ru",
    },
    {"engine": "kendo", "title": "Торги82", "domain": "https://lot.torgi82.ru"},
    {
        "engine": "kendo",
        "title": "ВЭТП",
        "domain": "https://банкрот.вэтп.рф",
        "note": "IDN-домен, хранится в Unicode — curl_cffi кодирует в punycode сам.",
    },
    # --- btorg / edoc-ETP --------------------------------------------------------------
    {"engine": "btorg", "title": "Аукционный тендерный центр", "domain": "https://atctrade.ru"},
    {"engine": "btorg", "title": "Аукционы Сибири", "domain": "https://ausib.ru"},
    {"engine": "btorg", "title": "ЭТП Профит", "domain": "https://etp-profit.ru"},
    {"engine": "btorg", "title": "Аукционный центр", "domain": "https://aukcioncenter.ru"},
    {"engine": "btorg", "title": "Региональная торговая площадка", "domain": "https://regtorg.com"},
    {"engine": "btorg", "title": "ПТП-Центр", "domain": "https://ptp-center.ru"},
    # --- rus-on ------------------------------------------------------------------------
    {"engine": "ruson", "title": "Новые информационные сервисы", "domain": "https://nistp.ru"},
    {"engine": "ruson", "title": "Электронные торги", "domain": "https://el-torg.com"},
    {"engine": "ruson", "title": "РОССИЯ ОнЛайн", "domain": "https://rus-on.ru"},
    {
        "engine": "ruson",
        "title": "Объединённые системы торгов",
        "domain": "https://sistematorg.com",
        "params": {"start_url": "tradelist.php"},
    },
    {
        "engine": "ruson",
        "title": "Промконсалт",
        "domain": "https://promkonsalt.ru",
        "params": {"start_url": "tradelist.php"},
    },
]


class Command(BaseCommand):
    help = "Create the sources carried over from the temporary parser project (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        created, kept = 0, 0

        for spec in SOURCES:
            key = collector_key(spec["engine"])
            domain = spec["domain"]
            site_fields = spec.get("params", {})

            # The domain is the identity: a source renamed in the admin must not be re-created
            # here under its old name.
            if Source.objects.filter(domain=domain).exists():
                kept += 1
                continue

            created += 1
            self.stdout.write(f"+ {spec['title']} ({domain})")
            if spec.get("note"):
                self.stdout.write(f"    {spec['note']}")
            if not dry_run:
                tls_keys = set(Source.TLS_OPTION_FIELDS)
                source_kwargs = {k: v for k, v in site_fields.items() if k not in tls_keys}
                tls_options = {k: v for k, v in site_fields.items() if k in tls_keys}
                source = Source.objects.create(
                    name=spec["title"],
                    domain=domain,
                    tls_options=tls_options,
                    **source_kwargs,
                )
                Config.objects.create(
                    name=spec["title"],
                    collector_key=key,
                    source=source,
                    enabled=spec.get("enabled", True),
                )

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(f"{prefix}источников создано: {created}, уже было: {kept}")
        )
        if dry_run:
            transaction.set_rollback(True)
