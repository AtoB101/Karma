"""Karma API — brake-only administrative controls.

Ops may pause, freeze, risk-mark, and expire unpaid intents.
Ops must never lock, settle, refund, or otherwise move user funds.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_agent_id
from config.settings import settings
from core.schemas import IdentityProfile, RuntimeSafetyModeState
from db.models.orm import IdentityProfileModel
from db.session import get_db
from services.payment_intent_service import expire_stale_intents
from services.runtime_safety import (
    get_runtime_safety_mode_state,
    set_runtime_operational_pauses,
    set_runtime_safety_mode,
)
from services.security_monitoring import SecurityMonitoringEventType, record_security_event

router = APIRouter()


class UpdateSafetyModeRequest(BaseModel):
    enabled: bool
    reason: str | None = None


class UpdateOperationalPausesRequest(BaseModel):
    pause_new_lock: bool = False
    pause_new_authorization: bool = False
    pause_new_task: bool = False
    pause_new_settlement: bool = False
    reason: str | None = None


class MarkRiskIdentityRequest(BaseModel):
    risk_marked: bool = True
    reason: str | None = None


def _profile_to_schema(row: IdentityProfileModel) -> IdentityProfile:
    return IdentityProfile(
        identity_id=row.identity_id,
        display_id=row.display_id,
        legal_identity_status=row.legal_identity_status,
        status=row.status,
        bound_wallet_address=getattr(row, "bound_wallet_address", None),
        did_agent_address=getattr(row, "did_agent_address", None),
        on_chain_did=getattr(row, "on_chain_did", None),
        projection_readonly=bool(getattr(row, "projection_readonly", False)),
        projection_source=getattr(row, "projection_source", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def require_admin_actor(agent_id: str = Depends(get_current_agent_id)) -> str:
    allow = settings.admin_actor_id_set()
    if not allow or agent_id not in allow:
        raise HTTPException(status_code=403, detail="admin controls require a whitelisted actor id")
    return agent_id


@router.get("/controls", response_model=RuntimeSafetyModeState)
async def get_admin_controls_state(_: str = Depends(require_admin_actor)) -> RuntimeSafetyModeState:
    return get_runtime_safety_mode_state()


@router.post("/controls/safety-mode", response_model=RuntimeSafetyModeState)
async def update_admin_safety_mode(
    body: UpdateSafetyModeRequest,
    admin_actor_id: str = Depends(require_admin_actor),
) -> RuntimeSafetyModeState:
    result = set_runtime_safety_mode(
        enabled=body.enabled,
        reason=body.reason,
        actor_id=admin_actor_id,
    )
    # 高敏感操作审计（红队报告 KARMA-RT-2026-08-27-001 §5）：
    # 管理员切换安全模式能暂停全站资金操作，须可追溯、可告警。
    record_security_event(
        SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
        metadata={
            "path": "/v1/admin/controls/safety-mode",
            "actor_id": admin_actor_id,
            "route_group": "admin",
            "action": "safety-mode",
            "enabled": bool(body.enabled),
        },
    )
    return result


@router.post("/controls/pauses", response_model=RuntimeSafetyModeState)
async def update_admin_operational_pauses(
    body: UpdateOperationalPausesRequest,
    admin_actor_id: str = Depends(require_admin_actor),
) -> RuntimeSafetyModeState:
    result = set_runtime_operational_pauses(
        pause_new_lock=body.pause_new_lock,
        pause_new_authorization=body.pause_new_authorization,
        pause_new_task=body.pause_new_task,
        pause_new_settlement=body.pause_new_settlement,
        reason=body.reason,
        actor_id=admin_actor_id,
    )
    record_security_event(
        SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
        metadata={
            "path": "/v1/admin/controls/pauses",
            "actor_id": admin_actor_id,
            "route_group": "admin",
            "action": "operational-pauses",
            "pause_new_lock": bool(body.pause_new_lock),
            "pause_new_settlement": bool(body.pause_new_settlement),
        },
    )
    return result


@router.post("/controls/identities/{identity_id}/risk-mark", response_model=IdentityProfile)
async def mark_identity_risk(
    identity_id: str,
    body: MarkRiskIdentityRequest,
    db: AsyncSession = Depends(get_db),
    admin_actor_id: str = Depends(require_admin_actor),
) -> IdentityProfile:
    row = await db.get(IdentityProfileModel, identity_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"identity profile not found: {identity_id}")
    row.status = "risk_marked" if body.risk_marked else "active"
    reason = body.reason or ("risk flag enabled" if body.risk_marked else "risk flag cleared")
    legal_status_prefix = (row.legal_identity_status or "unbound").split("|")[0]
    row.legal_identity_status = f"{legal_status_prefix}|admin:{admin_actor_id}|{reason}"
    row.updated_at = datetime.utcnow()
    await db.flush()
    record_security_event(
        SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
        metadata={
            "path": "/v1/admin/controls/identities/{identity_id}/risk-mark",
            "actor_id": admin_actor_id,
            "route_group": "admin",
            "action": "risk-mark",
            "target_identity_id": identity_id,
            "risk_marked": bool(body.risk_marked),
        },
    )
    return _profile_to_schema(row)


class EmergencyFreezeRequest(BaseModel):
    reason: str
    duration_seconds: int = Field(default=3600, ge=60, le=7 * 24 * 3600)
    scope: str = "global"
    submit_on_chain: bool = False


@router.post("/controls/emergency-freeze")
async def admin_emergency_freeze(
    body: EmergencyFreezeRequest,
    admin_actor_id: str = Depends(require_admin_actor),
) -> dict:
    from services.security_control_plane import classify_and_maybe_freeze

    incident = classify_and_maybe_freeze(
        classification="admin_emergency_freeze",
        severity="critical",
        actor_id=admin_actor_id,
        reason=body.reason,
        freeze_scope=body.scope if body.scope in {"global", "agent", "bill", "binding"} else "global",
        duration_seconds=body.duration_seconds,
        submit_on_chain=body.submit_on_chain,
    )
    return {
        "incident_id": incident.incident_id,
        "freeze_requested": incident.freeze_requested,
        "on_chain_submitted": incident.on_chain_submitted,
        "detail": incident.detail,
    }


@router.post("/maintenance/expire-payment-intents")
async def admin_expire_stale_payment_intents(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin_actor),
) -> dict[str, int]:
    """Expire payment intents past ``expiresAt`` (cron / beat / manual)."""
    if not settings.payment_intent_expire_enabled:
        raise HTTPException(status_code=403, detail="payment intent expire maintenance disabled")
    count = await expire_stale_intents(db)
    await db.flush()
    return {"expired_count": count}
