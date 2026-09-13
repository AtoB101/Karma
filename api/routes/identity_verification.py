"""
Karma — Master identity verification routes (证件 + 扫脸 → 身份卡).

- ``GET  /v1/identity/{identity_id}/verification``         本人看完整状态，他人只看状态位
- ``POST /v1/identity/{identity_id}/verification/submit``  本人提交「密文包 + 摘要 + 脱敏字段」
- ``POST /v1/identity/{identity_id}/verification/verify``  verifier 类档案核验

服务端只存密文与摘要：明文字段在服务层就被拒（见 services/identity_verification）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import IdentityRoleProfile, IdentityVerificationModel
from db.session import get_db
from services.identity_actor import resolve_actor_identity_id
from services.identity_verification import (
    IdentityVerificationError,
    assert_can_decide,
    assert_can_submit,
    build_submission,
    empty_view,
    mark_verified,
    owner_view,
    public_view,
)
from services.path_param_safety import validate_public_url_segment

router = APIRouter()


class SubmitVerificationBody(BaseModel):
    # 故意允许未知字段：任何夹带的明文 / 原图字段都要在服务层被指名拒掉，
    # 而不是被 pydantic 静默丢掉（丢掉会让"我传了明文"变成看不见的事实）。
    model_config = {"extra": "allow"}

    level: str | None = Field(default=None, max_length=16)
    # 摘要 / 密文的具体形状由服务层校验，错误信息才说得清楚（400 而不是 422）。
    doc_digest: str = Field(min_length=1, max_length=128)
    face_digest: str = Field(min_length=1, max_length=128)
    package_digest: str = Field(min_length=1, max_length=128)
    package_cipher: str = Field(min_length=1, max_length=8_000_000)
    encryption: dict[str, Any] = Field(default_factory=dict)
    extracted: dict[str, Any] = Field(default_factory=dict)


class VerifyDecisionBody(BaseModel):
    decision: str = Field(..., pattern="^(verified|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)


def _translate(exc: IdentityVerificationError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _require_owner(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to manage identity verification")
    if actor != identity_id:
        raise HTTPException(403, "only the identity owner can manage its verification")
    return actor


async def _require_verifier(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to verify identity")
    if actor == identity_id:
        raise HTTPException(403, "an identity cannot verify itself")
    row = (
        await db.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == actor,
                IdentityRoleProfile.class_ == "verifier",
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(403, "only a verifier-class profile can verify identity")
    return actor


@router.get("/{identity_id}/verification")
async def get_identity_verification(
    identity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    row = await db.get(IdentityVerificationModel, identity_id)
    actor = await resolve_actor_identity_id(db, request)
    if row is None:
        if actor == identity_id:
            return empty_view(identity_id)
        return {"identity_id": identity_id, "status": "none", "level": "basic", "verified_at": None}
    if actor == identity_id:
        return owner_view(row)
    return public_view(row)


@router.post("/{identity_id}/verification/submit")
async def submit_identity_verification(
    identity_id: str,
    body: SubmitVerificationBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)

    try:
        payload = build_submission(
            level=body.level,
            doc_digest=body.doc_digest,
            face_digest=body.face_digest,
            package_digest=body.package_digest,
            package_cipher=body.package_cipher,
            encryption=body.encryption,
            extracted=body.extracted,
            raw_payload=body.model_dump(),
        )
    except IdentityVerificationError as exc:
        raise _translate(exc) from exc

    row = await db.get(IdentityVerificationModel, identity_id)
    current = row.status if row else "none"
    try:
        assert_can_submit(current)
    except IdentityVerificationError as exc:
        raise _translate(exc) from exc

    if row is None:
        row = IdentityVerificationModel(identity_id=identity_id)
        db.add(row)

    row.status = "pending"
    row.level = payload["level"]
    row.doc_digest = payload["doc_digest"]
    row.face_digest = payload["face_digest"]
    row.package_digest = payload["package_digest"]
    row.package_cipher = payload["package_cipher"]
    row.encryption = payload["encryption"]
    row.extracted = payload["extracted"]
    row.reviewer_identity_id = None
    row.review_note = None
    row.verified_at = None
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


@router.post("/{identity_id}/verification/verify")
async def verify_identity_verification(
    identity_id: str,
    body: VerifyDecisionBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    reviewer = await _require_verifier(db, request, identity_id)

    row = await db.get(IdentityVerificationModel, identity_id)
    if row is None:
        raise HTTPException(404, "identity verification not found")

    try:
        assert_can_decide(row.status, body.decision)
    except IdentityVerificationError as exc:
        raise _translate(exc) from exc

    if body.decision == "verified":
        mark_verified(row, reviewer_identity_id=reviewer, note=body.reason)
    else:
        row.status = "rejected"
        row.reviewer_identity_id = reviewer
        row.review_note = (body.reason or "")[:2000] or None
        row.verified_at = None
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)
