"""Async HTTP client for Karma BFF ``/v1/integration`` + public status."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx

from karma_openmanus.hmac_auth import hmac_hex_signature


def _now_ts() -> str:
    return str(int(time.time()))


class KarmaBffClient:
    """
    Call Karma BFF routes defined in ``openmanus-karma-tools/tools.json``.

    Parameters
    ----------
    base_url:
        ``KARMA_BFF_URL`` — no trailing slash.
    secret:
        ``BFF_INTEGRATION_SECRET``.
    """

    def __init__(self, base_url: str, secret: str, *, timeout_s: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._secret = secret
        self._timeout = timeout_s

    @classmethod
    def from_env(cls) -> "KarmaBffClient":
        base = os.environ.get("KARMA_BFF_URL", "").strip()
        secret = os.environ.get("BFF_INTEGRATION_SECRET", "").strip()
        if not base or not secret:
            raise RuntimeError("KARMA_BFF_URL and BFF_INTEGRATION_SECRET must be set")
        return cls(base, secret)

    def _hmac_headers(self, timestamp: str, raw_body: str) -> dict[str, str]:
        sig = hmac_hex_signature(self._secret, timestamp, raw_body)
        return {
            "X-Karma-Timestamp": timestamp,
            "X-Karma-Signature": sig,
            "Content-Type": "application/json",
        }

    async def _post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        ts = _now_ts()
        headers = self._hmac_headers(ts, raw)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base}{path}", content=raw.encode("utf-8"), headers=headers)
            r.raise_for_status()
            return r.json()

    async def _get_hmac(self, path: str) -> dict[str, Any]:
        ts = _now_ts()
        raw_body = ""
        headers = {
            "X-Karma-Timestamp": ts,
            "X-Karma-Signature": hmac_hex_signature(self._secret, ts, raw_body),
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base}{path}", headers=headers)
            r.raise_for_status()
            return r.json()

    async def create_task(self, body: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
        key = idempotency_key or str(uuid.uuid4())
        return await self._post_json("/v1/integration/tasks", body, idempotency_key=key)

    async def submit_order_snapshot(self, trace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json(
            f"/v1/integration/tasks/{trace_id}/order-snapshot",
            body,
            idempotency_key=f"order-{trace_id}",
        )

    async def request_buyer_lock_page(self, trace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json(
            f"/v1/integration/tasks/{trace_id}/buyer-lock-intent",
            body,
            idempotency_key=f"lock-intent-{trace_id}",
        )

    async def append_execution_receipt(self, trace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json(
            f"/v1/integration/tasks/{trace_id}/receipts",
            body,
            idempotency_key=f"rcpt-{trace_id}-{uuid.uuid4().hex[:12]}",
        )

    async def build_evidence_and_settlement_plan(self, trace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json(
            f"/v1/integration/tasks/{trace_id}/evidence/build",
            body,
            idempotency_key=f"evidence-{trace_id}",
        )

    async def get_task_status(self, trace_id: str) -> dict[str, Any]:
        return await self._get_hmac(f"/v1/integration/tasks/{trace_id}/status")

    async def get_buyer_public_status(self, trace_id: str) -> dict[str, Any]:
        """No HMAC — read-only public UI endpoint."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base}/public/status/{trace_id}")
            r.raise_for_status()
            return r.json()
