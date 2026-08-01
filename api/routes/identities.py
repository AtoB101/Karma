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
from services.identity_projection import (
    identity_id_from_did_agent,
    is_did_projection_identity_id,
    project_from_on_chain_did,
)

router = APIRouter()

MAX_ACTIVE_SUB_IDENTITIES = 2


class CreateSubIdentityRequest(BaseModel):
    sub_identity_type: SubIdentityType
    alias: str


class InitProfileRequest(BaseModel):
    wallet_address: str | None = Field(default=None, max_length=128)


class ProjectFromDidRequest(BaseModel):
    """Project IdentityProfile + AgentCard.agent_id from on-chain DID (SSOT)."""
    did_agent_address: str = Field(..., min_length=42, max_length=42)
    on_chain_did: str = Field(..., min_length=66, max_length=66)
    # Optional: caller-attested verifyDID result (RPC verification can be layered later)
    did_valid: bool = True


@router.post("/project-from-did", response_model=IdentityProfile)
async def project_identity_from_did(
    body: ProjectFromDidRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create or refresh a read-only IdentityProfile projection from on-chain DID.

    identity_id is derived as ``did:karma:{agent_address}`` and must not be chosen
    independently. AgentCard.agent_id uses the same projection string.
    """
    if not body.did_valid:
        raise HTTPException(400, "on-chain DID is not valid (verifyDID=false)")
    try:
        projection = project_from_on_chain_did(
            did_agent_address=body.did_agent_address,
            on_chain_did=body.on_chain_did,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    row = await db.get(IdentityProfileModel, projection.identity_id)
    if row is None:
        # Also reject conflicting on_chain_did bound to another identity
        existing_did = await db.execute(
            select(IdentityProfileModel).where(IdentityProfileModel.on_chain_did == projection.on_chain_did)
        )
        if existing_did.scalar_one_or_none():
            raise HTTPException(409, "on_chain_did already projected to another identity")
        row = IdentityProfileModel(
            identity_id=projection.identity_id,
            display_id=_new_display_id(),
            legal_identity_status="did_bound",
            status="active",
            bound_wallet_address=projection.did_agent_address,
            did_agent_address=projection.did_agent_address,
            on_chain_did=projection.on_chain_did,
            projection_readonly=True,
            projection_source="kya_did",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    else:
        if row.projection_readonly and row.on_chain_did and row.on_chain_did != projection.on_chain_did:
            raise HTTPException(409, "identity already bound to a different on_chain_did")
        row.did_agent_address = projection.did_agent_address
        row.on_chain_did = projection.on_chain_did
        row.bound_wallet_address = projection.did_agent_address
        row.projection_readonly = True
        row.projection_source = "kya_did"
        row.legal_identity_status = "did_bound"
        row.updated_at = datetime.utcnow()
    await db.flush()
    return _profile_to_schema(row)


@router.post("/{identity_id}/profile/init", response_model=IdentityProfile)
async def init_identity_profile(
    identity_id: str,
    body: InitProfileRequest = InitProfileRequest(),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(IdentityProfileModel, identity_id)
    if row:
        return _profile_to_schema(row)

    # If identity_id looks like a DID projection, keep wallet aligned
    did_agent = None
    if is_did_projection_identity_id(identity_id):
        from services.identity_projection import agent_address_from_identity_id

        did_agent = agent_address_from_identity_id(identity_id)
        if body.wallet_address and body.wallet_address.lower() != did_agent:
            raise HTTPException(
                400,
                "wallet_address must match DID projection agent address for did:karma: identities",
            )

    row = IdentityProfileModel(
        identity_id=identity_id,
        display_id=_new_display_id(),
        legal_identity_status="unbound" if not did_agent else "did_bound",
        status="active",
        bound_wallet_address=body.wallet_address or did_agent,
        did_agent_address=did_agent,
        projection_readonly=bool(did_agent),
        projection_source="kya_did" if did_agent else None,
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
    # display_id is the only mutable presentation field on DID projections
    row.display_id = _new_display_id()
    row.updated_at = datetime.utcnow()
    await db.flush()
    return _profile_to_schema(row)


@router.get("/{identity_id}/agent-card-id")
async def get_agent_card_id_projection(identity_id: str, db: AsyncSession = Depends(get_db)):
    """Return AgentCard.agent_id projection for this identity (DID SSOT)."""
    row = await db.get(IdentityProfileModel, identity_id)
    if not row:
        raise HTTPException(404, f"Identity profile {identity_id} not found")
    agent_card_id = row.identity_id
    if row.did_agent_address:
        agent_card_id = identity_id_from_did_agent(row.did_agent_address)
        if row.projection_readonly and agent_card_id != row.identity_id:
            raise HTTPException(409, "identity_id diverges from DID projection")
    return {
        "identity_id": row.identity_id,
        "agent_card_agent_id": agent_card_id,
        "did_agent_address": getattr(row, "did_agent_address", None),
        "on_chain_did": getattr(row, "on_chain_did", None),
        "projection_readonly": bool(getattr(row, "projection_readonly", False)),
        "source": getattr(row, "projection_source", None) or "legacy",
    }


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
        did_agent_address=getattr(row, "did_agent_address", None),
        on_chain_did=getattr(row, "on_chain_did", None),
        projection_readonly=bool(getattr(row, "projection_readonly", False)),
        projection_source=getattr(row, "projection_source", None),
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
    human_not_present_allowed: bool = False


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
        human_not_present_allowed=body.human_not_present_allowed,
    )
    await db.commit()
    return {"configured": True, **policy_to_dict(row)}

