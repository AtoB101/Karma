"""Karma API — Identity profile and sub-identity management."""
from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import IdentityProfile, SubIdentity, SubIdentityStatus, SubIdentityType, VoucherStatus
from db.models.orm import IdentityProfileModel, SubIdentityModel, VoucherModel
from db.session import get_db
from services.agent_automation_policy import get_automation_policy, policy_to_dict, upsert_automation_policy

router = APIRouter()

MAX_ACTIVE_SUB_IDENTITIES = 2


class CreateSubIdentityRequest(BaseModel):
    sub_identity_type: SubIdentityType
    alias: str


@router.post("/{identity_id}/profile/init", response_model=IdentityProfile)
async def init_identity_profile(identity_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(IdentityProfileModel, identity_id)
    if row:
        return _profile_to_schema(row)

    row = IdentityProfileModel(
        identity_id=identity_id,
        display_id=_new_display_id(),
        legal_identity_status="unbound",
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    return _profile_to_schema(row)


@router.get("/{identity_id}/profile", response_model=IdentityProfile)
async def get_identity_profile(identity_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(IdentityProfileModel, identity_id)
    if not row:
        raise HTTPException(404, f"Identity profile {identity_id} not found")
    return _profile_to_schema(row)


@router.post("/{identity_id}/rotate-display-id", response_model=IdentityProfile)
async def rotate_display_id(identity_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(IdentityProfileModel, identity_id)
    if not row:
        raise HTTPException(404, f"Identity profile {identity_id} not found")
    row.display_id = _new_display_id()
    row.updated_at = datetime.utcnow()
    await db.flush()
    return _profile_to_schema(row)


@router.post("/{identity_id}/sub-identities", response_model=SubIdentity, status_code=201)
async def create_sub_identity(identity_id: str, body: CreateSubIdentityRequest, db: AsyncSession = Depends(get_db)):
    active_count_result = await db.execute(
        select(SubIdentityModel).where(
            SubIdentityModel.parent_identity_id == identity_id,
            SubIdentityModel.status == SubIdentityStatus.ACTIVE.value,
        )
    )
    active_rows = active_count_result.scalars().all()
    if len(active_rows) >= MAX_ACTIVE_SUB_IDENTITIES:
        raise HTTPException(409, "max active sub-identity limit reached (2)")

    row = SubIdentityModel(
        parent_identity_id=identity_id,
        sub_identity_type=body.sub_identity_type.value,
        alias=body.alias,
        status=SubIdentityStatus.ACTIVE.value,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    return _sub_to_schema(row)


@router.get("/{identity_id}/sub-identities", response_model=list[SubIdentity])
async def list_sub_identities(identity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SubIdentityModel)
        .where(SubIdentityModel.parent_identity_id == identity_id)
        .order_by(SubIdentityModel.created_at.asc())
    )
    rows = result.scalars().all()
    return [_sub_to_schema(row) for row in rows]


@router.delete("/{identity_id}/sub-identities/{sub_identity_id}", response_model=SubIdentity)
async def delete_sub_identity(identity_id: str, sub_identity_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(SubIdentityModel, sub_identity_id)
    if not row or row.parent_identity_id != identity_id:
        raise HTTPException(404, f"Sub-identity {sub_identity_id} not found for {identity_id}")
    if row.status == SubIdentityStatus.DELETED.value:
        return _sub_to_schema(row)

    active_voucher_result = await db.execute(
        select(VoucherModel.voucher_id).where(
            and_(
                or_(
                    VoucherModel.buyer_sub_identity_id == sub_identity_id,
                    VoucherModel.seller_sub_identity_id == sub_identity_id,
                ),
                VoucherModel.status.in_([VoucherStatus.CREATED.value, VoucherStatus.ACCEPTED.value]),
            )
        )
    )
    active_voucher = active_voucher_result.scalar_one_or_none()
    if active_voucher:
        raise HTTPException(409, f"sub-identity has active voucher linkage: {active_voucher}")

    row.status = SubIdentityStatus.DELETED.value
    row.deleted_at = datetime.utcnow()
    await db.flush()
    return _sub_to_schema(row)


def _new_display_id() -> str:
    return f"Karma-ID-{secrets.token_hex(4).upper()}"


def _profile_to_schema(row: IdentityProfileModel) -> IdentityProfile:
    return IdentityProfile(
        identity_id=row.identity_id,
        display_id=row.display_id,
        legal_identity_status=row.legal_identity_status,
        status=row.status,
        bound_wallet_address=getattr(row, "bound_wallet_address", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _sub_to_schema(row: SubIdentityModel) -> SubIdentity:
    return SubIdentity(
        sub_identity_id=row.sub_identity_id,
        parent_identity_id=row.parent_identity_id,
        sub_identity_type=SubIdentityType(row.sub_identity_type),
        alias=row.alias,
        status=SubIdentityStatus(row.status),
        created_at=row.created_at,
        deleted_at=row.deleted_at,
    )


class AutomationPolicyBody(BaseModel):
    auto_enabled: bool = False
    single_limit: float = Field(gt=0)
    daily_limit: float = Field(gt=0)
    permissions: list[str]
    high_risk_mode: str = "always"
    responsibility_acknowledged: bool = False
    preauth_enabled: bool = False
    allowed_task_types: list[str] = Field(default_factory=list)
    task_precision_min: float | None = None
    task_precision_max: float | None = None
    trusted_counterparty_ids: list[str] = Field(default_factory=list)
    payment_code_ttl_seconds: int = Field(default=3600, ge=60)
    responsibility_boundary_id: str | None = None
    auto_accept_incoming: bool = False
    auto_execute_pipeline: bool = False


@router.get("/{identity_id}/automation-policy")
async def get_automation_policy_route(identity_id: str, db: AsyncSession = Depends(get_db)):
    """Return saved AI automation policy (fund limits, permissions, responsibility ack) for Console."""
    row = await get_automation_policy(db, identity_id)
    if not row:
        return {"configured": False, "karma_identity_id": identity_id}
    return {"configured": True, **policy_to_dict(row)}


@router.put("/{identity_id}/automation-policy")
async def put_automation_policy_route(
    identity_id: str,
    body: AutomationPolicyBody,
    db: AsyncSession = Depends(get_db),
):
    """
    Persist operator AI automation bounds before Runtime Key mint / OpenClaw handoff.

    Enabling ``auto_enabled`` requires ``responsibility_acknowledged=true``.
    """
    row = await upsert_automation_policy(
        db,
        karma_identity_id=identity_id,
        auto_enabled=body.auto_enabled,
        single_limit=body.single_limit,
        daily_limit=body.daily_limit,
        permissions=body.permissions,
        high_risk_mode=body.high_risk_mode,
        responsibility_acknowledged=body.responsibility_acknowledged,
        preauth_enabled=body.preauth_enabled,
        allowed_task_types=body.allowed_task_types,
        task_precision_min=body.task_precision_min,
        task_precision_max=body.task_precision_max,
        trusted_counterparty_ids=body.trusted_counterparty_ids,
        payment_code_ttl_seconds=body.payment_code_ttl_seconds,
        responsibility_boundary_id=body.responsibility_boundary_id,
        auto_accept_incoming=body.auto_accept_incoming,
        auto_execute_pipeline=body.auto_execute_pipeline,
    )
    await db.commit()
    return {"configured": True, **policy_to_dict(row)}

