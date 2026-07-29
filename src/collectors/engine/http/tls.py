"""TLS helper: build a certifi CA bundle augmented with a site's extra cert."""

from __future__ import annotations

import functools
import tempfile
from pathlib import Path

import certifi


@functools.cache
def ca_bundle_with_extra_cert(cert_path: str) -> str:
    """Build (and disk-cache) a certifi bundle plus a site's extra certificate.

    Some sites omit an intermediate certificate from their TLS chain;
    curl/BoringSSL, unlike browsers, will not fetch it, so we append it here.
    ``cert_path`` is an absolute path to the extra PEM file (the caller resolves
    it — see http.factory).
    """
    combined = Path(certifi.where()).read_text(encoding="utf-8")
    combined += "\n" + Path(cert_path).read_text(encoding="utf-8")
    # delete=False on purpose: the file outlives this call — curl reads it by path, for as long
    # as the process keeps making requests. The lru-cached return value is that path.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", prefix="ca-bundle-", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(combined)
    return tmp.name
