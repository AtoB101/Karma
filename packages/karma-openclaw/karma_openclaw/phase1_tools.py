"""Phase 1 — payment codes, trade launch, voucher events (OpenClaw MCP)."""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from karma_openclaw.guard import require_valid_handoff_for_automation
from karma_openclaw.helpers import stable_sha256_hex
from karma_openclaw.http_client import api_get, api_post, api_put


def build_payment_code_request(
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount: float,
    task_type: str,
    task_description: str,
    bill_credit_amount: float | None = None,
    task_precision: float | None = None,
    payment_mode: str = "preauth",
    chain_anchor_hash: str | None = None,
    buyer_signature: str = "0xopenclaw_phase1_sig",
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Minimal body for POST /v1/payment-codes."""
    desc_hash = stable_sha256_hex(task_description)
    progress_spec = {"source": "karma-openclaw", "task_type": task_type}
    body: dict[str, Any] = {
        "buyer_identity_id": buyer_identity_id,
        "seller_identity_id": seller_identity_id,
        "amount": amount,
        "currency": "USDC",
        "bill_credit_amount": bill_credit_amount if bill_credit_amount is not None else amount,
        "task_type": task_type,
        "task_precision": task_precision,
        "task_description_hash": desc_hash,
        "progress_rule_hash": stable_sha256_hex(progress_spec),
        "evidence_requirement_hash": stable_sha256_hex({"task_description_hash": desc_hash}),
        "buyer_signature": buyer_signature,
        "nonce": secrets.token_hex(16),
        "payment_mode": payment_mode,
        "progress_rule_spec": progress_spec,
    }
    if task_precision is not None:
        body["task_precision"] = task_precision
    if chain_anchor_hash:
        body["chain_anchor_hash"] = chain_anchor_hash
    if ttl_seconds is not None:
        body["ttl_seconds"] = ttl_seconds
    return body


def register_phase1_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def karma_create_payment_code(payment_code_json: str) -> dict[str, Any]:
        """
        POST /v1/payment-codes — buyer creates timed payment code (preauth or manual).

        Pass full JSON or use karma_build_payment_code_request then POST.
        Requires buyer ``KARMA_API_KEY``.
        """
        return await api_post("/v1/payment-codes", json.loads(payment_code_json))

    @mcp.tool()
    def karma_build_payment_code_request(
        buyer_identity_id: str,
        seller_identity_id: str,
        amount: float,
        task_type: str,
        task_description: str,
        payment_mode: str = "preauth",
        task_precision: float | None = None,
        chain_anchor_hash: str = "",
    ) -> dict[str, Any]:
        """Build JSON body for karma_create_payment_code."""
        return build_payment_code_request(
            buyer_identity_id=buyer_identity_id,
            seller_identity_id=seller_identity_id,
            amount=amount,
            task_type=task_type,
            task_description=task_description,
            task_precision=task_precision,
            payment_mode=payment_mode,
            chain_anchor_hash=chain_anchor_hash.strip() or None,
        )

    @mcp.tool()
    async def karma_get_payment_code(voucher_id: str) -> dict[str, Any]:
        """GET /v1/payment-codes/{voucher_id} — payment_code_v1 payload + voucher status."""
        vid = quote(voucher_id, safe="")
        return await api_get(f"/v1/payment-codes/{vid}")

    @mcp.tool()
    async def karma_accept_payment_code(voucher_id: str, seller_identity_id: str) -> dict[str, Any]:
        """POST /v1/payment-codes/{id}/accept — traditional seller manual accept."""
        vid = quote(voucher_id, safe="")
        return await api_post(f"/v1/payment-codes/{vid}/accept", {"seller_identity_id": seller_identity_id})

    @mcp.tool()
    async def karma_reject_payment_code(
        voucher_id: str,
        seller_identity_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """POST /v1/payment-codes/{id}/reject."""
        vid = quote(voucher_id, safe="")
        return await api_post(
            f"/v1/payment-codes/{vid}/reject",
            {"seller_identity_id": seller_identity_id, "reason": reason},
        )

    @mcp.tool()
    async def karma_trade_launch_signing_preview(
        buyer_identity_id: str,
        seller_identity_id: str,
        requirement_text: str,
        idempotency_key: str = "",
        amount: float | None = None,
        task_precision: float | None = None,
        task_type: str = "",
        chain_anchor_hash: str = "",
    ) -> dict[str, Any]:
        """POST /v1/trade/orders/launch/signing-preview — EIP-712 typed data for wallet signing."""
        body: dict[str, Any] = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "requirement_text": requirement_text,
        }
        if amount is not None:
            body["amount"] = amount
        if task_precision is not None:
            body["task_precision"] = task_precision
        if task_type.strip():
            body["task_type"] = task_type.strip()
        if chain_anchor_hash.strip():
            body["chain_anchor_hash"] = chain_anchor_hash.strip()
        key = idempotency_key.strip() or f"oc-preview-{uuid.uuid4().hex}"
        return await api_post("/v1/trade/orders/launch/signing-preview", body, idempotency_key=key)

    @mcp.tool()
    async def karma_trade_launch_sign_with_backend(
        buyer_identity_id: str,
        seller_identity_id: str,
        requirement_text: str,
        idempotency_key: str = "",
        amount: float | None = None,
        task_precision: float | None = None,
        task_type: str = "",
        chain_anchor_hash: str = "",
    ) -> dict[str, Any]:
        """POST /v1/trade/orders/launch/sign-with-backend — dev only when KARMA_SIGNING_BACKEND=local|env."""
        body: dict[str, Any] = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "requirement_text": requirement_text,
        }
        if amount is not None:
            body["amount"] = amount
        if task_precision is not None:
            body["task_precision"] = task_precision
        if task_type.strip():
            body["task_type"] = task_type.strip()
        if chain_anchor_hash.strip():
            body["chain_anchor_hash"] = chain_anchor_hash.strip()
        key = idempotency_key.strip() or f"oc-sign-{uuid.uuid4().hex}"
        return await api_post("/v1/trade/orders/launch/sign-with-backend", body, idempotency_key=key)

    @mcp.tool()
    async def karma_launch_trade_order(
        buyer_identity_id: str,
        seller_identity_id: str,
        requirement_text: str,
        idempotency_key: str = "",
        amount: float | None = None,
        task_precision: float | None = None,
        task_type: str = "",
        chain_anchor_hash: str = "",
        buyer_signature: str = "0xopenclaw_trade_launch",
    ) -> dict[str, Any]:
        """
        POST /v1/trade/orders/launch — full preauth pipeline (both parties preconfigured).

        Always pass a unique ``idempotency_key`` per logical order (required in production).
        """
        body: dict[str, Any] = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "requirement_text": requirement_text,
            "buyer_signature": buyer_signature,
        }
        if amount is not None:
            body["amount"] = amount
        if task_precision is not None:
            body["task_precision"] = task_precision
        if task_type.strip():
            body["task_type"] = task_type.strip()
        if chain_anchor_hash.strip():
            body["chain_anchor_hash"] = chain_anchor_hash.strip()
        key = idempotency_key.strip() or f"oc-launch-{uuid.uuid4().hex}"
        return await api_post("/v1/trade/orders/launch", body, idempotency_key=key)

    @mcp.tool()
    async def karma_get_trade_order(order_id: str) -> dict[str, Any]:
        """GET /v1/trade/orders/{order_id}."""
        oid = quote(order_id, safe="")
        return await api_get(f"/v1/trade/orders/{oid}")

    @mcp.tool()
    async def karma_list_voucher_events(voucher_id: str, identity_id: str) -> dict[str, Any]:
        """GET /v1/vouchers/{id}/events?identity_id=."""
        vid = quote(voucher_id, safe="")
        iid = quote(identity_id, safe="")
        return await api_get(f"/v1/vouchers/{vid}/events?identity_id={iid}")

    @mcp.tool()
    async def karma_get_handoff_draft(task_id: str, trace_id: str = "") -> dict[str, Any]:
        """GET /v1/openclaw/handoff-draft — export handoff v1 after Console steps."""
        tid = quote(task_id, safe="")
        params = f"task_id={tid}"
        if trace_id.strip():
            params += f"&trace_id={quote(trace_id.strip(), safe='')}"
        return await api_get(f"/v1/openclaw/handoff-draft?{params}")

    @mcp.tool()
    async def karma_confirm_handoff(
        task_id: str,
        karma_identity_id: str,
        role: str = "buyer",
        trace_id: str = "",
        handoff_json: str = "",
    ) -> dict[str, Any]:
        """
        POST /v1/openclaw/handoff-confirm — server attestation after readiness.

        Call karma_check_automation_readiness with for_handoff_confirm first.
        """
        body: dict[str, Any] = {
            "task_id": task_id,
            "karma_identity_id": karma_identity_id,
            "role": role,
            "trace_id": trace_id,
        }
        if handoff_json.strip():
            body["handoff"] = json.loads(handoff_json)
        return await api_post("/v1/openclaw/handoff-confirm", body)

    @mcp.tool()
    async def karma_get_automation_policy(identity_id: str) -> dict[str, Any]:
        """GET /v1/identities/{id}/automation-policy."""
        iid = quote(identity_id, safe="")
        return await api_get(f"/v1/identities/{iid}/automation-policy")

    @mcp.tool()
    async def karma_save_automation_policy(identity_id: str, policy_json: str) -> dict[str, Any]:
        """PUT /v1/identities/{id}/automation-policy — preauth / auto_execute_pipeline etc."""
        iid = quote(identity_id, safe="")
        return await api_put(f"/v1/identities/{iid}/automation-policy", json.loads(policy_json))

    @mcp.tool()
    async def karma_continue_after_trade_launch(
        task_id: str,
        handoff_json: str,
        role: str = "seller",
    ) -> dict[str, Any]:
        """
        After karma_launch_trade_order returns execution_started: validate handoff and suggest next MCP step.

        Does not mutate — returns validation + karma_automation_status hint payload.
        """
        err, normalized = await require_valid_handoff_for_automation(handoff_json or None)
        if err:
            return {"ok": False, "error": err, "hint": "GET karma_get_handoff_draft and complete handoff-confirm"}
        from karma_openclaw.orchestration import suggest_next_steps

        settlement = await api_get(f"/v1/settlement/{quote(task_id, safe='')}")
        status = settlement.get("status") if isinstance(settlement, dict) else "unknown"
        vid = normalized.get("voucher_id") or ""
        voucher_status = ""
        if vid:
            v = await api_get(f"/v1/vouchers/{quote(vid, safe='')}")
            voucher_status = v.get("status", "") if isinstance(v, dict) else ""
        hints = suggest_next_steps(
            role=role,
            settlement_status=str(status),
            voucher_status=str(voucher_status),
            handoff_ok=True,
        )
        return {
            "ok": True,
            "task_id": task_id,
            "settlement_status": status,
            "voucher_status": voucher_status,
            "next_steps": hints,
        }
