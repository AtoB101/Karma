"""Handoff and policy gates before OpenClaw mutates Karma state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from karma_openclaw.handoff import validate_handoff_v1


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def buyer_confirm_allowed() -> bool:
    return _env_flag("KARMA_OPENCLAW_ALLOW_BUYER_CONFIRM")


def buyer_accept_allowed() -> bool:
    return _env_flag("KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT")


def setup_mutations_allowed() -> bool:
    """Contract / settlement create — default off (Console)."""
    return _env_flag("KARMA_OPENCLAW_ALLOW_SETUP_MUTATIONS")


def load_handoff_payload(handoff_json: str | None) -> dict[str, Any]:
    raw = (handoff_json or "").strip()
    if not raw:
        path = os.environ.get("KARMA_OPENCLAW_HANDOFF_PATH", "").strip()
        if path:
            raw = Path(path).read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(
            "handoff JSON required: pass handoff_json or set KARMA_OPENCLAW_HANDOFF_PATH to a handoff v1 file"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("handoff must be a JSON object")
    return payload


def require_valid_handoff(handoff_json: str | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Returns (error_dict, normalized_handoff).

    error_dict is None when handoff validates locally.
    """
    try:
        payload = load_handoff_payload(handoff_json)
    except (ValueError, json.JSONDecodeError) as exc:
        return (
            {
                "ok": False,
                "error": "handoff_required",
                "detail": str(exc),
                "hint": "Complete Console authorization first; see karma_manual_auth_checklist",
            },
            {},
        )

    ok, errors, normalized = validate_handoff_v1(payload)
    if not ok:
        return (
            {
                "ok": False,
                "error": "handoff_invalid",
                "errors": errors,
                "hint": "Fix handoff.json manual_console_steps_completed after Console steps",
            },
            normalized,
        )
    return None, normalized


def block_response(reason: str, *, hint: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": reason}
    if hint:
        out["hint"] = hint
    return out


def server_attestation_required() -> bool:
    return _env_flag("KARMA_OPENCLAW_REQUIRE_SERVER_ATTESTATION")


async def require_valid_handoff_for_automation(
    handoff_json: str | None,
    *,
    karma_identity_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Local handoff validation plus optional server attestation (POST handoff-confirm).
    """
    err, normalized = require_valid_handoff(handoff_json)
    if err:
        return err, normalized

    if not server_attestation_required():
        return None, normalized

    task_id = str(normalized.get("task_id") or "").strip()
    kid = (
        (karma_identity_id or "").strip()
        or os.environ.get("KARMA_ID", "").strip()
        or str(normalized.get("buyer_identity_id") or "").strip()
    )
    if not task_id or not kid:
        return (
            {
                "ok": False,
                "error": "attestation_context_missing",
                "detail": "task_id and karma_identity_id required for server attestation check",
                "hint": "Set KARMA_ID to this OpenClaw party identity",
            },
            normalized,
        )

    from urllib.parse import quote

    from karma_openclaw.http_client import api_get

    try:
        path = (
            f"/v1/openclaw/handoff-attestation?task_id={quote(task_id, safe='')}"
            f"&karma_identity_id={quote(kid, safe='')}"
        )
        att = await api_get(path)
    except Exception as exc:  # noqa: BLE001
        return (
            {
                "ok": False,
                "error": "attestation_check_failed",
                "detail": str(exc),
                "hint": "Call POST /v1/openclaw/handoff-confirm in Console first",
            },
            normalized,
        )

    if not (isinstance(att, dict) and att.get("attested")):
        return (
            {
                "ok": False,
                "error": "handoff_not_attested",
                "hint": "Complete Console: automation-readiness → handoff-confirm → export handoff",
            },
            normalized,
        )
    return None, normalized
