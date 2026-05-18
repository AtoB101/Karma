"""Direct Karma public API client (phase 1 trade + payment codes) for OpenManus orchestrators."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx


class KarmaRuntimeClient:
    """
    Call Karma FastAPI ``/v1/*`` with ``X-Karma-Api-Key``.

    Use alongside ``KarmaBffClient`` when OpenManus needs phase-1 trade/payment flows
    without going through BFF integration state.
    """

    def __init__(self, base_url: str, api_key: str, *, timeout_s: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._timeout = timeout_s

    @classmethod
    def from_env(cls) -> "KarmaRuntimeClient":
        base = os.environ.get("KARMA_RUNTIME_URL", "").strip()
        key = os.environ.get("KARMA_API_KEY", "").strip()
        if not base or not key:
            raise RuntimeError("KARMA_RUNTIME_URL and KARMA_API_KEY must be set")
        return cls(base, key)

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json", "X-Karma-Api-Key": self._api_key}
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    async def _post(self, path: str, body: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}{path}",
                content=raw.encode("utf-8"),
                headers=self._headers(idempotency_key=idempotency_key),
            )
            r.raise_for_status()
            return r.json()

    async def _get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base}{path}", headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def trade_launch_signing_preview(
        self,
        *,
        buyer_identity_id: str,
        seller_identity_id: str,
        requirement_text: str,
        idempotency_key: str | None = None,
        amount: float | None = None,
        task_type: str | None = None,
        task_precision: float | None = None,
        chain_anchor_hash: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "requirement_text": requirement_text,
        }
        if amount is not None:
            body["amount"] = amount
        if task_type:
            body["task_type"] = task_type
        if task_precision is not None:
            body["task_precision"] = task_precision
        if chain_anchor_hash:
            body["chain_anchor_hash"] = chain_anchor_hash
        key = idempotency_key or f"manus-preview-{uuid.uuid4().hex}"
        return await self._post("/v1/trade/orders/launch/signing-preview", body, idempotency_key=key)

    async def launch_trade_order(
        self,
        *,
        buyer_identity_id: str,
        seller_identity_id: str,
        requirement_text: str,
        idempotency_key: str | None = None,
        amount: float | None = None,
        task_type: str | None = None,
        task_precision: float | None = None,
        chain_anchor_hash: str | None = None,
        buyer_signature: str = "0xopenmanus_trade_launch",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "requirement_text": requirement_text,
            "buyer_signature": buyer_signature,
        }
        if amount is not None:
            body["amount"] = amount
        if task_type:
            body["task_type"] = task_type
        if task_precision is not None:
            body["task_precision"] = task_precision
        if chain_anchor_hash:
            body["chain_anchor_hash"] = chain_anchor_hash
        key = idempotency_key or f"manus-launch-{uuid.uuid4().hex}"
        return await self._post("/v1/trade/orders/launch", body, idempotency_key=key)

    async def get_trade_order(self, order_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/trade/orders/{order_id}")

    async def create_payment_code(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/v1/payment-codes", body)

    async def get_payment_code(self, voucher_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/payment-codes/{voucher_id}")

    async def get_automation_readiness(
        self,
        *,
        task_id: str,
        role: str = "buyer",
        karma_identity_id: str | None = None,
        for_handoff_confirm: bool = False,
    ) -> dict[str, Any]:
        q = f"?task_id={task_id}&role={role}&for_handoff_confirm={'true' if for_handoff_confirm else 'false'}"
        if karma_identity_id:
            q += f"&karma_identity_id={karma_identity_id}"
        return await self._get(f"/v1/openclaw/automation-readiness{q}")

    async def get_handoff_draft(self, task_id: str, trace_id: str = "") -> dict[str, Any]:
        q = f"?task_id={task_id}"
        if trace_id:
            q += f"&trace_id={trace_id}"
        return await self._get(f"/v1/openclaw/handoff-draft{q}")
