"""MCP (stdio) bridge from OpenClaw (or any MCP host) to Karma public HTTP API."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from karma_openclaw.guard import (
    buyer_confirm_allowed,
    require_valid_handoff,
    require_valid_handoff_for_automation,
    server_attestation_required,
)
from karma_openclaw.handoff import validate_handoff_v1
from karma_openclaw.helpers import (
    build_execution_receipt_skeleton,
    build_mcp_execution_extension,
    manual_authorization_checklist,
    new_client_nonce,
    stable_sha256_hex,
    voucher_eip712_operator_notes,
)
from karma_openclaw.http_client import api_get, api_post
from karma_openclaw.p0_tools import register_p0_tools


def build_app() -> FastMCP:
    mcp = FastMCP(
        "karma-openclaw",
        instructions=(
            "Karma Trust Protocol — OpenClaw MCP (P0+P1). "
            "KARMA_RUNTIME_URL + KARMA_API_KEY; optional KARMA_RUNTIME_KEY for /runtime/*. "
            "Voucher create/accept and Runtime Key mint are MANUAL in Karma Console. "
            "Mutating tools require handoff v1 (handoff_json or KARMA_OPENCLAW_HANDOFF_PATH)."
        ),
    )

    # --- Capacity + bundles ---

    @mcp.tool()
    async def karma_get_capacity(identity_id: str) -> dict[str, Any]:
        """GET /v1/capacity/{identity_id} — USDC capacity snapshot."""
        pid = quote(identity_id, safe="")
        return await api_get(f"/v1/capacity/{pid}")

    @mcp.tool()
    async def karma_lock_usdc(identity_id: str, amount: float) -> dict[str, Any]:
        """POST /v1/capacity/{identity_id}/lock — prefer Console for first lock."""
        pid = quote(identity_id, safe="")
        return await api_post(f"/v1/capacity/{pid}/lock", {"amount": amount})

    @mcp.tool()
    async def karma_get_evidence_bundle(bundle_id: str) -> dict[str, Any]:
        """GET /v1/bundles/{bundle_id}"""
        bid = quote(bundle_id, safe="")
        return await api_get(f"/v1/bundles/{bid}")

    @mcp.tool()
    async def karma_get_evidence_bundle_by_task(task_id: str) -> dict[str, Any]:
        """GET /v1/bundles/task/{task_id}"""
        tid = quote(task_id, safe="")
        return await api_get(f"/v1/bundles/task/{tid}")

    @mcp.tool()
    async def karma_submit_evidence_bundle(bundle_json: str) -> dict[str, Any]:
        """POST /v1/bundles"""
        return await api_post("/v1/bundles", json.loads(bundle_json))

    # --- Manual auth guidance ---

    @mcp.tool()
    def karma_manual_auth_checklist(role: str = "both") -> str:
        """Console steps required before automation (buyer | seller | both)."""
        return manual_authorization_checklist(role)

    @mcp.tool()
    def karma_voucher_eip712_notes() -> str:
        """Operator notes when voucher EIP-712 is enforced."""
        return voucher_eip712_operator_notes()

    @mcp.tool()
    def karma_new_client_nonce(prefix: str = "oc") -> str:
        """Nonce for Runtime Gateway anti-replay."""
        return new_client_nonce(prefix)

    @mcp.tool()
    async def karma_validate_handoff(handoff_json: str) -> dict[str, Any]:
        """Validate handoff v1; live voucher check; optional server attestation."""
        err, normalized = await require_valid_handoff_for_automation(handoff_json)
        if err:
            return err
        ok, errors, _ = validate_handoff_v1(json.loads(handoff_json))
        out: dict[str, Any] = {"ok": ok, "errors": errors, "handoff": normalized}
        vid = normalized.get("voucher_id")
        if ok and vid:
            try:
                row = await api_get(f"/v1/vouchers/{quote(vid, safe='')}")
            except Exception as exc:  # noqa: BLE001
                out["voucher_live_check"] = {"ok": False, "error": str(exc)}
            else:
                status = row.get("status") if isinstance(row, dict) else None
                out["voucher_live_check"] = {"ok": True, "status": status}
                if status != "accepted":
                    out["ok"] = False
                    out["errors"] = list(errors) + [
                        f"live voucher status is {status!r}; seller must accept in Console"
                    ]
        if server_attestation_required():
            out["server_attestation"] = {"ok": True, "required": True}
        return out

    # --- P1 verify / reads ---

    @mcp.tool()
    async def karma_submit_verification(
        bundle_json: str,
        contract_json: str,
        handoff_json: str = "",
    ) -> dict[str, Any]:
        """POST /v1/verify — after handoff + Console authorization."""
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        return await api_post(
            "/v1/verify",
            {"bundle": json.loads(bundle_json), "contract": json.loads(contract_json)},
        )

    @mcp.tool()
    async def karma_list_progress_for_task(task_id: str) -> list[Any]:
        """GET /v1/progress/task/{task_id}"""
        tid = quote(task_id, safe="")
        data = await api_get(f"/v1/progress/task/{tid}")
        return data if isinstance(data, list) else [data]

    @mcp.tool()
    async def karma_confirm_progress(progress_receipt_id: str, handoff_json: str = "") -> dict[str, Any]:
        """POST /v1/progress/{id}/confirm — Console by default."""
        if not buyer_confirm_allowed():
            return {
                "ok": False,
                "error": "progress confirm is Console-only by default",
                "hint": "Set KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM=true after Console approval",
            }
        err, _ = require_valid_handoff(handoff_json or None)
        if err:
            return err
        pid = quote(progress_receipt_id, safe="")
        return await api_post(f"/v1/progress/{pid}/confirm", {})

    @mcp.tool()
    async def karma_list_receipts_for_task(task_id: str) -> list[Any]:
        """GET /v1/receipts/task/{task_id}"""
        tid = quote(task_id, safe="")
        data = await api_get(f"/v1/receipts/task/{tid}")
        return data if isinstance(data, list) else [data]

    @mcp.tool()
    async def karma_get_settlement(task_id: str) -> dict[str, Any]:
        """GET /v1/settlement/{task_id}"""
        tid = quote(task_id, safe="")
        return await api_get(f"/v1/settlement/{tid}")

    @mcp.tool()
    async def karma_get_voucher(voucher_id: str) -> dict[str, Any]:
        """GET /v1/vouchers/{id} — read-only."""
        vid = quote(voucher_id, safe="")
        return await api_get(f"/v1/vouchers/{vid}")

    # --- Receipt builders (local) ---

    @mcp.tool()
    def karma_build_mcp_receipt_extension(
        mcp_server_id: str,
        mcp_tool_name: str,
        tool_call_trace_json: str,
        normalized_result_json: str,
    ) -> dict[str, Any]:
        """Build mcp.* execution receipt extension."""
        trace = json.loads(tool_call_trace_json)
        result = json.loads(normalized_result_json)
        return build_mcp_execution_extension(
            mcp_server_id=mcp_server_id,
            mcp_tool_name=mcp_tool_name,
            tool_call_trace=trace,
            normalized_result=result,
        )

    @mcp.tool()
    def karma_build_execution_receipt_step(
        task_id: str,
        agent_id: str,
        step_index: int,
        tool_name: str,
        input_payload_json: str,
        output_payload_json: str,
        task_type_prefix: str = "mcp",
        mcp_server_id: str = "karma-openclaw",
        mcp_tool_name: str = "",
    ) -> dict[str, Any]:
        """Build unsigned ExecutionReceipt JSON."""
        inp = json.loads(input_payload_json)
        out = json.loads(output_payload_json)
        ext = None
        if task_type_prefix.startswith("mcp"):
            ext = build_mcp_execution_extension(
                mcp_server_id=mcp_server_id,
                mcp_tool_name=mcp_tool_name or tool_name,
                tool_call_trace=inp,
                normalized_result=out,
            )
        return build_execution_receipt_skeleton(
            task_id=task_id,
            agent_id=agent_id,
            step_index=step_index,
            tool_name=tool_name,
            input_hash=stable_sha256_hex(inp),
            output_hash=stable_sha256_hex(out),
            extension=ext,
        )

    register_p0_tools(mcp)
    return mcp


def main() -> None:
    """Entrypoint: ``python -m karma_openclaw`` or ``karma-openclaw-mcp``."""
    build_app().run(transport="stdio")
