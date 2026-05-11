"""HMAC request authentication for integration + webhooks."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated

from fastapi import Header, HTTPException, Request


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_hmac_body(secret: str, timestamp: str, body: bytes, signature_hex: str, *, max_skew_sec: int = 300) -> None:
    if not secret:
        raise HTTPException(503, "BFF_INTEGRATION_SECRET not configured")
    try:
        ts = int(timestamp)
    except ValueError as e:
        raise HTTPException(401, "invalid timestamp") from e
    now = int(time.time())
    if abs(now - ts) > max_skew_sec:
        raise HTTPException(401, "timestamp skew")
    msg = timestamp.encode("utf-8") + b"\n" + body
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not _constant_time_eq(expected.lower(), signature_hex.lower()):
        raise HTTPException(401, "invalid signature")


async def require_integration_hmac(
    request: Request,
    secret: str,
    x_karma_timestamp: Annotated[str | None, Header(alias="X-Karma-Timestamp")] = None,
    x_karma_signature: Annotated[str | None, Header(alias="X-Karma-Signature")] = None,
) -> bytes:
    if x_karma_timestamp is None or x_karma_signature is None:
        raise HTTPException(401, "missing X-Karma-Timestamp or X-Karma-Signature")
    body = await request.body()
    verify_hmac_body(secret, x_karma_timestamp, body, x_karma_signature)
    return body
