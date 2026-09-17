"""Karma — 技能开发者实名路由。

- ``GET  /v1/developers/me``                        本人看自己名下所有开发者档案
- ``POST /v1/developers/prepare``                   服务端生成「待签开发者协议」原文
- ``POST /v1/developers/submit``                    提交实名 + 材料密文包 + 协议签名
- ``POST /v1/developers/{id}/review``               verifier 类档案复核（不能自审自己）
- ``GET  /v1/developers/{id}``                      公开档案（尽调用）
- ``GET  /v1/developers?identity_id=``              某个主体下**已通过**的开发者名单

服务端只存密文包 + 摘要；明文材料在服务层被按名拒掉（services/developer_registry）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import IdentityRoleProfile, SkillDeveloperModel
from db.session import get_db
from services.developer_registry import (
    DeveloperError,
    agreement_digest,
    agreement_text,
    assert_can_decide,
    assert_can_submit,
    assert_entity_verified,
    build_signup_message,
    build_submission,
    empty_view,
    find_by_signer,
    is_verified,
    list_by_identity,
    mark_rejected,
    mark_verified,
    owner_view,
    public_view,
    verify_signer,
)
from services.identity_actor import resolve_actor_identity_id
from services.path_param_safety import validate_public_url_segment

router = APIRouter()
public_router = APIRouter()


class PrepareDeveloperBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    real_name: str = Field(min_length=1, max_length=64)
    role_title: str = Field(min_length=1, max_length=64)
    contact_email: str = Field(min_length=3, max_length=200)
    role: str | None = Field(default=None, max_length=32)


class SubmitDeveloperBody(BaseModel):
    # 与主体认证同一策略：允许未知字段，夹带的明文由服务层指名拒掉，
    # 而不是被 pydantic 静默丢掉（丢掉会让"我传了明文"变成看不见的事实）。
    model_config = {"extra": "allow"}

    real_name: str = Field(min_length=1, max_length=64)
    role_title: str = Field(min_length=1, max_length=64)
    contact_email: str = Field(min_length=3, max_length=200)
    role: str | None = Field(default=None, max_length=32)
    materials: list[dict[str, Any]] = Field(default_factory=list)
    package_digest: str | None = Field(default=None, max_length=128)
    package_cipher: str | None = Field(default=None, max_length=8_000_000)
    encryption: dict[str, Any] = Field(default_factory=dict)
    signature: str = Field(min_length=1, max_length=200)


class ReviewDeveloperBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    decision: str = Field(..., pattern="^(verified|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)


def _translate(exc: DeveloperError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _actor_or_403(db: AsyncSession, request: Request) -> str:
    """本人视图的身份一律从鉴权头解析（与 /v1/skills 一致），不接受客户端自报。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to manage developer profiles")
    return actor


