"""Скриншоты админки через Playwright.

    pip install -r requirements-dev.txt && playwright install chromium
    python manage.py runserver 8099
    python tools/shots.py [--dark]
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SHOTS_BASE_URL", "http://127.0.0.1:8099")
USERNAME = os.environ.get("SHOTS_USER", "admin")
PASSWORD = os.environ.get("SHOTS_PASSWORD", "admin12345")
CHROMIUM = os.environ.get("SHOTS_CHROMIUM")  # путь к бинарю, если не из playwright install
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("01-dashboard", "/admin/"),
    ("02-users", "/admin/auth/user/"),
    ("03-user-form", "/admin/auth/user/1/change/"),
    ("04-groups", "/admin/auth/group/"),
]


def main():
    dark = "--dark" in sys.argv
    suffix = "-dark" if dark else ""

    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": CHROMIUM} if CHROMIUM else {}))
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
            color_scheme="dark" if dark else "light",
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        page = ctx.new_page()

        page.goto(f"{BASE}/admin/login/?next=/admin/")
        page.fill("#id_username", USERNAME)
        page.fill("#id_password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE}/admin/")

        for name, url in PAGES:
            page.goto(f"{BASE}{url}")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(OUT / f"{name}{suffix}.png"), full_page=True)
            print("saved", name)

        mobile = browser.new_context(
            viewport={"width": 420, "height": 900},
            device_scale_factor=2,
            color_scheme="dark" if dark else "light",
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            storage_state=ctx.storage_state(),
        )
        mp = mobile.new_page()
        mp.goto(f"{BASE}/admin/")
        mp.wait_for_timeout(1000)
        mp.screenshot(path=str(OUT / f"05-mobile{suffix}.png"), full_page=True)
        print("saved 05-mobile")

        browser.close()


if __name__ == "__main__":
    main()
