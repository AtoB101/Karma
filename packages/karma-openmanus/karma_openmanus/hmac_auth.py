"""HMAC signing for Karma BFF integration calls."""

from __future__ import annotations

import hashlib
import hmac


def hmac_hex_signature(secret: str, timestamp: str, raw_body_utf8: str) -> str:
    """
    Hex-encoded HMAC-SHA256 over ``f"{timestamp}\\n{raw_body_utf8}"``.

    Matches ``docs/KARMA_BFF_OPENMANUS_INTEGRATION.md`` and ``tools.json`` body_canonical.
    """
    msg = f"{timestamp}\n{raw_body_utf8}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return digest
