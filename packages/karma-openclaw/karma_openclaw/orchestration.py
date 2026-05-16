"""Suggest next automation steps for OpenClaw (after Console authorization)."""

from __future__ import annotations

from typing import Any

# Settlement status → suggested MCP / Console action (seller/buyer).
_NEXT_BY_STATUS: dict[str, dict[str, str]] = {
    "draft": {
        "buyer": "Console: create settlement + pending; or ALLOW_SETUP_MUTATIONS",
        "seller": "Wait for buyer setup",
    },
    "pending": {
        "buyer": "Wait for seller lock",
        "seller": "karma_settlement_lock(worker_agent_id=you)",
    },
    "accepted": {
        "seller": "karma_settlement_start",
        "buyer": "Wait for execution",
    },
    "in_progress": {
        "seller": "karma_submit_execution_receipt / karma_runtime_submit_receipt",
        "buyer": "karma_list_receipts_for_task (monitor)",
    },
    "progress_submitted": {
        "buyer": "Console: confirm progress (or ALLOW_BUYER_CONFIRM)",
        "seller": "Wait or submit more progress",
    },
    "progress_confirmed": {
        "seller": "Continue work or karma_settlement_submit_delivery when done",
        "buyer": "Monitor",
    },
    "delivered": {
        "buyer": "karma_submit_verification then Console buyer-accept (or ALLOW_BUYER_ACCEPT)",
        "seller": "Wait for buyer acceptance",
    },
    "settled": {
        "buyer": "Done — optional on-chain payout per runbook",
        "seller": "Done",
    },
}


def suggest_next_steps(
    *,
    role: str,
    settlement_status: str | None,
    voucher_status: str | None,
    handoff_ok: bool,
) -> dict[str, Any]:
    role = role.strip().lower()
    if role not in ("buyer", "seller"):
        role = "seller"
    hints: list[str] = []
    if not handoff_ok:
        hints.append("Run karma_validate_handoff after Console authorization steps.")
        hints.append("Run karma_manual_auth_checklist.")
    if voucher_status and voucher_status != "accepted":
        hints.append(f"Voucher status is {voucher_status!r} — seller must accept in Console.")
    status_key = (settlement_status or "").lower().replace(" ", "_")
    by_status = _NEXT_BY_STATUS.get(status_key, {})
    suggested = by_status.get(role, "karma_get_settlement + karma_list_receipts_for_task")
    return {
        "role": role,
        "settlement_status": settlement_status,
        "voucher_status": voucher_status,
        "handoff_ok": handoff_ok,
        "suggested_action": suggested,
        "hints": hints,
    }
