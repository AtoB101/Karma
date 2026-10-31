"""Spending grant API — owner-signed budgeted authorization for agents."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models.orm import SpendingGrantModel
from services import spending_grant as grants
from services.identity_wallet_binding import resolve_identity_id_by_wallet
from services.runtime_wallet import verify_personal_message

router = APIRouter(prefix="/v1/spending-grants", tags=["SpendingGrants"])

_ACTION_LABELS = {"revoke": "Revoke", "pause": "Pause", "resume": "Resume"}


class CreateGrantBody(BaseModel):
    grant_id: str = Field(min_length=1, max_length=64)
    wallet_address: str = Field(min_length=42, max_length=42)
    wallet_signature: str = Field(min_length=132, max_length=132)
    agent_id: str = Field(min_length=1, max_length=128)
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


def _action_message(action: str, grant_id: str, wallet_address: str) -> str:
    label = _ACTION_LABELS.get(action, action)
    return "\n".join(
        [
            f"Karma Spending Grant {label}",
            f"grant_id:{grant_id}",
            f"wallet_address:{wallet_address}",
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
