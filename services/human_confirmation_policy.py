"""Human vs auto confirmation policy — real-world scene gates.

Agents should only bother the owner at OWNER_CONFIRM (or POLICY_AUTO when
policy is missing). After owner says yes, accept/execute may proceed.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "human-confirmation-policy.v1.json"
)

_LOCK = threading.Lock()
_SESSIONS: dict[str, "ConfirmationSession"] = {}


class ConfirmationPolicyError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_policy_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"confirmation policy missing: {CATALOG_PATH}")
    import json

    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-human-confirmation-v1":
        raise ConfirmationPolicyError("unsupported confirmation policy schema")
    return data


# Intent discovery task_type → confirmation scene_id
_TASK_TYPE_TO_SCENE: dict[str, str] = {
    "commerce.food": "food_delivery",
    "commerce.ride": "ride_hailing",
    "commerce.hotel": "hotel_booking",
    "commerce.flight": "flight_booking",
    "commerce.procurement": "b2b_procurement",
    "b2b.procurement": "b2b_procurement",
    "api.translate": "api_tool_call",
    "api.caption": "api_tool_call",
    "api.labeling": "api_tool_call",
    "api.generic": "api_tool_call",
    "api.data": "data_api_billing",
    "data.api": "data_api_billing",
    "logistics": "logistics_delivery",
    "software": "software_development",
}


def task_type_to_scene_id(task_type: str | None) -> str:
    """Map discovery task_type (e.g. commerce.food) to confirmation scene_id."""
    tt = (task_type or "").strip().lower()
    if not tt:
        return "api_tool_call"
    if tt in _TASK_TYPE_TO_SCENE:
        return _TASK_TYPE_TO_SCENE[tt]
    if tt.startswith("commerce.food") or "food" in tt:
        return "food_delivery"
    if tt.startswith("commerce.ride") or "ride" in tt:
        return "ride_hailing"
    if tt.startswith("commerce.hotel") or "hotel" in tt:
        return "hotel_booking"
    if tt.startswith("commerce.flight") or "flight" in tt:
        return "flight_booking"
    if "procure" in tt or "b2b" in tt:
        return "b2b_procurement"
    if tt.startswith("api.") or "mcp" in tt or "tool" in tt:
        return "api_tool_call"
    if "data" in tt:
        return "data_api_billing"
    if "logistic" in tt or "delivery" in tt:
        return "logistics_delivery"
    if "software" in tt or "dev" in tt:
        return "software_development"
    # Unknown → use global defaults via fallback scene wrapper
    return tt if tt in (load_policy_catalog().get("scenes") or {}) else "api_tool_call"


def list_policy_scenes() -> list[dict[str, Any]]:
    cat = load_policy_catalog()
    out = []
    for sid, body in (cat.get("scenes") or {}).items():
        out.append(
            {
                "scene_id": sid,
                "title_zh": body.get("title_zh"),
                "reality_note_zh": body.get("reality_note_zh"),
                "auto_ok_examples_zh": body.get("auto_ok_examples_zh") or [],
            }
        )
    return out


def get_scene_policy(scene_id: str) -> dict[str, Any]:
    cat = load_policy_catalog()
    scene = (cat.get("scenes") or {}).get(scene_id)
    if not scene:
        # fallback to global defaults wrapped
        return {
            "scene_id": scene_id,
            "title_zh": scene_id,
            "reality_note_zh": "使用全局默认确认策略",
            "buyer": (cat.get("global_defaults") or {}).get("buyer") or {},
            "seller": (cat.get("global_defaults") or {}).get("seller") or {},
            "owner_prompt_templates_zh": {},
            "auto_ok_examples_zh": [],
            "fallback": True,
        }
    return {"scene_id": scene_id, **scene, "fallback": False}


def resolve_gate(
    *,
    scene_id: str,
    role: str,
    step: str,
    policy_auto_allowed: bool = False,
) -> dict[str, Any]:
    """Resolve gate mode for one step. role: buyer|seller."""
    role = role.lower().strip()
    if role not in {"buyer", "seller"}:
        raise ConfirmationPolicyError("role must be buyer or seller")
    cat = load_policy_catalog()
    scene = get_scene_policy(scene_id)
    role_map = dict(scene.get(role) or {})
    defaults = ((cat.get("global_defaults") or {}).get(role)) or {}
    mode = role_map.get(step) or defaults.get(step) or "OWNER_CONFIRM"

    effective = mode
    needs_owner = False
    if mode == "AUTO":
        needs_owner = False
    elif mode == "OWNER_CONFIRM":
        needs_owner = True
    elif mode == "POLICY_AUTO":
        if policy_auto_allowed:
            effective = "AUTO"
            needs_owner = False
        else:
            effective = "OWNER_CONFIRM"
            needs_owner = True
    elif mode == "COUNTERPARTY_OR_OWNER":
        needs_owner = True
        effective = "OWNER_CONFIRM"
    else:
        needs_owner = True
        effective = "OWNER_CONFIRM"

    templates = scene.get("owner_prompt_templates_zh") or {}
    return {
        "scene_id": scene_id,
        "role": role,
        "step": step,
        "mode": mode,
        "effective_mode": effective,
        "needs_owner_confirmation": needs_owner,
        "policy_auto_allowed": policy_auto_allowed,
        "owner_prompt_template_zh": templates.get(step),
        "reality_note_zh": scene.get("reality_note_zh"),
    }


def plan_confirmations(
    *,
    scene_id: str,
    role: str,
    steps: list[str] | None = None,
    policy_auto_allowed: bool = False,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cat = load_policy_catalog()
    lifecycle = list(cat.get("lifecycle_steps") or [])
    use_steps = list(steps) if steps else lifecycle
    ctx = context or {}
    must: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []
    for step in use_steps:
        gate = resolve_gate(
            scene_id=scene_id,
            role=role,
            step=step,
            policy_auto_allowed=policy_auto_allowed,
        )
        prompt = gate.get("owner_prompt_template_zh")
        if prompt and ctx:
            try:
                prompt = str(prompt).format(**ctx)
            except Exception:  # noqa: BLE001
                pass
        item = {**gate, "owner_prompt_zh": prompt}
        if gate["needs_owner_confirmation"]:
            must.append(item)
        else:
            auto.append(item)
    scene = get_scene_policy(scene_id)
    return {
        "schema_version": "karma-human-confirmation-v1",
        "scene_id": scene_id,
        "role": role,
        "title_zh": scene.get("title_zh"),
        "reality_note_zh": scene.get("reality_note_zh"),
        "must_confirm": must,
        "auto_ok": auto,
        "auto_ok_examples_zh": scene.get("auto_ok_examples_zh") or [],
        "agent_ux_zh": (cat.get("agent_ux_zh") or {}),
        "summary_zh": (
            f"需主人确认 {len(must)} 步；可自动 {len(auto)} 步。"
            "Agent 只需在必须确认点询问是否确认。"
        ),
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ConfirmationSession:
    session_id: str
    scene_id: str
    role: str
    step: str
    owner_agent_id: str
    prompt_zh: str
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"  # PENDING | CONFIRMED | REJECTED | EXPIRED
    created_at: str = ""
    decided_at: str | None = None
    decision_note: str | None = None
    interaction_ref: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "scene_id": self.scene_id,
            "role": self.role,
            "step": self.step,
            "owner_agent_id": self.owner_agent_id,
            "prompt_zh": self.prompt_zh,
            "context": self.context,
            "status": self.status,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decision_note": self.decision_note,
            "interaction_ref": self.interaction_ref,
            "can_proceed": self.status == "CONFIRMED",
        }


def reset_confirmation_sessions() -> None:
    with _LOCK:
        _SESSIONS.clear()


def create_confirmation_session(
    *,
    scene_id: str,
    role: str,
    step: str,
    owner_agent_id: str,
    context: dict[str, Any] | None = None,
    interaction_ref: str | None = None,
    policy_auto_allowed: bool = False,
) -> dict[str, Any]:
    gate = resolve_gate(
        scene_id=scene_id,
        role=role,
        step=step,
        policy_auto_allowed=policy_auto_allowed,
    )
    if not gate["needs_owner_confirmation"]:
        return {
            "skipped": True,
            "reason": "step is AUTO under current policy",
            "gate": gate,
            "can_proceed": True,
            "status": "AUTO_APPROVED",
        }
    ctx = dict(context or {})
    prompt = gate.get("owner_prompt_template_zh") or f"是否确认执行 {step}？"
    try:
        prompt = str(prompt).format(**ctx)
    except Exception:  # noqa: BLE001
        pass
    sid = "cfm_" + secrets.token_hex(12)
    sess = ConfirmationSession(
        session_id=sid,
        scene_id=scene_id,
        role=role.lower(),
        step=step,
        owner_agent_id=owner_agent_id,
        prompt_zh=prompt,
        context=ctx,
        status="PENDING",
        created_at=_iso_now(),
        interaction_ref=interaction_ref,
    )
    with _LOCK:
        _SESSIONS[sid] = sess
    return {"skipped": False, **sess.public(), "gate": gate}


def get_confirmation_session(session_id: str) -> dict[str, Any]:
    with _LOCK:
        sess = _SESSIONS.get(session_id)
    if not sess:
        raise ConfirmationPolicyError(f"unknown confirmation session: {session_id}")
    return sess.public()


def decide_confirmation_session(
    session_id: str,
    *,
    confirm: bool,
    note: str | None = None,
    actor_agent_id: str | None = None,
) -> dict[str, Any]:
    with _LOCK:
        sess = _SESSIONS.get(session_id)
        if not sess:
            raise ConfirmationPolicyError(f"unknown confirmation session: {session_id}")
        if sess.status != "PENDING":
            raise ConfirmationPolicyError(f"session already {sess.status}")
        if actor_agent_id and actor_agent_id != sess.owner_agent_id:
            raise ConfirmationPolicyError("only the owner_agent_id may decide this session")
        sess.status = "CONFIRMED" if confirm else "REJECTED"
        sess.decided_at = _iso_now()
        sess.decision_note = note
        out = sess.public()
    out["next_zh"] = (
        "主人已确认，Agent 可继续接单/锁字段/执行/结算"
        if confirm
        else "主人已拒绝，停止该步，不接单、不锁款"
    )
    return out


def assert_step_allowed(
    *,
    scene_id: str,
    role: str,
    step: str,
    confirmation_session_id: str | None = None,
    policy_auto_allowed: bool = False,
) -> dict[str, Any]:
    """Gate helper for orchestration: AUTO ok; OWNER_CONFIRM requires CONFIRMED session."""
    gate = resolve_gate(
        scene_id=scene_id,
        role=role,
        step=step,
        policy_auto_allowed=policy_auto_allowed,
    )
    if not gate["needs_owner_confirmation"]:
        return {"allowed": True, "gate": gate, "reason": "auto"}
    if not confirmation_session_id:
        raise ConfirmationPolicyError(
            f"step {step} requires owner confirmation session for scene {scene_id}"
        )
    sess = get_confirmation_session(confirmation_session_id)
    if sess["status"] != "CONFIRMED":
        raise ConfirmationPolicyError(
            f"confirmation session status is {sess['status']}, need CONFIRMED"
        )
    if sess["scene_id"] != scene_id or sess["step"] != step or sess["role"] != role.lower():
        raise ConfirmationPolicyError("confirmation session does not match scene/role/step")
    return {"allowed": True, "gate": gate, "reason": "owner_confirmed", "session": sess}
