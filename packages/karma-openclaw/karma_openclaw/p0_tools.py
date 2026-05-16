"""P0 MCP tools — settlement execution path (post-Console authorization)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from karma_openclaw.guard import (
    block_response,
    buyer_accept_allowed,
    require_valid_handoff,
    setup_mutations_allowed,
)
from karma_openclaw.http_client import api_get, api_post, runtime_get, runtime_key, runtime_post
from karma_openclaw.orchestration import suggest_next_steps


def register_p0_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def karma_verify_voucher(
        voucher_id: str,
        seller_identity_id: str,
        handoff_json: str = "",
        expected_amount: float | None = None,
    ) -> dict[str, Any]:
        """
        POST /v1/vouchers/{id}/verify — read-only check (does NOT accept).

        Use after seller accepted voucher in Console; requires valid handoff.
        """
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        body: dict[str, Any] = {"seller_identity_id": seller_identity_id}
        if expected_amount is not None:
            body["expected_amount"] = expected_amount
        vid = quote(voucher_id, safe="")
        return await api_post(f"/v1/vouchers/{vid}/verify", body)

    @mcp.tool()
    async def karma_create_contract(contract_json: str, handoff_json: str = "") -> dict[str, Any]:
        """
        POST /v1/contracts — disabled unless KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS=true (prefer Console).
        """
        if not setup_mutations_allowed():
            return block_response(
                "setup_mutations_disabled",
                hint="Create contract in Karma Console, or set KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS=true",
            )
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        return await api_post("/v1/contracts", json.loads(contract_json))

    @mcp.tool()
    async def karma_create_settlement(settlement_json: str, handoff_json: str = "") -> dict[str, Any]:
        """
        POST /v1/settlement/create — disabled unless KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS=true (prefer Console).
        """
        if not setup_mutations_allowed():
            return block_response(
                "setup_mutations_disabled",
                hint="Create settlement in Console after voucher accept, or set ALLOW_SETUP_MUTATIONS",
            )
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        return await api_post("/v1/settlement/create", json.loads(settlement_json))

    @mcp.tool()
    async def karma_get_contract(task_id: str) -> dict[str, Any]:
        """GET /v1/contracts/{task_id}"""
        tid = quote(task_id, safe="")
        return await api_get(f"/v1/contracts/{tid}")

    @mcp.tool()
    async def karma_settlement_pending(task_id: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /v1/settlement/{task_id}/pending"""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        tid = quote(task_id, safe="")
        return await api_post(f"/v1/settlement/{tid}/pending", {})

    @mcp.tool()
    async def karma_settlement_lock(
        task_id: str,
        worker_agent_id: str,
        handoff_json: str = "",
    ) -> dict[str, Any]:
        """POST /v1/settlement/{task_id}/lock — seller binds as worker."""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        tid = quote(task_id, safe="")
        return await api_post(f"/v1/settlement/{tid}/lock", {"worker_agent_id": worker_agent_id})

    @mcp.tool()
    async def karma_settlement_start(task_id: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /v1/settlement/{task_id}/start"""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        tid = quote(task_id, safe="")
        return await api_post(f"/v1/settlement/{tid}/start", {})

    @mcp.tool()
    async def karma_settlement_submit_delivery(task_id: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /v1/settlement/{task_id}/submit — mark delivered."""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        tid = quote(task_id, safe="")
        return await api_post(f"/v1/settlement/{tid}/submit", {})

    @mcp.tool()
    async def karma_settlement_buyer_accept(task_id: str, handoff_json: str = "") -> dict[str, Any]:
        """
        POST /v1/settlement/{task_id}/buyer-accept — disabled by default (Console).

        Set KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT=true only after buyer confirms in Console UI.
        """
        if not buyer_accept_allowed():
            return block_response(
                "buyer_accept_console_only",
                hint="Complete buyer-accept in Console or set KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT=true",
            )
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        tid = quote(task_id, safe="")
        return await api_post(f"/v1/settlement/{tid}/buyer-accept", {})

    @mcp.tool()
    async def karma_submit_execution_receipt(receipt_json: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /v1/receipts — signed execution receipt from seller/worker."""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        return await api_post("/v1/receipts", json.loads(receipt_json))

    @mcp.tool()
    async def karma_submit_progress(progress_json: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /v1/progress — seller progress receipt."""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        return await api_post("/v1/progress", json.loads(progress_json))

    # --- Runtime Gateway (optional KARMA_RUNTIME_KEY) ---

    @mcp.tool()
    async def karma_runtime_submit_receipt(receipt_json: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /runtime/submit-receipt — requires KARMA_RUNTIME_KEY (seller)."""
        if not runtime_key():
            return block_response("runtime_key_missing", hint="Set KARMA_RUNTIME_KEY for seller Claw process")
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        return await runtime_post("/runtime/submit-receipt", json.loads(receipt_json))

    @mcp.tool()
    async def karma_runtime_request_settlement(
        task_id: str,
        kind: str,
        client_nonce: str,
        handoff_json: str = "",
        settled_value_percent: float | None = None,
    ) -> dict[str, Any]:
        """
        POST /runtime/request-settlement — kind: submit_delivery | buyer_accept | partial.

        buyer_accept requires KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT=true.
        """
        if not runtime_key():
            return block_response("runtime_key_missing", hint="Set KARMA_RUNTIME_KEY")
        if kind == "buyer_accept" and not buyer_accept_allowed():
            return block_response("buyer_accept_console_only", hint="Use Console or ALLOW_BUYER_ACCEPT")
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        body: dict[str, Any] = {
            "task_id": task_id,
            "kind": kind,
            "client_nonce": client_nonce,
        }
        if settled_value_percent is not None:
            body["settled_value_percent"] = settled_value_percent
        return await runtime_post("/runtime/request-settlement", body)

    @mcp.tool()
    async def karma_runtime_task_status(task_id: str) -> dict[str, Any]:
        """GET /runtime/task-status/{task_id} — requires KARMA_RUNTIME_KEY."""
        if not runtime_key():
            return block_response("runtime_key_missing", hint="Set KARMA_RUNTIME_KEY")
        tid = quote(task_id, safe="")
        return await runtime_get(f"/runtime/task-status/{tid}")

    @mcp.tool()
    async def karma_runtime_get_capacity() -> dict[str, Any]:
        """GET /runtime/capacity — requires KARMA_RUNTIME_KEY."""
        if not runtime_key():
            return block_response("runtime_key_missing", hint="Set KARMA_RUNTIME_KEY")
        return await runtime_get("/runtime/capacity")

    @mcp.tool()
    async def karma_runtime_check_voucher(
        voucher_id: str,
        client_nonce: str,
        handoff_json: str = "",
        expected_amount: float | None = None,
    ) -> dict[str, Any]:
        """POST /runtime/check-voucher — seller verify only (not accept); needs verify_voucher permission."""
        if not runtime_key():
            return block_response("runtime_key_missing", hint="Set KARMA_RUNTIME_KEY")
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        body: dict[str, Any] = {"voucher_id": voucher_id, "client_nonce": client_nonce}
        if expected_amount is not None:
            body["expected_amount"] = expected_amount
        return await runtime_post("/runtime/check-voucher", body)

    @mcp.tool()
    async def karma_poll_handoff_events(task_id: str = "", limit: int = 20) -> dict[str, Any]:
        """
        GET /v1/openclaw/handoff-events — recent voucher/settlement events (requires OPENCLAW_WEBHOOK_STORE_EVENTS on API).
        """
        q = f"?limit={int(limit)}"
        if task_id.strip():
            q = f"?task_id={quote(task_id.strip(), safe='')}&limit={int(limit)}"
        return await api_get(f"/v1/openclaw/handoff-events{q}")

    @mcp.tool()
    async def karma_automation_status(
        task_id: str,
        role: str,
        handoff_json: str = "",
        voucher_id: str = "",
    ) -> dict[str, Any]:
        """
        Aggregate handoff + settlement + optional voucher; return suggested next MCP/Console step.
        """
        err, norm = require_valid_handoff(handoff_json or None)
        handoff_ok = err is None
        settlement = await api_get(f"/v1/settlement/{quote(task_id, safe='')}")
        v_id = voucher_id.strip() or (norm.get("voucher_id") if handoff_ok else "") or ""
        v_status = None
        if v_id:
            try:
                vrow = await api_get(f"/v1/vouchers/{quote(v_id, safe='')}")
                v_status = vrow.get("status") if isinstance(vrow, dict) else None
            except Exception as exc:  # noqa: BLE001
                v_status = f"error:{exc}"
        st = settlement.get("status") if isinstance(settlement, dict) else None
        if hasattr(st, "value"):
            st = st.value
        plan = suggest_next_steps(
            role=role,
            settlement_status=str(st) if st is not None else None,
            voucher_status=str(v_status) if v_status is not None else None,
            handoff_ok=handoff_ok,
        )
        return {
            "handoff_errors": err.get("errors") if err else [],
            "settlement": settlement,
            "voucher_status": v_status,
            "plan": plan,
        }
