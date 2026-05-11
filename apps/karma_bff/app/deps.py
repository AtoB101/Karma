"""FastAPI dependencies."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import Header, HTTPException, Request

from apps.karma_bff.app import auth, config


async def read_hmac_json(
    request: Request,
    x_karma_timestamp: Annotated[str | None, Header(alias="X-Karma-Timestamp")] = None,
    x_karma_signature: Annotated[str | None, Header(alias="X-Karma-Signature")] = None,
) -> dict[str, Any]:
    secret = config.integration_secret()
    body_bytes = await request.body()
    if not x_karma_timestamp or not x_karma_signature:
        raise HTTPException(401, "missing X-Karma-Timestamp or X-Karma-Signature")
    auth.verify_hmac_body(secret, x_karma_timestamp, body_bytes, x_karma_signature)
    try:
        return json.loads(body_bytes.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, "invalid json body") from e


async def read_webhook_json(
    request: Request,
    x_karma_timestamp: Annotated[str | None, Header(alias="X-Karma-Timestamp")] = None,
    x_karma_signature: Annotated[str | None, Header(alias="X-Karma-Signature")] = None,
) -> dict[str, Any]:
    secret = config.webhook_secret()
    body_bytes = await request.body()
    if not x_karma_timestamp or not x_karma_signature:
        raise HTTPException(401, "missing X-Karma-Timestamp or X-Karma-Signature")
    auth.verify_hmac_body(secret, x_karma_timestamp, body_bytes, x_karma_signature)
    try:
        return json.loads(body_bytes.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, "invalid json body") from e
