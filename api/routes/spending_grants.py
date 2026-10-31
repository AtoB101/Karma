"""Spending grant API — owner-signed budgeted authorization for agents."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from api.middleware.auth import get_current_agent_id
from db.models.orm import SpendingGrantModel
from services import grant_approval
from services import spending_grant as grants
from services.identity_wallet_binding import resolve_identity_id_by_wallet
from services.runtime_wallet import verify_personal_message

router = APIRouter(prefix="/v1/spending-grants", tags=["SpendingGrants"])

_ACTION_LABELS = {"revoke": "Revoke", "pause": "Pause", "resume": "Resume", "reduce": "Reduce"}


class CreateGrantBody(BaseModel):
    grant_id: str = Field(min_length=1, max_length=64)
    wallet_address: str = Field(min_length=42, max_length=42)
    wallet_signature: str = Field(min_length=132, max_length=132)
    agent_id: str = Field(min_length=1, max_length=128)
    agent_name: str | None = Field(default=None, max_length=128)
    agent_public_key: str | None = Field(default=None, max_length=256)
    currency: str = Field(default="USDC", max_length=16)
    token_address: str | None = Field(default=None, max_length=42)
    total_limit: float = Field(gt=0)
    per_tx_limit: float = Field(gt=0)
    purpose_scope: list[str] = Field(default_factory=list)
    expires_at: str | None = Field(default=None, max_length=64)
    nonce: str = Field(min_length=8, max_length=64)


class GrantActionBody(BaseModel):
    wallet_address: str = Field(min_length=42, max_length=42)
    wallet_signature: str = Field(min_length=132, max_length=132)
    reason: str | None = Field(default=None, max_length=256)


class ReduceGrantBody(BaseModel):
    wallet_address: str = Field(min_length=42, max_length=42)
    wallet_signature: str = Field(min_length=132, max_length=132)
    new_total_limit: float = Field(gt=0)
    reason: str | None = Field(default=None, max_length=256)


def _action_message(action: str, grant_id: str, wallet_address: str) -> str:
    label = _ACTION_LABELS.get(action, action)
    return "\n".join(
        [
            f"Karma Spending Grant {label}",
            f"grant_id:{grant_id}",
            f"wallet_address:{wallet_address}",
        ]
    )


def _reduce_message(grant_id: str, wallet_address: str, new_total_limit: float) -> str:
    return "\n".join(
        [
            "Karma Spending Grant Reduce",
            f"grant_id:{grant_id}",
            f"wallet_address:{wallet_address}",
            f"new_total_limit:{new_total_limit}",
        ]
    )


def _verify_owner(action: str, grant: SpendingGrantModel, body: GrantActionBody) -> None:
    verify_personal_message(
        message=_action_message(action, grant.grant_id, body.wallet_address),
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    if grant.owner_wallet_address.lower() != body.wallet_address.lower():
        raise HTTPException(403, "wallet is not the grant owner")


@router.post("")
async def create_grant(body: CreateGrantBody, db: AsyncSession = Depends(get_db)):
    owner_identity_id = await resolve_identity_id_by_wallet(db, body.wallet_address)
    if not owner_identity_id:
        raise HTTPException(
            403,
            "wallet is not bound to a Karma identity — connect this wallet in the console first",
        )
    grant = await grants.create_grant(
        db,
        owner_identity_id=owner_identity_id,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        agent_public_key=body.agent_public_key,
        currency=body.currency,
        token_address=body.token_address,
        total_limit=body.total_limit,
        per_tx_limit=body.per_tx_limit,
        purpose_scope=body.purpose_scope,
        expires_at=body.expires_at,
        nonce=body.nonce,
        grant_id=body.grant_id,
    )
    await db.commit()
    return grants._grant_to_dict(grant)


@router.get("/check")
async def check_grant(
    agent_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    rows = await grants.list_grants(db, agent_id=agent_id)
    active = [grants._grant_to_dict(g) for g in rows if g.status == "active" and not grants._expired(g)]
    return {"agent_id": agent_id, "grants": active, "count": len(active)}


@router.get("")
async def list_grants(
    owner_identity_id: str | None = Query(default=None, max_length=128),
    agent_id: str | None = Query(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    rows = await grants.list_grants(db, owner_identity_id=owner_identity_id, agent_id=agent_id)
    return {"grants": [grants._grant_to_dict(g) for g in rows], "count": len(rows)}


@router.get("/events")
async def list_events(
    grant_id: str | None = Query(default=None, max_length=64),
    owner_identity_id: str | None = Query(default=None, max_length=128),
    agent_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = await grants.list_grant_events(
        db,
        grant_id=grant_id,
        owner_identity_id=owner_identity_id,
        agent_id=agent_id,
        limit=limit,
    )
    return {"events": [grants._event_to_dict(e) for e in rows], "count": len(rows)}


@router.get("/{grant_id}")
async def get_grant(grant_id: str, db: AsyncSession = Depends(get_db)):
    grant = await grants.get_grant(db, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    return grants._grant_to_dict(grant)


@router.post("/{grant_id}/revoke")
async def revoke_grant(grant_id: str, body: GrantActionBody, db: AsyncSession = Depends(get_db)):
    grant = await grants.get_grant(db, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    _verify_owner("revoke", grant, body)
    await grants.revoke_grant(db, grant=grant, reason=body.reason or "")
    await db.commit()
    return grants._grant_to_dict(grant)


@router.post("/{grant_id}/pause")
async def pause_grant(grant_id: str, body: GrantActionBody, db: AsyncSession = Depends(get_db)):
    grant = await grants.get_grant(db, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    _verify_owner("pause", grant, body)
    await grants.pause_grant(db, grant=grant)
    await db.commit()
    return grants._grant_to_dict(grant)


@router.post("/{grant_id}/resume")
async def resume_grant(grant_id: str, body: GrantActionBody, db: AsyncSession = Depends(get_db)):
    grant = await grants.get_grant(db, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    _verify_owner("resume", grant, body)
    await grants.resume_grant(db, grant=grant)
    await db.commit()
    return grants._grant_to_dict(grant)


@router.post("/{grant_id}/reduce")
async def reduce_grant(grant_id: str, body: ReduceGrantBody, db: AsyncSession = Depends(get_db)):
    grant = await grants.get_grant(db, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    verify_personal_message(
        message=_reduce_message(grant.grant_id, body.wallet_address, body.new_total_limit),
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    if grant.owner_wallet_address.lower() != body.wallet_address.lower():
        raise HTTPException(403, "wallet is not the grant owner")
    await grants.reduce_grant(db, grant=grant, new_total_limit=body.new_total_limit, reason=body.reason)
    await db.commit()
    return grants._grant_to_dict(grant)


@router.get("/{grant_id}/action-message")
async def action_message(
    grant_id: str,
    action: str = Query(min_length=1, max_length=16),
    wallet_address: str = Query(min_length=42, max_length=42),
    new_total_limit: float | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
):
    """The exact EIP-191 text the owner signs for a management action."""
    grant = await grants.get_grant(db, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    if action == "reduce":
        if new_total_limit is None:
            raise HTTPException(400, "new_total_limit is required for reduce")
        message = _reduce_message(grant.grant_id, wallet_address, new_total_limit)
    elif action in _ACTION_LABELS:
        message = _action_message(action, grant.grant_id, wallet_address)
    else:
        raise HTTPException(400, f"unsupported action: {action}")
    return {"grant_id": grant.grant_id, "action": action, "message": message}



class ApprovalRequestBody(BaseModel):
    agent_name: str = Field(min_length=1, max_length=128)
    agent_public_key: str | None = Field(default=None, max_length=256)
    currency: str = Field(default="USDC", max_length=16)
    token_address: str | None = Field(default=None, max_length=42)
    total_limit: float = Field(gt=0)
    per_tx_limit: float = Field(gt=0)
    purpose_scope: list[str] = Field(default_factory=list)
    expires_at: str | None = Field(default=None, max_length=64)


class ApproveBody(BaseModel):
    confirmation_code: str = Field(min_length=6, max_length=16)
    wallet_address: str = Field(min_length=42, max_length=42)
    wallet_signature: str = Field(min_length=132, max_length=132)


@router.post("/approval-request")
async def request_approval(body: ApprovalRequestBody, actor: str = Depends(get_current_agent_id)):
    """Agent opens an owner approval request for a spending grant."""
    return grant_approval.issue_grant_approval(
        agent_id=actor,
        agent_name=body.agent_name,
        agent_public_key=body.agent_public_key,
        currency=body.currency,
        token_address=body.token_address,
        total_limit=body.total_limit,
        per_tx_limit=body.per_tx_limit,
        purpose_scope=body.purpose_scope,
        expires_at=body.expires_at,
    )



approval_router = APIRouter(prefix="/v1/spending-grants", tags=["SpendingGrants"])


@approval_router.get("/approval/{challenge_id}")
async def get_approval(challenge_id: str):
    """Owner-side read of a pending approval request (capability URL)."""
    return grant_approval.public_view(challenge_id)


@approval_router.post("/approval/{challenge_id}/approve")
async def approve_approval(
    challenge_id: str,
    body: ApproveBody,
    db: AsyncSession = Depends(get_db),
):
    """Owner signs the grant terms with their wallet; the grant is created on success."""
    grant = await grant_approval.approve_grant_approval(
        db,
        challenge_id=challenge_id,
        confirmation_code=body.confirmation_code,
        wallet_address=body.wallet_address,
        wallet_signature=body.wallet_signature,
    )
    await db.commit()
    return grant


@approval_router.get("/approval/{challenge_id}/sign-message")
async def approval_sign_message(
    challenge_id: str,
    wallet_address: str = Query(min_length=42, max_length=42),
):
    """The exact EIP-191 text the owner must sign with this wallet."""
    return {"challenge_id": challenge_id, "message": grant_approval.sign_message_for(challenge_id, wallet_address)}
