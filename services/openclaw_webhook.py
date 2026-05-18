"""Outbound OpenClaw handoff webhooks (HMAC-signed, best-effort async)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_EVENT_RING: deque[dict[str, Any]] = deque(maxlen=200)


def _ring_enabled() -> bool:
    return bool(getattr(settings, "openclaw_webhook_store_events", False))


def list_stored_events(*, task_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """In-process ring buffer for dev / single-worker polling (not durable)."""
    items = list(_EVENT_RING)
    if task_id:
        items = [e for e in items if (e.get("payload") or {}).get("task_id") == task_id]
    return items[-limit:]


def build_envelope(event_type: str, payload: dict[str, Any], *, trace_id: str = "") -> dict[str, Any]:
    return {
        "event_version": "1",
        "event_type": event_type,
        "emitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trace_id": trace_id or str(payload.get("trace_id") or ""),
        "payload": payload,
    }


def _sign_body(body_bytes: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _post_webhook(envelope: dict[str, Any]) -> None:
    url = (settings.openclaw_webhook_url or "").strip()
    if not url:
        return
    secret = (settings.openclaw_webhook_secret or "").strip()
    body_bytes = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Karma-Signature"] = _sign_body(body_bytes, secret)
    max_retries = max(1, int(getattr(settings, "openclaw_webhook_max_retries", 3) or 3))
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, content=body_bytes, headers=headers)
                resp.raise_for_status()
            return
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < max_retries:
                await asyncio.sleep(min(8.0, 2.0**attempt))
    logger.warning(
        "openclaw webhook delivery failed after retries",
        exc_info=last_exc,
        extra={"event_type": envelope.get("event_type"), "attempts": max_retries},
    )


def emit_openclaw_event(event_type: str, payload: dict[str, Any], *, trace_id: str = "") -> None:
    """
    Fire-and-forget webhook + optional in-process ring buffer.

    Never raises to callers — automation must not depend on webhook delivery.
    """
    envelope = build_envelope(event_type, payload, trace_id=trace_id)
    if _ring_enabled():
        _EVENT_RING.append(envelope)
    url = (settings.openclaw_webhook_url or "").strip()
    if not url and not _ring_enabled():
        return
    if url:

        async def _runner() -> None:
            await _post_webhook(envelope)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_runner())
        except RuntimeError:
            asyncio.run(_post_webhook(envelope))
