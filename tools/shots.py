"""Скриншоты админки через Playwright. Запуск: python tools/shots.py"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("01-dashboard", "/admin/", 1600),
    ("02-vehicles", "/admin/fleet/vehicle/", 1600),
    ("03-vehicle-form", None, 1600),
    ("04-zones", "/admin/fleet/zone/", 1600),
    ("05-zone-form", None, 1600),
    ("06-trips", "/admin/fleet/trip/", 1600),
    ("07-alerts", "/admin/fleet/alert/", 1600),
]


def main():
    dark = "--dark" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
            color_scheme="dark" if dark else "light",
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        page = ctx.new_page()

        page.goto(f"{BASE}/admin/login/?next=/admin/")
        page.fill("#id_username", "admin")
        page.fill("#id_password", "admin12345")
        page.click("button[type=submit]")
        page.wait_for_url(f"{BASE}/admin/")

        suffix = "-dark" if dark else ""

        def shot(name, full=True):
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / f"{name}{suffix}.png"), full_page=full)
            print("saved", name)

        page.goto(f"{BASE}/admin/")
        shot("01-dashboard")

        page.goto(f"{BASE}/admin/fleet/vehicle/")
        shot("02-vehicles")

        page.goto(f"{BASE}/admin/fleet/vehicle/1/change/")
        shot("03-vehicle-form")

        page.goto(f"{BASE}/admin/fleet/zone/")
        shot("04-zones")

        page.goto(f"{BASE}/admin/fleet/zone/1/change/")
        shot("05-zone-form")

        page.goto(f"{BASE}/admin/fleet/trip/")
        shot("06-trips")

        page.goto(f"{BASE}/admin/fleet/trip/1/change/")
        shot("07-trip-form")

        page.goto(f"{BASE}/admin/fleet/alert/")
        shot("08-alerts")

        # Мобильный вид
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
        mp.wait_for_timeout(1200)
        mp.screenshot(path=str(OUT / f"09-mobile{suffix}.png"), full_page=True)
        print("saved 09-mobile")

        browser.close()


if __name__ == "__main__":
    main()
