"""Karma API — brake-only administrative controls."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_agent_id
from config.settings import settings
from core.schemas import IdentityProfile, RuntimeSafetyModeState
from db.models.orm import IdentityProfileModel
from db.session import get_db
from services.runtime_safety import (
    get_runtime_safety_mode_state,
    set_runtime_operational_pauses,
    set_runtime_safety_mode,
)

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
    return set_runtime_safety_mode(
        enabled=body.enabled,
        reason=body.reason,
        actor_id=admin_actor_id,
    )


@router.post("/controls/pauses", response_model=RuntimeSafetyModeState)
async def update_admin_operational_pauses(
    body: UpdateOperationalPausesRequest,
    admin_actor_id: str = Depends(require_admin_actor),
) -> RuntimeSafetyModeState:
    return set_runtime_operational_pauses(
        pause_new_lock=body.pause_new_lock,
        pause_new_authorization=body.pause_new_authorization,
        pause_new_task=body.pause_new_task,
        pause_new_settlement=body.pause_new_settlement,
        reason=body.reason,
        actor_id=admin_actor_id,
    )


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
    return _profile_to_schema(row)
