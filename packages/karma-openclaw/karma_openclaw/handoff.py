"""OpenClaw ↔ OpenClaw task handoff (v1) — coordination without automating authorization."""

from __future__ import annotations

from typing import Any

HANDOFF_VERSION = "1"

# Steps that MUST be completed by a human in Karma Console (or wallet UI), not by Claw MCP.
MANUAL_CONSOLE_STEPS_BUYER = frozenset(
    {
        "buyer_create_voucher",
        "buyer_mint_runtime_key",
        "buyer_lock_capacity",
    }
)
MANUAL_CONSOLE_STEPS_SELLER = frozenset(
    {
        "seller_accept_voucher",
        "seller_mint_runtime_key",
        "seller_lock_capacity",
    }
)
MANUAL_CONSOLE_STEPS_SHARED = frozenset(
    {
        "settlement_created",
        "settlement_worker_locked",
    }
)

ALL_KNOWN_MANUAL_STEPS = MANUAL_CONSOLE_STEPS_BUYER | MANUAL_CONSOLE_STEPS_SELLER | MANUAL_CONSOLE_STEPS_SHARED


def validate_handoff_v1(payload: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """
    Validate handoff JSON shape and return (ok, error_messages, normalized_view).

    Does not call Karma HTTP — use together with ``karma_validate_handoff`` MCP tool for live checks.
    """
    errors: list[str] = []
    if payload.get("handoff_version") != HANDOFF_VERSION:
        errors.append(f"handoff_version must be {HANDOFF_VERSION!r}")

    for field in ("trace_id", "task_id", "buyer_identity_id", "seller_identity_id"):
        val = payload.get(field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{field} is required (non-empty string)")

    voucher_id = payload.get("voucher_id")
    if voucher_id is not None and (not isinstance(voucher_id, str) or not voucher_id.strip()):
        errors.append("voucher_id must be a non-empty string when present")

    auth = payload.get("authorization")
    if not isinstance(auth, dict):
        errors.append("authorization object is required")
        auth = {}

    completed = auth.get("manual_console_steps_completed")
    if not isinstance(completed, list):
        errors.append("authorization.manual_console_steps_completed must be a list of step ids")
        completed = []

    unknown = [s for s in completed if s not in ALL_KNOWN_MANUAL_STEPS]
    if unknown:
        errors.append(f"unknown manual_console_steps_completed entries: {unknown}")

    # Minimum bar before Claw may run verify / delivery automation.
    required_before_automation = {"buyer_create_voucher", "seller_accept_voucher", "settlement_created"}
    missing = sorted(required_before_automation - set(completed))
    if missing:
        errors.append(
            "authorization incomplete for automated verify/delivery — complete in Console first, "
            f"then add to manual_console_steps_completed: {missing}"
        )

    voucher_status = auth.get("voucher_status")
    if voucher_status is not None and voucher_status not in (
        "created",
        "accepted",
        "used",
        "cancelled",
        "expired",
    ):
        errors.append(f"authorization.voucher_status invalid: {voucher_status!r}")

    if voucher_status and voucher_status != "accepted" and "seller_accept_voucher" in completed:
        errors.append("voucher_status must be 'accepted' when seller_accept_voucher is marked complete")

    normalized = {
        "handoff_version": HANDOFF_VERSION,
        "trace_id": str(payload.get("trace_id", "")).strip(),
        "task_id": str(payload.get("task_id", "")).strip(),
        "voucher_id": str(voucher_id).strip() if voucher_id else None,
        "buyer_identity_id": str(payload.get("buyer_identity_id", "")).strip(),
        "seller_identity_id": str(payload.get("seller_identity_id", "")).strip(),
        "bill_credit_amount": payload.get("bill_credit_amount"),
        "authorization": {
            "voucher_status": voucher_status,
            "manual_console_steps_completed": list(completed),
        },
    }
    return (len(errors) == 0, errors, normalized)
