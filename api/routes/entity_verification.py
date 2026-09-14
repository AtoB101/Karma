"""Karma — 主体资质认证路由（数据 API / 技能提供方）。

- ``GET  /v1/identity/{id}/entity-verification``                    本人看全量，他人看公开视图
- ``POST /v1/identity/{id}/entity-verification/website-challenge``  生成官网校验文件内容
- ``POST /v1/identity/{id}/entity-verification/website-verify``     服务端回读官网校验文件
- ``POST /v1/identity/{id}/entity-verification/submit``             提交主体 + 资质（密文包 + 摘要）
- ``POST /v1/identity/{id}/entity-verification/verify``             verifier 类档案复核
- ``GET  /v1/entities/{id}``                                        对外公开的工商信息

服务端全程只存密文包 + 摘要；明文资质在服务层就被按名拒掉（services/entity_verification）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import EntityVerificationModel, IdentityRoleProfile
from db.session import get_db
from services.entity_verification import (
    EntityVerificationError,
    assert_can_decide,
    assert_can_submit,
    assert_website_token,
    build_submission,
    empty_view,
    fetch_website_proof,
    issue_website_challenge,
    mark_rejected,
    mark_verified,
    normalize_domain,
    owner_view,
    parse_proof_body,
    public_view,
    website_digest,
)
from services.identity_actor import resolve_actor_identity_id
from services.path_param_safety import validate_public_url_segment

router = APIRouter()
public_router = APIRouter()


class WebsiteChallengeBody(BaseModel):
    model_config = {"extra": "allow"}

    official_domain: str | None = Field(default=None, max_length=255)


class SubmitEntityBody(BaseModel):
    # 与自然人认证同一策略：允许未知字段，夹带的明文由服务层指名拒掉，
    # 而不是被 pydantic 静默丢弃（丢掉会让"我传了明文"变成看不见的事实）。
    model_config = {"extra": "allow"}

    subject_type: str | None = Field(default=None, max_length=16)
    legal_name: str = Field(min_length=1, max_length=200)
    registration_no: str | None = Field(default=None, max_length=64)
    jurisdiction: str | None = Field(default=None, max_length=64)
    legal_rep: str | None = Field(default=None, max_length=120)
    official_domain: str = Field(min_length=4, max_length=255)
    contact_email: str = Field(min_length=3, max_length=200)
    service_category: str | None = Field(default=None, max_length=64)
    service_scope: str = Field(min_length=10, max_length=2000)
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    doc_digest: str = Field(min_length=1, max_length=128)
    package_digest: str = Field(min_length=1, max_length=128)
    package_cipher: str = Field(min_length=1, max_length=8_000_000)
    encryption: dict[str, Any] = Field(default_factory=dict)
    extracted: dict[str, Any] = Field(default_factory=dict)


class VerifyEntityBody(BaseModel):
    decision: str = Field(..., pattern="^(verified|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)


def _translate(exc: EntityVerificationError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _require_owner(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to manage entity verification")
    if actor != identity_id:
        raise HTTPException(403, "only the identity owner can manage its entity verification")
    return actor


async def _require_reviewer(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to review entity verification")
    if actor == identity_id:
        raise HTTPException(403, "an identity cannot review its own entity verification")
    row = (
        await db.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == actor,
                IdentityRoleProfile.class_ == "verifier",
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(403, "only a verifier-class profile can review entity verification")
    return actor


async def _load(db: AsyncSession, identity_id: str) -> EntityVerificationModel | None:
    return await db.get(EntityVerificationModel, identity_id)


async def _assert_domain_unclaimed(
    db: AsyncSession, *, identity_id: str, domain: str
) -> None:
    """一个官网域名只能认给一个主体 —— 否则两家公司能拿同一个域名各自上架。"""
    row = (
        await db.execute(
            select(EntityVerificationModel).where(
                EntityVerificationModel.official_domain == domain,
                EntityVerificationModel.status == "verified",
                EntityVerificationModel.identity_id != identity_id,
            )
        )
    ).scalars().first()
    if row is not None:
        raise HTTPException(
            409,
            f"官网域名 {domain} 已经认证给另一个主体；如果你确实拥有它，请联系运营复核",
        )


@router.get("/{identity_id}/entity-verification")
async def get_entity_verification(
    identity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    row = await _load(db, identity_id)
    actor = await resolve_actor_identity_id(db, request)
    if row is None:
        if actor == identity_id:
            return empty_view(identity_id)
        return {"identity_id": identity_id, "status": "none", "verified_at": None}
    if actor == identity_id:
        return owner_view(row)
    return public_view(row)


@router.post("/{identity_id}/entity-verification/website-challenge")
async def create_website_challenge(
    identity_id: str,
    body: WebsiteChallengeBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """发一个一次性 token：用户把它放到官网固定路径下，我们再回读比对。"""
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)

    row = await _load(db, identity_id)
    raw_domain = (body.official_domain or (row.official_domain if row else "") or "").strip()
    try:
        domain = normalize_domain(raw_domain)
    except EntityVerificationError as exc:
        raise _translate(exc) from exc

    if row is None:
        row = EntityVerificationModel(identity_id=identity_id, status="draft")
        db.add(row)
    if str(row.status or "none") == "verified":
        raise HTTPException(409, "主体已认证通过；如需更换官网请先联系运营复核")

    challenge = issue_website_challenge(domain)
    row.official_domain = domain
    row.website_token = challenge["token"]
    row.website_challenge_at = datetime.utcnow()
    row.website_verified_at = None
    row.website_digest = None
    if str(row.status or "none") in ("none", "verified"):
        row.status = "draft"
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return {**owner_view(row), "challenge": challenge}


@router.post("/{identity_id}/entity-verification/website-verify")
async def verify_website(
    identity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)

    row = await _load(db, identity_id)
    if row is None or not (row.official_domain or "").strip():
        raise HTTPException(409, "请先生成官网校验文件（还没有 official_domain）")

    try:
        body_text = await fetch_website_proof(str(row.official_domain))
        found = parse_proof_body(body_text)
        assert_website_token(found, row.website_token, challenged_at=row.website_challenge_at)
    except EntityVerificationError as exc:
        raise _translate(exc) from exc

    row.website_verified_at = datetime.utcnow()
    row.website_digest = website_digest(str(row.official_domain), str(row.website_token))
    row.updated_at = datetime.utcnow()
    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


@router.post("/{identity_id}/entity-verification/submit")
async def submit_entity_verification(
    identity_id: str,
    body: SubmitEntityBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)

    try:
        payload = build_submission(body.model_dump(), raw_payload=body.model_dump())
    except EntityVerificationError as exc:
        raise _translate(exc) from exc

    row = await _load(db, identity_id)
    current = row.status if row else "none"
    try:
        assert_can_submit(current)
    except EntityVerificationError as exc:
        raise _translate(exc) from exc

    if row is None:
        row = EntityVerificationModel(identity_id=identity_id, status="draft")
        db.add(row)

    # 官网控制权必须是**验证过**的：这是"这家公司真的是它"的唯一硬证据。
    await _assert_domain_unclaimed(db, identity_id=identity_id, domain=payload["official_domain"])
    if not row.website_verified_at:
        raise HTTPException(409, "请先完成官网控制权校验（生成校验文件 → 回读通过）再提交审核")
    if str(row.official_domain) != payload["official_domain"]:
        raise HTTPException(
            409,
            f"提交的 official_domain（{payload['official_domain']}）与已验证的官网"
            f"（{row.official_domain}）不一致，请重新走一次官网校验",
        )

    for key, value in payload.items():
        setattr(row, key, value)
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


@router.post("/{identity_id}/entity-verification/verify")
async def review_entity_verification(
    identity_id: str,
    body: VerifyEntityBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    reviewer = await _require_reviewer(db, request, identity_id)

    row = await _load(db, identity_id)
    if row is None:
        raise HTTPException(404, "entity verification not found")

    try:
        assert_can_decide(row.status, body.decision)
    except EntityVerificationError as exc:
        raise _translate(exc) from exc

    if body.decision == "verified":
        await _assert_domain_unclaimed(
            db, identity_id=identity_id, domain=str(row.official_domain or "")
        )
        mark_verified(row, reviewer_identity_id=reviewer, note=body.reason)
    else:
        mark_rejected(row, reviewer_identity_id=reviewer, note=body.reason)
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


@public_router.get("/{identity_id}")
async def get_public_entity(identity_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """任何人都能查到的主体公开信息（尽调用）。"""
    validate_public_url_segment("identity_id", identity_id)
    row = await _load(db, identity_id)
    if row is None:
        raise HTTPException(404, "entity not found")
    return public_view(row)