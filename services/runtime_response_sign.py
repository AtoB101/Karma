"""HMAC response integrity for Runtime Gateway JSON (SDK verification)."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi.responses import JSONResponse

from config.settings import settings


def runtime_hmac_headers(body_bytes: bytes) -> dict[str, str]:
    current_key = (settings.app_secret_key or "change-me-in-production").encode()
    headers = {
        "X-Karma-Response-Body-Sha256": hashlib.sha256(body_bytes).hexdigest(),
    }
    if settings.secret_rotation_active():
        # 过渡期主签名头继续用上一把钥签（老 SDK 只认这一个头），
        # 新 SDK 走附加头 X-Karma-Response-Signature-V2（当前钥）。
        previous_key = (settings.app_secret_key_previous or "").encode()
        headers["X-Karma-Response-Signature"] = (
            f"sha256={hmac.new(previous_key, body_bytes, hashlib.sha256).hexdigest()}"
        )
        headers["X-Karma-Response-Signature-V2"] = (
            f"sha256={hmac.new(current_key, body_bytes, hashlib.sha256).hexdigest()}"
        )
    else:
        headers["X-Karma-Response-Signature"] = (
            f"sha256={hmac.new(current_key, body_bytes, hashlib.sha256).hexdigest()}"
        )
    return headers


def signed_json_response(content: Any, status_code: int = 200) -> JSONResponse:
    body_bytes = json.dumps(content, default=str, separators=(",", ":")).encode("utf-8")
    headers = runtime_hmac_headers(body_bytes)
    return JSONResponse(status_code=status_code, content=content, headers=headers)
