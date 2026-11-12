"""HMAC response integrity for Runtime Gateway JSON (SDK verification)."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi.responses import JSONResponse

from config.settings import settings


def runtime_hmac_headers(body_bytes: bytes) -> dict[str, str]:
    key = (settings.app_secret_key or "change-me-in-production").encode()
    digest = hmac.new(key, body_bytes, hashlib.sha256).hexdigest()
    return {
        "X-Karma-Response-Signature": f"sha256={digest}",
        "X-Karma-Response-Body-Sha256": hashlib.sha256(body_bytes).hexdigest(),
    }


def signed_json_response(content: Any, status_code: int = 200) -> JSONResponse:
    body_bytes = json.dumps(content, default=str, separators=(",", ":")).encode("utf-8")
    headers = runtime_hmac_headers(body_bytes)
    return JSONResponse(status_code=status_code, content=content, headers=headers)
