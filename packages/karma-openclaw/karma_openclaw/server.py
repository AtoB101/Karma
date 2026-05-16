"""MCP (stdio) bridge from OpenClaw (or any MCP host) to Karma public HTTP API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

from karma_openclaw.handoff import validate_handoff_v1
from karma_openclaw.helpers import (
    build_execution_receipt_skeleton,
    build_mcp_execution_extension,
    manual_authorization_checklist,
    new_client_nonce,
    stable_sha256_hex,
    voucher_eip712_operator_notes,
)


def _runtime_url() -> str:
    u = os.environ.get("KARMA_RUNTIME_URL", "http://localhost:8000").strip().rstrip("/")
    return u


def _api_key() -> str | None:
    k = os.environ.get("KARMA_API_KEY", "").strip()
    return k or None


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        h["X-Karma-Api-Key"] = key
    return h


def _buyer_confirm_allowed() -> bool:
    return os.environ.get("KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(f"{_runtime_url()}{path}", headers=_headers())
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r.text


async def _post_json(path: str, body: Any) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{_runtime_url()}{path}",
            headers=_headers(),
            content=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        )
        r.raise_for_status()
        return r.json()


def build_app() -> FastMCP:
    mcp = FastMCP(
        "karma-openclaw",
        instructions=(
            "Karma Trust Protocol — OpenClaw MCP (P1). Set KARMA_RUNTIME_URL and KARMA_API_KEY. "
            "Authorization (voucher create/accept, Runtime Key mint) is MANUAL in Karma Console — "
            "use karma_manual_auth_checklist and karma_validate_handoff before automated verify/delivery."
        ),
    )

    # --- Existing v0.1 tools ---

    @mcp.tool()
    async def karma_get_capacity(identity_id: str) -> dict[str, Any]:
        """GET /v1/capacity/{identity_id} — USDC capacity snapshot."""
        pid = quote(identity_id, safe="")
        return await _get(f"/v1/capacity/{pid}")

    @mcp.tool()
    async def karma_lock_usdc(identity_id: str, amount: float) -> dict[str, Any]:
        """POST /v1/capacity/{identity_id}/lock — reserve capacity (JSON {amount}). Prefer Console for first lock."""
        pid = quote(identity_id, safe="")
        return await _post_json(f"/v1/capacity/{pid}/lock", {"amount": amount})

    @mcp.tool()
    async def karma_get_evidence_bundle(bundle_id: str) -> dict[str, Any]:
        """GET /v1/bundles/{bundle_id} — fetch evidence bundle by id."""
        bid = quote(bundle_id, safe="")
        return await _get(f"/v1/bundles/{bid}")

    @mcp.tool()
    async def karma_get_evidence_bundle_by_task(task_id: str) -> dict[str, Any]:
        """GET /v1/bundles/task/{task_id} — fetch bundle for a task."""
        tid = quote(task_id, safe="")
        return await _get(f"/v1/bundles/task/{tid}")

    @mcp.tool()
    async def karma_submit_evidence_bundle(bundle_json: str) -> dict[str, Any]:
        """POST /v1/bundles — body is full EvidenceBundle JSON string."""
        body = json.loads(bundle_json)
        return await _post_json("/v1/bundles", body)

    # --- P1: manual auth guidance (no HTTP) ---

    @mcp.tool()
    def karma_manual_auth_checklist(role: str = "both") -> str:
        """
        Return what the human operator must complete in Karma Console before Claw automation.
        role: buyer | seller | both
        """
        return manual_authorization_checklist(role)

    @mcp.tool()
    def karma_voucher_eip712_notes() -> str:
        """Operator notes when voucher buyer EIP-712 signatures are required."""
        return voucher_eip712_operator_notes()

    @mcp.tool()
    def karma_new_client_nonce(prefix: str = "oc") -> str:
        """Generate client_nonce for Runtime Gateway anti-replay (if using /runtime/* from a sidecar)."""
        return new_client_nonce(prefix)

    @mcp.tool()
    async def karma_validate_handoff(handoff_json: str) -> dict[str, Any]:
        """
        Validate OpenClaw handoff v1 JSON (local rules). Optionally cross-check voucher on API when configured.

        Does not perform voucher create/accept — those remain Console-only.
        """
        payload = json.loads(handoff_json)
        ok, errors, normalized = validate_handoff_v1(payload)
        out: dict[str, Any] = {"ok": ok, "errors": errors, "handoff": normalized}
        vid = normalized.get("voucher_id")
        if ok and vid and _api_key():
            try:
                row = await _get(f"/v1/vouchers/{quote(vid, safe='')}")  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001 — surface to operator
                out["voucher_live_check"] = {"ok": False, "error": str(exc)}
            else:
                status = row.get("status") if isinstance(row, dict) else None
                out["voucher_live_check"] = {"ok": True, "status": status}
                if status != "accepted":
                    out["ok"] = False
                    out["errors"] = list(errors) + [
                        f"live voucher status is {status!r}; seller must accept in Console before automation"
                    ]
        return out

    # --- P1: verify / progress / delivery reads ---

    @mcp.tool()
    async def karma_submit_verification(bundle_json: str, contract_json: str) -> dict[str, Any]:
        """
        POST /v1/verify — structural verification (bundle + task contract).

        Run only after handoff validates and manual authorization steps are done in Console.
        """
        body = {
            "bundle": json.loads(bundle_json),
            "contract": json.loads(contract_json),
        }
        return await _post_json("/v1/verify", body)

    @mcp.tool()
    async def karma_list_progress_for_task(task_id: str) -> list[Any]:
        """GET /v1/progress/task/{task_id} — list progress receipts."""
        tid = quote(task_id, safe="")
        data = await _get(f"/v1/progress/task/{tid}")
        return data if isinstance(data, list) else [data]

    @mcp.tool()
    async def karma_confirm_progress(progress_receipt_id: str) -> dict[str, Any]:
        """
        POST /v1/progress/{id}/confirm — buyer confirms progress.

        Disabled by default: set KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM=true only if buyer already approved in Console.
        Prefer confirming progress in Karma Console UI.
        """
        if not _buyer_confirm_allowed():
            return {
                "ok": False,
                "error": "progress confirm is Console-only by default",
                "hint": "Confirm in Karma Console, or set KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM=true after explicit buyer approval",
            }
        pid = quote(progress_receipt_id, safe="")
        return await _post_json(f"/v1/progress/{pid}/confirm", {})

    @mcp.tool()
    async def karma_list_receipts_for_task(task_id: str) -> list[Any]:
        """GET /v1/receipts/task/{task_id} — execution receipts for verify/delivery context."""
        tid = quote(task_id, safe="")
        data = await _get(f"/v1/receipts/task/{tid}")
        return data if isinstance(data, list) else [data]

    @mcp.tool()
    async def karma_get_settlement(task_id: str) -> dict[str, Any]:
        """GET /v1/settlement/{task_id} — settlement state for delivery alignment."""
        tid = quote(task_id, safe="")
        return await _get(f"/v1/settlement/{tid}")

    @mcp.tool()
    async def karma_get_voucher(voucher_id: str) -> dict[str, Any]:
        """
        GET /v1/vouchers/{voucher_id} — read-only voucher snapshot.

        No create/accept/verify tools: seller accept and buyer create stay on Console.
        """
        vid = quote(voucher_id, safe="")
        return await _get(f"/v1/vouchers/{vid}")

    # --- P1: receipt builder helpers (local, unsigned) ---

    @mcp.tool()
    def karma_build_mcp_receipt_extension(
        mcp_server_id: str,
        mcp_tool_name: str,
        tool_call_trace_json: str,
        normalized_result_json: str,
    ) -> dict[str, Any]:
        """Build mcp execution receipt extension dict from JSON trace/result blobs."""
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
        """
        Build unsigned ExecutionReceipt JSON for POST /v1/receipts or /runtime/submit-receipt.

        Hashes payloads with stable SHA-256. For task_type mcp.*, includes typed extension.
        """
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

    return mcp


def main() -> None:
    """Entrypoint: ``python -m karma_openclaw`` or ``karma-openclaw-mcp``."""
    build_app().run(transport="stdio")
