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
