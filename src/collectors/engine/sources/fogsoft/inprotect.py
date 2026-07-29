"""inprotect anti-bot bypass for iTender (Fogsoft) sites: pure solver + hook.

The site is behind a JS "inprotect" challenge: the first request returns HTTP
429 with a small HTML page whose script collects a browser fingerprint and sets
two cookies, then reloads. The challenge is purely client-side — the server
only checks that the cookies ``inprotect_ok_<id>`` and ``inprotect_fp_<id>`` are
present; the nonce comes from the challenge page itself. So it is solvable over
plain HTTP, no browser.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_NONCE_RE = re.compile(r'nonce\s*=\s*"([0-9a-f]+)"')
_SITE_ID_RE = re.compile(r"inprotect_ok_(\d+)")

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


def looks_like_challenge(text: str, status_code: int | None = None) -> bool:
    """Is this an inprotect challenge page rather than a real listing?

    Markers: HTTP 429, or an inprotect script page with no ViewState (a real
    listing page always has __CVIEWSTATE).
    """
    if status_code == 429:
        return True
    return "inprotect_fp_" in text and "inprotect_ok_" in text and "__CVIEWSTATE" not in text


def build_cookies(html: str, user_agent: str | None = None) -> dict[str, str] | None:
    """Build the inprotect pass cookies from the challenge HTML.

    Returns ``{"inprotect_ok_<id>": "1", "inprotect_fp_<id>": "<base64>"}`` or
    None if the expected markers (site id / nonce) are absent.
    """
    site_id_m = _SITE_ID_RE.search(html)
    nonce_m = _NONCE_RE.search(html)
    if not (site_id_m and nonce_m):
        return None

    site_id = site_id_m.group(1)
    nonce = nonce_m.group(1)

    fp = {
        "ua": user_agent or _DEFAULT_UA,
        "plat": "Win32",
        "lang": "ru",
        "languages": ["ru", "en-US", "en"],
        "timeZone": "Europe/Moscow",
        "devToolsOpen": False,
        "pluginsCount": 5,
        "isHeadless": False,
        "screenOrientation": "landscape-primary",
        "timeOrigin": 1780554480011.6,
        "res": "1920x1080",
        "threads": 8,
        "chrome": 1,
        "touch": 0,
        "canvas": 180447607,
        "webgl": (
            "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 (0x00001BE0) "
            "Direct3D11 vs_5_0 ps_5_0, D3D11)|Google Inc. (NVIDIA)"
        ),
        "fonts": 0,
        "nonce": nonce,
    }
    payload = json.dumps(fp, separators=(",", ":"), ensure_ascii=False)
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return {f"inprotect_ok_{site_id}": "1", f"inprotect_fp_{site_id}": b64}


async def solve_inprotect(response: Any, *, session: Any, retry: Any) -> Any:
    """Response hook: if the response is an inprotect challenge, set the pass
    cookies and retry."""
    if not looks_like_challenge(response.text, response.status_code):
        return response

    cookies = build_cookies(response.text)
    if not cookies:
        logger.warning(
            "inprotect.unsolvable url=%s status=%s",
            getattr(response, "url", "?"),
            response.status_code,
        )
        return response

    for name, value in cookies.items():
        session.cookies.set(name, value)
    logger.info(
        "inprotect.solved url=%s cookies=%s", getattr(response, "url", "?"), sorted(cookies)
    )

    return await retry()
