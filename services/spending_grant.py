"""Owner-approved spending grants (budgeted authorization).

A *grant* is the durable allowance an owner signs for an agent: total limit,
per-transaction limit, currency/token, expiry, and purpose scope. The owner
approves it with a wallet signature over the canonical terms (EIP-191 personal
message), so the grant is self-certifying rather than just a server-side row.

This module provides the primitive plus the hard server-side gate: every spend
entry point must call :func:`assert_spend_allowed` before moving money, and
:func:`record_spend` after the money actually moved. Rejections update the grant
row so they stay queryable.
"""
from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import SpendingGrantModel

logger = structlog.get_logger(__name__)

#: Decimal base for the on-chain USDC integer amounts (6 decimals).
_TOKEN_DECIMALS = 6

ACTIVE_STATUS = "active"


def build_grant_message(
    *,
    grant_id: str,
    wallet_address: str,
    agent_id: str,
    agent_public_key: str | None,
    currency: str,
    token_address: str | None,
    total_limit: float,
    per_tx_limit: float,
    purpose_scope: list[str],
    expires_at: str | None,
    nonce: str,
) -> str:
    """Canonical human-readable text the owner signs. Rebuilt byte-for-byte at verify time."""
    if expires_at is None or not str(expires_at).strip():
        expire_line = "never"
    else:
        expire_line = str(expires_at).strip()
    lines = [
        "Karma Spending Grant",
        f"grant_id:{grant_id}",
        f"wallet_address:{wallet_address}",
        f"agent_id:{agent_id}",
        f"agent_public_key:{agent_public_key or ''}",
        f"currency:{currency}",
        f"token_address:{token_address or ''}",
        f"total_limit:{total_limit}",
        f"per_tx_limit:{per_tx_limit}",
        f"purpose_scope:{','.join(sorted(purpose_scope or []))}",
        f"expires_at:{expire_line}",
        f"nonce:{nonce}",
    ]
    return "\n".join(lines)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _expired(grant: SpendingGrantModel) -> bool:
    return bool(grant.expires_at and grant.expires_at < _utcnow())


