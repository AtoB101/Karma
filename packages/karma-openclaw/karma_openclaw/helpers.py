"""Agent-side helpers for OpenClaw (no wallet keys; authorization stays on Console)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


def new_client_nonce(prefix: str = "oc") -> str:
    """Fresh nonce for Runtime Gateway anti-replay (request-voucher / request-settlement)."""
    return f"{prefix}-{uuid.uuid4().hex}"


def stable_sha256_hex(value: Any) -> str:
    """Canonical JSON SHA-256 (sorted keys) — aligns with Karma hook_layer hashing style."""
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_mcp_execution_extension(
    *,
    mcp_server_id: str,
    mcp_tool_name: str,
    tool_call_trace: Any,
    normalized_result: Any,
) -> dict[str, Any]:
    """Typed extension payload for task_type ``mcp.*`` execution receipts."""
    return {
        "kind": "mcp",
        "mcp_server_id": mcp_server_id,
        "mcp_tool_name": mcp_tool_name,
        "trace_hash": stable_sha256_hex(tool_call_trace),
        "result_hash": stable_sha256_hex(normalized_result),
    }


def apply_openclaw_dev_delivery_signatures(body: dict[str, Any]) -> dict[str, Any]:
    """
    Fill placeholder delivery signatures for local Phase 1 when the server relaxes checks.

    Safe to call client-side: production with EIP-712 on still requires real Ed25519 receipts.
    """
    out = dict(body)
    if not (out.get("signature") or "").strip():
        out["signature"] = "0xopenclaw_execution_receipt_dev"
    if not (out.get("seller_signature") or "").strip():
        out["seller_signature"] = "0xopenclaw_progress_dev"
    return out


def build_execution_receipt_skeleton(
    *,
    task_id: str,
    agent_id: str,
    step_index: int,
    tool_name: str,
    input_hash: str,
    output_hash: str,
    duration_ms: int = 1,
    status: str = "success",
    extension: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build unsigned ExecutionReceipt JSON (signature filled by Karma API or Runtime submit-receipt).

    ``input_hash`` / ``output_hash`` should be 64-char hex digests (see stable_sha256_hex).
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    body: dict[str, Any] = {
        "receipt_id": f"rcpt-{uuid.uuid4().hex}",
        "task_id": task_id,
        "agent_id": agent_id,
        "step_index": step_index,
        "tool_name": tool_name,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "started_at": now.isoformat().replace("+00:00", "Z"),
        "ended_at": now.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration_ms,
        "status": status,
        "signature": None,
    }
    if extension is not None:
        body["extension"] = extension
    return body


def manual_authorization_checklist(role: str) -> str:
    """
    Human-readable checklist: what must be done in Karma Console before Claw automation.

    role: ``buyer`` | ``seller`` | ``both``
    """
    role = role.strip().lower()
    lines = [
        "Karma authorization is MANUAL on the operator Console — OpenClaw MCP must not create/accept vouchers or mint Runtime Keys.",
        "",
    ]
    if role in ("buyer", "both"):
        lines.extend(
            [
                "Buyer (Console / wallet):",
                "  1. Lock capacity (USDC credits) for the buyer identity",
                "  2. Create authorization voucher (buyer signs EIP-712 when enforced)",
                "  3. Optional: mint Runtime Key with request_voucher permission (Console)",
                "  4. Create task contract + settlement; bind voucher_id",
                "",
            ]
        )
    if role in ("seller", "both"):
        lines.extend(
            [
                "Seller (Console):",
                "  1. Lock capacity for seller bond",
                "  2. Verify + ACCEPT voucher (reserves buyer credits) — required before work",
                "  3. Optional: mint Runtime Key with submit_receipt / update_progress",
                "  4. Settlement lock as worker_agent_id",
                "",
            ]
        )
    lines.extend(
        [
            "After manual steps, export handoff JSON (see docs/OPENCLAW_P1_DUAL_AGENT.md) and call karma_validate_handoff.",
            "Automated MCP tools (verify, receipts, progress list) may run only after handoff validates.",
            "Buyer progress confirm: default Console-only; set KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM=true only if policy allows API confirm after UI approval.",
        ]
    )
    return "\n".join(lines)


def voucher_eip712_operator_notes() -> str:
    """Short operator notes when production enforces voucher EIP-712."""
    return (
        "When KARMA voucher EIP-712 is enabled, buyer_signature must come from the buyer wallet "
        "(Console or a one-shot signing script), not from OpenClaw chat.\n"
        "Use services/voucher_eip712.sign_authorization_voucher in a controlled environment, "
        "or the Console voucher wizard.\n"
        "Fields: buyer/seller identity, amount, bill_credit_amount, task hashes, nonce, expiry_time, chain_id."
    )
