"""
Karma — Identity Role Profile KYC state machine (P3).

kyc_status ∈ {none, pending, verified, rejected}，流转：
- none → pending       (owner 提交 KYC)
- pending → verified   (验证方通过)
- pending → rejected   (验证方拒绝)
- rejected → pending   (owner 重新提交)

验证方 = 任一已认证的非 owner 身份（简化版；严格的 verifier 角色授权留后续）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import resolve_actor_id_with_dev_fallback
from db.models.orm import IdentityRoleProfile
from db.session import get_db
from services.path_param_safety import validate_public_url_segment

router = APIRouter()

_TRANSITIONS = {
    "none": {"pending"},
    "pending": {"verified", "rejected"},
    "verified": set(),
    "rejected": {"pending"},
}


class SubmitKycBody(BaseModel):
    kyc_payload: dict = Field(default_factory=dict)


class VerifyKycBody(BaseModel):
    decision: str = Field(..., pattern="^(verified|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)


def _resolve_actor_id(request: Request) -> str | None:
    return resolve_actor_id_with_dev_fallback(request)


async def _get_profile(db: AsyncSession, profile_id: str) -> IdentityRoleProfile:
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")
    return row


def _require_owner(request: Request, profile: IdentityRoleProfile) -> None:
    actor = _resolve_actor_id(request)
    if not actor or actor != profile.owner_identity_id:
        raise HTTPException(403, "only the profile owner can manage KYC")


def _serialize_kyc(profile: IdentityRoleProfile) -> dict:
    return {
        "profile_id": profile.profile_id,
        "kyc_status": profile.kyc_status,
        "kyc_payload": profile.kyc_payload or {},
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.post("/{profile_id}/kyc")
async def submit_kyc(
    profile_id: str,
    body: SubmitKycBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("profile_id", profile_id)
    profile = await _get_profile(db, profile_id)
    _require_owner(request, profile)

    current = profile.kyc_status or "none"
    if "pending" not in _TRANSITIONS.get(current, set()):
        raise HTTPException(409, f"cannot submit KYC from status {current}")

    profile.kyc_status = "pending"
    profile.kyc_payload = body.kyc_payload or {}
    profile.updated_at = datetime.utcnow()
    await db.flush()
    return _serialize_kyc(profile)


@router.post("/{profile_id}/kyc/verify")
async def verify_kyc(
    profile_id: str,
    body: VerifyKycBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("profile_id", profile_id)
    profile = await _get_profile(db, profile_id)

    actor = _resolve_actor_id(request)
    if not actor:
        raise HTTPException(403, "authentication required to verify KYC")
    if actor == profile.owner_identity_id:
        raise HTTPException(403, "owner cannot verify its own KYC")

    current = profile.kyc_status or "none"
    if body.decision not in _TRANSITIONS.get(current, set()):
        raise HTTPException(409, f"cannot verify KYC from status {current} to {body.decision}")

    payload = dict(profile.kyc_payload or {})
    payload["verification"] = {
        "decision": body.decision,
        "reason": body.reason,
        "verified_by": actor,
        "verified_at": datetime.utcnow().isoformat(),
    }
    profile.kyc_status = body.decision
    profile.kyc_payload = payload
    profile.updated_at = datetime.utcnow()
    await db.flush()
    return _serialize_kyc(profile)