async def create_grant(
    db: AsyncSession,
    *,
    owner_identity_id: str,
    wallet_address: str,
    wallet_signature: str,
    agent_id: str,
    agent_public_key: str | None,
    currency: str,
    token_address: str | None,
    total_limit: float,
    per_tx_limit: float,
    purpose_scope: list[str],
    expires_at: str | None,
    nonce: str,
    grant_id: str,
) -> SpendingGrantModel:
    """Verify the owner's signature and persist a new grant."""
    if total_limit <= 0:
        raise HTTPException(400, "total_limit must be positive")
    if per_tx_limit <= 0:
        raise HTTPException(400, "per_tx_limit must be positive")
    if per_tx_limit > total_limit:
        raise HTTPException(400, "per_tx_limit cannot exceed total_limit")

    message = build_grant_message(
        grant_id=grant_id,
        wallet_address=wallet_address,
        agent_id=agent_id,
        agent_public_key=agent_public_key,
        currency=currency,
        token_address=token_address,
        total_limit=total_limit,
        per_tx_limit=per_tx_limit,
        purpose_scope=purpose_scope,
        expires_at=expires_at,
        nonce=nonce,
    )
    from services.runtime_wallet import verify_personal_message

    verify_personal_message(
        message=message,
        wallet_address=wallet_address,
        wallet_signature=wallet_signature,
    )

    existing = await db.execute(
        select(SpendingGrantModel).where(SpendingGrantModel.grant_id == grant_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, "grant_id already exists")

    expires_dt: datetime | None = None
    if expires_at and str(expires_at).strip():
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            expires_dt = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError as exc:
            raise HTTPException(400, "expires_at must be an ISO-8601 datetime") from exc
        if expires_dt <= _utcnow():
            raise HTTPException(400, "expires_at must be in the future")

    grant = SpendingGrantModel(
        grant_id=grant_id,
        owner_identity_id=owner_identity_id,
        owner_wallet_address=wallet_address.lower(),
        agent_id=agent_id,
        agent_public_key=agent_public_key,
        currency=currency or "USDC",
        token_address=token_address,
        total_limit=total_limit,
        per_tx_limit=per_tx_limit,
        used_amount=0.0,
        purpose_scope=purpose_scope or [],
        status=ACTIVE_STATUS,
        expires_at=expires_dt,
        nonce=nonce,
        signature=wallet_signature,
        signed_message=message,
    )
    db.add(grant)
    await db.flush()
    logger.info(
        "spending_grant_created",
        grant_id=grant_id,
        owner_identity_id=owner_identity_id,
        agent_id=agent_id,
        total_limit=total_limit,
        per_tx_limit=per_tx_limit,
    )
    return grant


async def get_grant(db: AsyncSession, grant_id: str) -> SpendingGrantModel | None:
    res = await db.execute(
        select(SpendingGrantModel).where(SpendingGrantModel.grant_id == grant_id)
    )
    return res.scalar_one_or_none()


async def list_grants(db: AsyncSession, *, owner_identity_id: str | None = None, agent_id: str | None = None) -> list[SpendingGrantModel]:
    stmt = select(SpendingGrantModel)
    if owner_identity_id:
        stmt = stmt.where(SpendingGrantModel.owner_identity_id == owner_identity_id)
    if agent_id:
        stmt = stmt.where(SpendingGrantModel.agent_id == agent_id)
    stmt = stmt.order_by(SpendingGrantModel.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars())


def _grant_to_dict(grant: SpendingGrantModel) -> dict[str, Any]:
    return {
        "grant_id": grant.grant_id,
        "owner_identity_id": grant.owner_identity_id,
        "owner_wallet_address": grant.owner_wallet_address,
        "agent_id": grant.agent_id,
        "agent_public_key": grant.agent_public_key,
        "currency": grant.currency,
        "token_address": grant.token_address,
        "total_limit": grant.total_limit,
        "per_tx_limit": grant.per_tx_limit,
        "used_amount": grant.used_amount,
        "remaining": round(grant.total_limit - grant.used_amount, 6),
        "purpose_scope": grant.purpose_scope,
        "status": grant.status,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
        "last_used_at": grant.last_used_at.isoformat() if grant.last_used_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revoke_reason": grant.revoke_reason,
    }


async def assert_spend_allowed(
    db: AsyncSession,
    *,
    agent_id: str,
    token_address: str | None,
    amount: float,
) -> SpendingGrantModel:
    """Hard server-side gate: reject spend with no active, unexpired, sufficient grant."""
    res = await db.execute(
        select(SpendingGrantModel)
        .where(SpendingGrantModel.agent_id == agent_id)
        .where(SpendingGrantModel.status == ACTIVE_STATUS)
        .order_by(SpendingGrantModel.created_at.desc())
    )
    grants = list(res.scalars())
    if not grants:
        _deny(grants=None, agent_id=agent_id, reason="no active spending grant")
    for grant in grants:
        if _expired(grant):
            continue
        if grant.token_address and token_address and grant.token_address.lower() != token_address.lower():
            continue
        if amount > grant.per_tx_limit + 1e-9:
            continue
        remaining = grant.total_limit - grant.used_amount
        if amount > remaining + 1e-9:
            continue
        return grant
    _deny(grants=grants, agent_id=agent_id, reason="no grant covers this spend")


def _deny(*, grants: list[SpendingGrantModel] | None, agent_id: str, reason: str) -> None:
    logger.warning(
        "spending_grant_denied",
        agent_id=agent_id,
        reason=reason,
    )
    raise HTTPException(status_code=403, detail=f"spending grant denied: {reason}")


async def record_spend(
    db: AsyncSession,
    *,
    grant_id: str,
    amount: float,
) -> None:
    """Atomically increment the grant's used_amount after money actually moved."""
    await db.execute(
        update(SpendingGrantModel)
        .where(SpendingGrantModel.grant_id == grant_id)
        .values(used_amount=SpendingGrantModel.used_amount + amount, last_used_at=_utcnow())
    )
    await db.flush()


async def revoke_grant(db: AsyncSession, *, grant: SpendingGrantModel, reason: str) -> SpendingGrantModel:
    if grant.status not in ("active", "paused"):
        raise HTTPException(409, f"grant is already {grant.status}")
    grant.status = "revoked"
    grant.revoked_at = _utcnow()
    grant.revoke_reason = (reason or "").strip()[:256]
    await db.flush()
    logger.info("spending_grant_revoked", grant_id=grant.grant_id, reason=grant.revoke_reason)
    return grant


async def pause_grant(db: AsyncSession, *, grant: SpendingGrantModel) -> SpendingGrantModel:
    if grant.status != "active":
        raise HTTPException(409, f"grant is {grant.status}, not active")
    grant.status = "paused"
    await db.flush()
    logger.info("spending_grant_paused", grant_id=grant.grant_id)
    return grant


async def resume_grant(db: AsyncSession, *, grant: SpendingGrantModel) -> SpendingGrantModel:
    if grant.status != "paused":
        raise HTTPException(409, f"grant is {grant.status}, not paused")
    if _expired(grant):
        raise HTTPException(409, "grant has expired and cannot be resumed")
    grant.status = "active"
    await db.flush()
    logger.info("spending_grant_resumed", grant_id=grant.grant_id)
    return grant
