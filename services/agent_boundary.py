"""Agent Boundary Standard — capability + responsibility + confirmation.

Every Karma-connected agent should expose a counterparty-readable boundary card
so discovery, human Yes/No gates, and delivery stay aligned with real scenes.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.human_confirmation_policy import plan_confirmations, task_type_to_scene_id

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "agent-boundary.v1.json"
)

_LOCK = threading.Lock()
_STORE_PATH = Path(__file__).resolve().parents[1] / ".karma_data" / "agent_boundaries.json"
_CACHE: dict[str, dict[str, Any]] = {}
_LOADED = False

# Capability / skill hints → scene_id
_CAP_TO_SCENE: dict[str, str] = {
    "order_food": "food_delivery",
    "food_delivery": "food_delivery",
    "book_ride": "ride_hailing",
    "ride_hailing": "ride_hailing",
    "book_hotel": "hotel_booking",
    "hotel_booking": "hotel_booking",
    "book_flight": "flight_booking",
    "flight_booking": "flight_booking",
    "b2b_procurement": "b2b_procurement",
    "data_api_billing": "data_api_billing",
    "api_tool_call": "api_tool_call",
    "api.translate": "api_tool_call",
    "api.caption": "api_tool_call",
    "api.labeling": "api_tool_call",
    "logistics_delivery": "logistics_delivery",
    "software_development": "software_development",
}


class AgentBoundaryError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_boundary_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"agent boundary catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-agent-boundary-v1":
        raise AgentBoundaryError("unsupported agent boundary schema")
    return data


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _CACHE.update({str(k): v for k, v in data.items() if isinstance(v, dict)})
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def save_agent_boundary(agent_id: str, boundary: dict[str, Any]) -> None:
    """Persist boundary after re-assessing completeness (never trust caller flags)."""
    _ensure_loaded()
    row = dict(boundary)
    row["agent_id"] = agent_id
    cap = row.get("capability_boundary") or {}
    complete, gaps = _assess_complete(
        profile_id=row.get("profile_id"),
        conf_role=(row.get("confirmation_boundary") or {}).get("role")
        or karma_role_to_confirmation_role(str(row.get("karma_role") or "worker")),
        scene_ids=list(row.get("scene_ids") or []),
        service_specs=dict(cap.get("service_specs") or {}),
        do_not=str(cap.get("do_not") or ""),
        capabilities=list(cap.get("capabilities") or []),
    )
    row["boundary_complete"] = complete
    row["completeness_gaps"] = gaps
    if complete:
        row["efficiency_note_zh"] = (
            "能力/责任/确认边界已界定：Agent 只在 must_confirm 步骤询问主人是否确认；"
            "auto_ok 步骤自动执行，保证交付畅通与增效。"
        )
    else:
        row["efficiency_note_zh"] = (
            "边界不完整：对端可见缺口。建议走 connect-from-template 补齐 service_specs 与不做清单。"
        )
    with _LOCK:
        _CACHE[agent_id] = row
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STORE_PATH.write_text(
            json.dumps(_CACHE, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def get_agent_boundary(agent_id: str) -> dict[str, Any] | None:
    _ensure_loaded()
    with _LOCK:
        row = _CACHE.get(agent_id)
        return dict(row) if row else None


def clear_agent_boundaries() -> None:
    global _LOADED
    with _LOCK:
        _CACHE.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def karma_role_to_confirmation_role(role: str | None) -> str:
    r = (role or "").lower().strip()
    if r in {"client", "buyer", "user"}:
        return "buyer"
    return "seller"


def scenes_from_capabilities(capabilities: list[str] | None) -> list[str]:
    scenes: list[str] = []
    for c in capabilities or []:
        raw = str(c).strip()
        if raw.startswith("industry:"):
            sid = raw.split(":", 1)[1]
        else:
            sid = _CAP_TO_SCENE.get(raw) or _CAP_TO_SCENE.get(raw.lower())
            if not sid and raw.startswith("commerce."):
                sid = task_type_to_scene_id(raw)
        if sid and sid not in scenes:
            scenes.append(sid)
    return scenes


def _confirmation_block(*, scene_ids: list[str], conf_role: str) -> dict[str, Any]:
    primary = scene_ids[0] if scene_ids else "api_tool_call"
    plan = plan_confirmations(scene_id=primary, role=conf_role)
    must = [x["step"] for x in plan["must_confirm"]]
    auto = [x["step"] for x in plan["auto_ok"]]
    policy_auto = [
        x["step"]
        for x in (plan["must_confirm"] + plan["auto_ok"])
        if x.get("mode") == "POLICY_AUTO"
    ]
    return {
        "role": conf_role,
        "primary_scene_id": primary,
        "scene_ids": scene_ids or [primary],
        "must_confirm_steps": must,
        "auto_ok_steps": auto,
        "policy_auto_steps": policy_auto,
        "summary_zh": plan.get("summary_zh"),
        "agent_ux_zh": plan.get("agent_ux_zh"),
        "reality_note_zh": plan.get("reality_note_zh"),
    }


def _assess_complete(
    *,
    profile_id: str | None,
    conf_role: str,
    scene_ids: list[str],
    service_specs: dict[str, Any],
    do_not: str,
    capabilities: list[str],
) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    pid = (profile_id or "").lower()
    if not capabilities:
        gaps.append("capabilities")
    if conf_role == "buyer" or pid == "user":
        # Buyer agents: confirmation boundary is enough
        return (len(gaps) == 0, gaps)
    if not scene_ids:
        gaps.append("scene_ids")
    if not service_specs:
        gaps.append("service_specs")
    else:
        for sid in scene_ids:
            if sid not in service_specs:
                gaps.append(f"service_specs.{sid}")
    if not (do_not or "").strip():
        gaps.append("boundaries/do_not")
    return (len(gaps) == 0, gaps)


def materialize_agent_boundary(
    *,
    agent_id: str,
    name: str | None = None,
    karma_role: str = "worker",
    profile_id: str | None = None,
    capabilities: list[str] | None = None,
    scene_ids: list[str] | None = None,
    profile_card: dict[str, Any] | None = None,
    owner_identity_id: str | None = None,
    responsibility_notes_zh: str | None = None,
    allows_delegation: bool = False,
    responsibility_acknowledged: bool = False,
) -> dict[str, Any]:
    """Build the public boundary card for a connected agent.

    ``responsibility_acknowledged`` defaults False — must be set only after a
    verified P1 responsibility ack (anti-forgery).
    """
    caps = list(capabilities or [])
    card = dict(profile_card or {})
    scenes = list(scene_ids or [])
    if not scenes:
        scenes = list(card.get("industry_ids") or card.get("scenes_interest") or [])
    if not scenes:
        scenes = scenes_from_capabilities(caps)

    conf_role = karma_role_to_confirmation_role(karma_role if not profile_id else (
        "client" if profile_id == "user" else karma_role
    ))
    if profile_id == "user":
        conf_role = "buyer"

    service_specs = dict(card.get("service_specs") or {})
    do_not = str(card.get("boundaries") or "").strip()
    if not do_not and service_specs:
        # Collect per-industry boundaries strings
        parts = []
        for spec in service_specs.values():
            if isinstance(spec, dict) and spec.get("boundaries"):
                parts.append(str(spec["boundaries"]))
        do_not = "；".join(parts)

    capability_boundary = {
        "capabilities": caps,
        "capability_summary": card.get("capability_summary") or (name or agent_id),
        "service_specs": service_specs,
        "do_not": do_not,
        "service_area": card.get("service_area") or {},
        "business_hours": card.get("business_hours") or {},
        "service_targets": card.get("service_targets") or [],
        "preferred_currency": card.get("preferred_currency") or "USDC",
    }

    compliance = dict(card.get("compliance_flags") or {})
    if "no_fund_custody" not in compliance:
        compliance["no_fund_custody"] = True

    responsibility_boundary = {
        "owner_identity_id": owner_identity_id or agent_id,
        "acknowledged": bool(responsibility_acknowledged),
        "boundary_id": f"rb_{agent_id}",
        "allows_delegation": bool(allows_delegation),
        "compliance_flags": compliance,
        "trade_side": card.get("trade_side"),
        "notes_zh": responsibility_notes_zh
        or (
            "交付与证据责任在本 agent；资金不托管；"
            "转委托默认关闭；成交字段另走 Important Fields 三方锁定。"
        ),
    }

    confirmation_boundary = _confirmation_block(scene_ids=scenes, conf_role=conf_role)
    complete, gaps = _assess_complete(
        profile_id=profile_id,
        conf_role=conf_role,
        scene_ids=scenes,
        service_specs=service_specs,
        do_not=do_not,
        capabilities=caps,
    )

    return {
        "schema_version": "karma-agent-boundary-v1",
        "agent_id": agent_id,
        "name": name,
        "profile_id": profile_id,
        "karma_role": karma_role,
        "scene_ids": scenes,
        "boundary_complete": complete,
        "completeness_gaps": gaps,
        "capability_boundary": capability_boundary,
        "responsibility_boundary": responsibility_boundary,
        "confirmation_boundary": confirmation_boundary,
        "efficiency_note_zh": (
            "能力/责任/确认边界已界定：Agent 只在 must_confirm 步骤询问主人是否确认；"
            "auto_ok 步骤自动执行，保证交付畅通与增效。"
            if complete
            else "边界不完整：对端可见缺口。建议走 connect-from-template 补齐 service_specs 与不做清单。"
        ),
        "related": {
            "onboarding": "/v1/standards/onboarding",
            "confirmation_policy": "/v1/standards/confirmation-policy",
            "important_fields": "/v1/standards/important-fields",
            "profile_card": f"/v1/agents/{agent_id}/profile-card",
        },
    }


def boundary_digest(boundary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact digest for discovery ranking cards."""
    if not boundary:
        return None
    conf = boundary.get("confirmation_boundary") or {}
    cap = boundary.get("capability_boundary") or {}
    return {
        "schema_version": "karma-agent-boundary-v1",
        "boundary_complete": bool(boundary.get("boundary_complete")),
        "scene_ids": list(boundary.get("scene_ids") or []),
        "do_not": (cap.get("do_not") or "")[:200],
        "must_confirm_steps": list(conf.get("must_confirm_steps") or [])[:12],
        "auto_ok_steps": list(conf.get("auto_ok_steps") or [])[:12],
        "primary_scene_id": conf.get("primary_scene_id"),
        "confirmation_role": conf.get("role"),
    }


def materialize_from_onboarding_result(
    materialized: dict[str, Any],
    *,
    agent_id: str,
    owner_identity_id: str | None = None,
    responsibility_acknowledged: bool = False,
) -> dict[str, Any]:
    connect = materialized.get("agent_connect") or {}
    card = materialized.get("profile_card") or {}
    hints = materialized.get("discovery_hints") or {}
    return materialize_agent_boundary(
        agent_id=agent_id,
        name=connect.get("name"),
        karma_role=str(connect.get("role") or "worker"),
        profile_id=materialized.get("profile_id") or card.get("profile_id"),
        capabilities=list(connect.get("capabilities") or []),
        scene_ids=list(hints.get("scene_ids") or card.get("industry_ids") or []),
        profile_card=card,
        owner_identity_id=owner_identity_id or agent_id,
        responsibility_acknowledged=responsibility_acknowledged,
    )
