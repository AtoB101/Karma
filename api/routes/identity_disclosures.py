"""
Karma — Identity Role Profile Authorized Disclosure (P3).

企业（enterprise）档案默认 `visibility=private`，明细默认不可公开查询。本模块实现：
- 授权披露：档案 owner 可对特定授权方开放「某几笔明细」（scope=transaction, task_id）
  或整本台账（scope=ledger）。
- 私有台账查询：`GET /{profile_id}/ledger` 仅 owner 或已授权方可见；
  授权方只能看到被披露的 task_id。

不涉及 KYC 流转与 capacity 独立额度（属后续）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import IdentityDisclosureModel, IdentityRoleProfile, SettlementModel
from db.session import get_db
from services.identity_actor import resolve_actor_identity_id
from services.path_param_safety import validate_public_url_segment

router = APIRouter()

_SCOPE_PATTERN = "^(transaction|ledger)$"


class CreateDisclosureBody(BaseModel):
    authorized_identity_id: str = Field(..., min_length=1, max_length=128)
    task_id: str | None = Field(default=None, max_length=64)
    scope: str = Field(default="transaction", pattern=_SCOPE_PATTERN)


def _serialize_disclosure(row: IdentityDisclosureModel) -> dict:
    return {
        "disclosure_id": row.disclosure_id,
        "profile_id": row.profile_id,
        "authorized_identity_id": row.authorized_identity_id,
        "task_id": row.task_id,
        "scope": row.scope,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _get_profile(db: AsyncSession, profile_id: str) -> IdentityRoleProfile:
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")
    return row


async def _require_owner(db: AsyncSession, request: Request, profile: IdentityRoleProfile) -> None:
    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != profile.owner_identity_id:
        raise HTTPException(403, "only the profile owner can manage disclosures")


@router.post("/{profile_id}/disclosures", status_code=201)
async def create_disclosure(
    profile_id: str,
    body: CreateDisclosureBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("profile_id", profile_id)
    profile = await _get_profile(db, profile_id)
    await _require_owner(db, request, profile)

    if body.scope == "transaction":
        if not body.task_id:
            raise HTTPException(400, "task_id is required when scope=transaction")
        validate_public_url_segment("task_id", body.task_id)
        task_id = body.task_id
    else:
        task_id = None

    row = IdentityDisclosureModel(
        profile_id=profile_id,
        authorized_identity_id=body.authorized_identity_id.strip(),
        task_id=task_id,
        scope=body.scope,
        status="active",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _serialize_disclosure(row)


@router.get("/{profile_id}/disclosures")
async def list_disclosures(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("profile_id", profile_id)
    profile = await _get_profile(db, profile_id)
    await _require_owner(db, request, profile)

    result = await db.execute(
        select(IdentityDisclosureModel)
        .where(IdentityDisclosureModel.profile_id == profile_id)
        .order_by(IdentityDisclosureModel.created_at.desc())
    )
    rows = result.scalars().all()
    return {"disclosures": [_serialize_disclosure(r) for r in rows]}


@router.delete("/{profile_id}/disclosures/{disclosure_id}")
async def revoke_disclosure(
    profile_id: str,
    disclosure_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("profile_id", profile_id)
    validate_public_url_segment("disclosure_id", disclosure_id)
    profile = await _get_profile(db, profile_id)
    await _require_owner(db, request, profile)

    row = await db.get(IdentityDisclosureModel, disclosure_id)
    if not row or row.profile_id != profile_id:
        raise HTTPException(404, "disclosure not found")
    row.status = "revoked"
    row.updated_at = datetime.utcnow()
    await db.flush()
    return _serialize_disclosure(row)


async def _disclosed_task_ids(db: AsyncSession, profile_id: str, actor: str) -> list[str] | None:
    """task_ids disclosed to `actor`; None means whole-ledger access granted."""
    result = await db.execute(
        select(IdentityDisclosureModel).where(
            IdentityDisclosureModel.profile_id == profile_id,
            IdentityDisclosureModel.authorized_identity_id == actor,
            IdentityDisclosureModel.status == "active",
        )
    )
    rows = result.scalars().all()
    if any(r.scope == "ledger" for r in rows):
        return None
    return [r.task_id for r in rows if r.task_id]


@router.get("/{profile_id}/ledger")
async def get_profile_ledger(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("profile_id", profile_id)
    profile = await _get_profile(db, profile_id)
    actor = await resolve_actor_identity_id(db, request)

    allowed: list[str] | None = None  # None => all transactions
    if profile.visibility == "private":
        if not actor:
            raise HTTPException(403, "authentication required for private ledger")
        if actor == profile.owner_identity_id:
            allowed = None
        else:
            allowed = await _disclosed_task_ids(db, profile_id, actor)
            if allowed is not None and not allowed:
                raise HTTPException(403, "not authorized to view this private ledger")

    result = await db.execute(
        select(SettlementModel)
        .where(SettlementModel.profile_id == profile_id)
        .order_by(SettlementModel.created_at.desc())
    )
    rows = list(result.scalars().all())
    if allowed is not None:
        rows = [r for r in rows if r.task_id in allowed]

    transactions = [
        {
            "task_id": r.task_id,
            "settlement_id": r.settlement_id,
            "escrow_amount": r.escrow_amount,
            "currency": r.currency,
            "status": r.status,
            "client_agent_id": r.client_agent_id,
            "worker_agent_id": r.worker_agent_id,
            "released_amount": r.released_amount,
            "refunded_amount": r.refunded_amount,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {
        "profile_id": profile_id,
        "visibility": profile.visibility,
        "class": profile.class_,
        "transactions": transactions,
    }
