"""
Karma — Identity Role Profile KYC state machine (P3).

kyc_status ∈ {none, pending, verified, rejected}，流转：
- none → pending       (owner 提交 KYC)
- pending → verified   (验证方通过)
- pending → rejected   (验证方拒绝)
- rejected → pending   (owner 重新提交)

验证方必须是 verifier 类档案（class=verifier），且不得是 owner 本人。
。``verified`` 是终态；唯一出口是合规撤销 ``verified → rejected``（复核员两人，
  或运维白名单单人，见 services/compliance_revocation.py）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import IdentityRoleProfile
from db.session import get_db
from services import compliance_revocation
from services.governance_stake import assert_governor_active
from services.security_monitoring import SecurityMonitoringEventType, record_security_event
from services.identity_actor import resolve_actor_identity_id
from services.identity_verification import (
    IdentityVerificationError,
    assert_no_plaintext_payload,
)
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


class RevokeKycBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


async def _get_profile(db: AsyncSession, profile_id: str) -> IdentityRoleProfile:
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")
    return row


async def _require_owner(db: AsyncSession, request: Request, profile: IdentityRoleProfile) -> None:
    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != profile.owner_identity_id:
        raise HTTPException(403, "only the profile owner can manage KYC")


async def _require_verifier(db: AsyncSession, request: Request, profile: IdentityRoleProfile) -> str:
    """验证方 = 已认证、非 owner、且持有 verifier 类档案。返回 actor identity。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to verify KYC")
    if actor == profile.owner_identity_id:
        raise HTTPException(403, "owner cannot verify its own KYC")

    result = await db.execute(
        select(IdentityRoleProfile).where(
            IdentityRoleProfile.owner_identity_id == actor,
            IdentityRoleProfile.class_ == "verifier",
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(403, "only a verifier-class profile can verify KYC")
    # 押金在则岗在：质押开出来的 verifier，押金被划走后立刻不能再批 KYC。
    await assert_governor_active(db, identity_id=actor, what="verifying KYC")
    return actor


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
    await _require_owner(db, request, profile)

    current = profile.kyc_status or "none"
    if "pending" not in _TRANSITIONS.get(current, set()):
        raise HTTPException(409, f"cannot submit KYC from status {current}")

    # 和主身份认证同一条红线：KYC 载荷里不许出现证件 / 人脸明文。
    try:
        assert_no_plaintext_payload(body.kyc_payload)
    except IdentityVerificationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc

    # 「复核结论」这个键只属于复核方：本人提交的载荷里带了它，等于自写一份「已通过」。
    submitted = dict(body.kyc_payload or {})
    submitted.pop("verification", None)
    profile.kyc_status = "pending"
    profile.kyc_payload = submitted
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

    actor = await _require_verifier(db, request, profile)

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

@router.post("/{profile_id}/kyc/revoke")
async def revoke_kyc(
    profile_id: str,
    body: RevokeKycBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """合规撤销：把已通过的子身份 KYC 降回 rejected（唯一一条从认证终态出来的边）。

    复核岗要两人（一人发起 + 另一人确认），运维白名单可单人直接执行。
    """
    validate_public_url_segment("profile_id", profile_id)
    profile = await _get_profile(db, profile_id)
    actor, privileged = await compliance_revocation.require_revoker(
        db, request, owner_identity_id=profile.owner_identity_id, what="revoking KYC"
    )
    compliance_revocation.assert_can_revoke(profile.kyc_status, what="KYC")
    reason = compliance_revocation.normalize_reason(body.reason)
    outcome = await compliance_revocation.propose_or_confirm(
        db,
        target_kind=compliance_revocation.TARGET_ROLE_PROFILE_KYC,
        target_id=profile_id,
        actor=actor,
        reason=reason,
        privileged=privileged,
    )
    if not outcome["executed"]:
        await db.commit()
        return {
            "revoked": False,
            "state": "awaiting_second_reviewer",
            "kyc_status": profile.kyc_status,
            **outcome,
        }

    compliance_revocation.apply_kyc_revocation(
        profile,
        proposed_by=outcome["proposed_by"],
        confirmed_by=outcome["confirmed_by"],
        reason=outcome["reason"],
    )
    await db.flush()
    await db.commit()
    await db.refresh(profile)
    record_security_event(
        SecurityMonitoringEventType.VERIFICATION_REVOKED,
        metadata={
            "target_kind": compliance_revocation.TARGET_ROLE_PROFILE_KYC,
            "target_id": profile_id,
            "path": outcome["path"],
            "proposed_by": outcome["proposed_by"],
            "confirmed_by": outcome["confirmed_by"],
            "reason": outcome["reason"][:200],
        },
    )
    return {"revoked": True, "state": "revoked", "kyc_status": profile.kyc_status, **outcome}