async def _require_reviewer(db: AsyncSession, request: Request, subject_identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to review developer profiles")
    if actor == subject_identity_id:
        raise HTTPException(403, "an identity cannot review its own developer profile")
    row = (
        await db.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == actor,
                IdentityRoleProfile.class_ == "verifier",
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(403, "only a verifier-class profile can review developer profiles")
    return actor


async def _load(db: AsyncSession, developer_id: str) -> SkillDeveloperModel | None:
    return await db.get(SkillDeveloperModel, developer_id)


def _mine(identity_id: str, rows: list[SkillDeveloperModel]) -> dict[str, Any]:
    return {
        "identity_id": identity_id,
        "count": len(rows),
        "developers": [owner_view(r) for r in rows],
        "agreement_version": rows[0].agreement_version if rows else None,
        "agreement_digest": agreement_digest(),
        "agreement_text": agreement_text(),
    }


@router.get("/me")
async def my_developers(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    actor = await _actor_or_403(db, request)
    rows = await list_by_identity(db, actor)
    return _mine(actor, rows)


@router.post("/prepare")
async def prepare_developer(
    body: PrepareDeveloperBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """把「待签开发者协议」交给客户端去签：协议正文、摘要与 message 都由服务端生成。

    前端只负责让钱包签这段 ``message`` 并把它原文显示给用户 —— 前后端各写一遍
    规范化，差一个字节就是白签。
    """
    actor = await _actor_or_403(db, request)
    try:
        entity = await assert_entity_verified(db, actor)
        payload = build_submission(
            {
                "real_name": body.real_name,
                "role_title": body.role_title,
                "contact_email": body.contact_email,
                "role": body.role,
            }
        )
    except DeveloperError as exc:
        raise _translate(exc) from exc

    message = build_signup_message(
        identity_id=actor,
        legal_name=str(entity.legal_name or ""),
        real_name=payload["real_name"],
        role_title=payload["role_title"],
    )
    return {
        "identity_id": actor,
        "legal_name": entity.legal_name or None,
        "official_domain": entity.official_domain or None,
        "real_name": payload["real_name"],
        "role_title": payload["role_title"],
        "contact_email": payload["contact_email"],
        "role": payload["developer_role"],
        "agreement_version": payload["agreement_version"],
        "agreement_digest": payload["agreement_digest"],
        "agreement_text": agreement_text(),
        "message": message,
    }


@router.post("/submit")
async def submit_developer(
    body: SubmitDeveloperBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    actor = await _actor_or_403(db, request)
    try:
        entity = await assert_entity_verified(db, actor)
        payload = build_submission(body.model_dump(), raw_payload=body.model_dump())
        message = build_signup_message(
            identity_id=actor,
            legal_name=str(entity.legal_name or ""),
            real_name=payload["real_name"],
            role_title=payload["role_title"],
        )
        signer = await verify_signer(
            db, identity_id=actor, message=message, signature=body.signature
        )
    except DeveloperError as exc:
        raise _translate(exc) from exc

    row = await find_by_signer(db, identity_id=actor, signer_wallet=signer)
    if row is None:
        row = SkillDeveloperModel(
            identity_id=actor,
            signer_wallet=signer,
            legal_name=str(entity.legal_name or ""),
            real_name=payload["real_name"],
            status="none",
        )
        db.add(row)
        await db.flush()
    try:
        assert_can_submit(str(row.status or "none"))
    except DeveloperError as exc:
        raise _translate(exc) from exc

    row.legal_name = str(entity.legal_name or "")
    row.real_name = payload["real_name"]
    row.role_title = payload["role_title"]
    row.contact_email = payload["contact_email"]
    row.developer_role = payload["developer_role"]
    row.agreement_version = payload["agreement_version"]
    row.agreement_digest = payload["agreement_digest"]
    row.signature = body.signature.strip()
    row.materials = payload["materials"]
    row.package_digest = payload["package_digest"]
    row.package_cipher = payload["package_cipher"]
    row.encryption = payload["encryption"]
    row.status = "pending"
    row.submitted_at = datetime.utcnow()
    row.reviewer_identity_id = None
    row.review_note = None
    row.verified_at = None
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


@router.post("/{developer_id}/review")
async def review_developer(
    developer_id: str,
    body: ReviewDeveloperBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("developer_id", developer_id)
    row = await _load(db, developer_id)
    if row is None:
        raise HTTPException(404, "developer profile not found")
    reviewer = await _require_reviewer(db, request, str(row.identity_id))
    try:
        assert_can_decide(str(row.status or "none"), body.decision)
    except DeveloperError as exc:
        raise _translate(exc) from exc

    if body.decision == "verified":
        mark_verified(row, reviewer_identity_id=reviewer, note=body.reason)
    else:
        mark_rejected(row, reviewer_identity_id=reviewer, note=body.reason)
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


@public_router.get("")
async def list_public_developers(
    identity_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """某个主体下**已通过复核**的开发者名单（尽调方不该先注册才能看）。"""
    validate_public_url_segment("identity_id", identity_id)
    rows = await list_by_identity(db, identity_id)
    verified = [r for r in rows if is_verified(r)]
    return {"identity_id": identity_id, "count": len(verified), "developers": [public_view(r) for r in verified]}


@public_router.get("/{developer_id}")
async def get_public_developer(
    developer_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    validate_public_url_segment("developer_id", developer_id)
    row = await _load(db, developer_id)
    if row is None:
        raise HTTPException(404, "developer profile not found")
    return public_view(row)


__all__ = ["router", "public_router", "empty_view"]