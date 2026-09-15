"""Karma — 复核台（治理角色专用）。

- ``GET  /v1/reviews/pending``  待复核队列：主体认证 / 开发者实名 / 子身份 KYC
- ``POST /v1/reviews/precheck`` 提交前自检：把能自动判的先判掉（任何已登录身份可用）

队列只对**持有 verifier 类档案**的身份开放，且**不展示自己提交的东西**：
「不能复核自己」是路由层的硬规则，队列里混进去只会让人白点一次。

每条待办都带一份 ``auto_checks``：能自动判的（信用代码校验位、邮箱 MX、
邮箱域名与官网是否同一家）先判掉，人只看需要人看的部分。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import EntityVerificationModel, IdentityRoleProfile, SkillDeveloperModel
from db.session import get_db
from services import auto_verification
from services.identity_actor import resolve_actor_identity_id

router = APIRouter()

MAX_ITEMS_PER_KIND = 50


class PrecheckBody(BaseModel):
    kind: str = Field(..., pattern="^(entity|merchant|personal)$")
    subject: dict[str, Any] = Field(default_factory=dict)
    website_verified: bool = False


async def _require_verifier(db: AsyncSession, request: Request) -> str:
    """必须持有一个 active 的 verifier 类档案，否则 403。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to open the review queue")
    row = (
        await db.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == actor,
                IdentityRoleProfile.class_ == "verifier",
                IdentityRoleProfile.status == "active",
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(403, "only a verifier-class profile can open the review queue")
    return actor


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


async def _entity_items(db: AsyncSession, actor: str) -> tuple[list[dict], int]:
    rows = (
        await db.execute(
            select(EntityVerificationModel)
            .where(EntityVerificationModel.status == "pending")
            .order_by(EntityVerificationModel.submitted_at.asc())
            .limit(MAX_ITEMS_PER_KIND)
        )
    ).scalars().all()
    items, skipped = [], 0
    for row in rows:
        if row.identity_id == actor:
            skipped += 1
            continue
        checks = await asyncio.to_thread(
            auto_verification.precheck_entity,
            legal_name=row.legal_name,
            registration_no=row.registration_no,
            official_domain=row.official_domain,
            contact_email=row.contact_email,
            service_scope=row.service_scope,
            website_verified=bool(row.website_verified_at),
        )
        items.append(
            {
                "kind": "entity_verification",
                "item_id": row.identity_id,
                "owner_identity_id": row.identity_id,
                "title": row.legal_name or row.identity_id,
                "subtitle": " · ".join(
                    [p for p in (row.subject_type, row.official_domain, row.contact_email) if p]
                ),
                "submitted_at": _iso(row.submitted_at),
                "materials": [
                    {"name": c.get("name") or c.get("kind"), "kind": c.get("kind")} for c in (row.certifications or [])
                ],
                "has_package": bool(row.package_cipher),
                "auto_checks": checks,
                "decide": {
                    "target": row.identity_id,
                    "approve_path": f"/v1/identity/{row.identity_id}/entity-verification/verify",
                    "body_key": "decision",
                },
            }
        )
    return items, skipped


async def _developer_items(db: AsyncSession, actor: str) -> tuple[list[dict], int]:
    rows = (
        await db.execute(
            select(SkillDeveloperModel)
            .where(SkillDeveloperModel.status == "pending")
            .order_by(SkillDeveloperModel.created_at.asc())
            .limit(MAX_ITEMS_PER_KIND)
        )
    ).scalars().all()
    items, skipped = [], 0
    for row in rows:
        if row.identity_id == actor:
            skipped += 1
            continue
        checks = await asyncio.to_thread(
            auto_verification.precheck_personal,
            full_name=row.real_name,
            contact_email=row.contact_email,
        )
        items.append(
            {
                "kind": "developer",
                "item_id": row.developer_id,
                "owner_identity_id": row.identity_id,
                "title": row.real_name or row.developer_id,
                "subtitle": " · ".join([p for p in (row.role_title, row.legal_name, row.contact_email) if p]),
                "submitted_at": _iso(row.submitted_at or row.created_at),
                "materials": [],
                "has_package": bool(getattr(row, "package_cipher", None)),
                "auto_checks": checks,
                "decide": {
                    "target": row.developer_id,
                    "approve_path": f"/v1/developers/{row.developer_id}/review",
                    "body_key": "decision",
                },
            }
        )
    return items, skipped


async def _kyc_items(db: AsyncSession, actor: str) -> tuple[list[dict], int]:
    rows = (
        await db.execute(
            select(IdentityRoleProfile)
            .where(IdentityRoleProfile.kyc_status == "pending")
            .order_by(IdentityRoleProfile.updated_at.asc())
            .limit(MAX_ITEMS_PER_KIND)
        )
    ).scalars().all()
    items, skipped = [], 0
    for row in rows:
        if row.owner_identity_id == actor:
            skipped += 1
            continue
        payload = row.kyc_payload or {}
        if payload.get("kind") == "sole_proprietor":
            checks = await asyncio.to_thread(
                auto_verification.precheck_merchant,
                business_name=payload.get("business_name"),
                operator_name=payload.get("operator_name"),
                registration_no=payload.get("registration_no"),
                business_scope=payload.get("business_scope"),
                business_address=payload.get("business_address"),
                contact_email=payload.get("contact_email"),
            )
            title = payload.get("business_name") or row.display_name or row.profile_id
            subtitle = " · ".join([p for p in (payload.get("business_scope"), payload.get("business_address")) if p])
        else:
            checks = {"checks": [], "ok": True, "blocking_failures": [], "needs_human": ["manual"]}
            title = row.display_name or row.profile_id
            subtitle = payload.get("kind") or "子身份 KYC"
        items.append(
            {
                "kind": "role_profile_kyc",
                "item_id": row.profile_id,
                "owner_identity_id": row.owner_identity_id,
                "title": title,
                "subtitle": subtitle,
                "submitted_at": _iso(row.updated_at),
                "materials": [
                    {"name": d.get("name"), "kind": d.get("kind")} for d in (payload.get("docs") or [])
                ],
                "has_package": bool(payload.get("package_cipher")),
                "auto_checks": checks,
                "decide": {
                    "target": row.profile_id,
                    "approve_path": f"/v1/identity/role-profiles/{row.profile_id}/kyc/verify",
                    "body_key": "decision",
                },
            }
        )
    return items, skipped


@router.get("/pending")
async def pending_reviews(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    actor = await _require_verifier(db, request)
    entity_items, entity_skipped = await _entity_items(db, actor)
    developer_items, developer_skipped = await _developer_items(db, actor)
    kyc_items, kyc_skipped = await _kyc_items(db, actor)
    items = entity_items + developer_items + kyc_items
    # 需要人看的排前面：自动核验已经全绿的往后放。
    items.sort(key=lambda i: (bool(i["auto_checks"].get("ok")), i.get("submitted_at") or ""))
    return {
        "verifier_identity_id": actor,
        "total": len(items),
        "counts": {
            "entity_verification": len(entity_items),
            "developer": len(developer_items),
            "role_profile_kyc": len(kyc_items),
            "skipped_own": entity_skipped + developer_skipped + kyc_skipped,
        },
        "items": items,
    }


@router.post("/precheck")
async def precheck(
    body: PrecheckBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """提交前自检。登录即可用，不需要治理角色 —— 它只读输入、只写结论。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to run precheck")
    subject = body.subject or {}
    if body.kind == "entity":
        result = await asyncio.to_thread(
            auto_verification.precheck_entity,
            legal_name=subject.get("legal_name"),
            registration_no=subject.get("registration_no"),
            official_domain=subject.get("official_domain"),
            contact_email=subject.get("contact_email"),
            service_scope=subject.get("service_scope"),
            website_verified=body.website_verified,
        )
    elif body.kind == "merchant":
        result = await asyncio.to_thread(
            auto_verification.precheck_merchant,
            business_name=subject.get("business_name"),
            operator_name=subject.get("operator_name"),
            registration_no=subject.get("registration_no"),
            business_scope=subject.get("business_scope"),
            business_address=subject.get("business_address"),
            contact_email=subject.get("contact_email"),
        )
    else:
        result = await asyncio.to_thread(
            auto_verification.precheck_personal,
            full_name=subject.get("full_name"),
            contact_email=subject.get("contact_email"),
        )
    return {"kind": body.kind, **result}
