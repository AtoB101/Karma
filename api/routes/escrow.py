"""Karma API — v2 allowance escrow (non-custodial).

The user's USDC never leaves their own wallet. ``approve`` + ``commit`` are
signed once in the Console; everything after that is Karma's rules running on
top of that allowance, and the payout is a direct wallet → wallet transfer the
contract executes. Nothing here ever sees a private key.

Endpoints
---------
GET  /v1/escrow/{identity_id}                     config + live commitments
POST /v1/escrow/{identity_id}/claim-commit        credit a wallet-signed commit()
POST /v1/escrow/{identity_id}/claim-revoke        mark a commitment revoked
POST /v1/escrow/{identity_id}/sync                re-read every bill from chain
POST /v1/escrow/{identity_id}/orders              bind + submit (Karma operator)
POST /v1/escrow/{identity_id}/orders/{id}/finalize  execute the pull, or slash
"""
from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AllowanceCommitModel, EscrowBindingModel, IdentityRoleProfile
from db.session import get_db
from services import profile_capacity, seller_stake
from services.chain import allowance_escrow as escrow
from services.chain import wallet_lock
from services.identity_wallet_binding import get_bound_wallet
from services.ledger_party_access import require_ledger_identity
from services.path_param_safety import validate_public_url_segment

logger = structlog.get_logger(__name__)

router = APIRouter()


class ClaimCommitBody(BaseModel):
    tx_hash: str = Field(min_length=10)


class ClaimRevokeBody(BaseModel):
    bill_id: str = Field(min_length=1)
    tx_hash: str = Field(min_length=10)


class OrderBody(BaseModel):
    """One order: the buyer's commitment + the seller's stake, bound together."""

    seller_bill_id: str = Field(min_length=1)
    buyer_bill_id: str | None = None
    amount_usdc: float = Field(gt=0.0)
    stake_usdc: float | None = None  # None → Karma's default 30% rule
    task_id: str = Field(min_length=1, max_length=64)
    proof: str = Field(min_length=1, description="verification proof / receipt hash")
    scope: str | None = None
    profile_id: str | None = Field(
        default=None,
        description="子身份（角色档案）——这一单花的是它的额度；不传则不受子身份额度约束",
    )


def _commit_view(row: AllowanceCommitModel) -> dict:
    return {
        "bill_id": row.bill_id,
        "amount_usdc": float(row.amount_usdc),
        "spent_usdc": float(row.spent_usdc or 0.0),
        "reserved_usdc": float(row.reserved_usdc or 0.0),
        "available_usdc": round(
            float(row.amount_usdc) - float(row.spent_usdc or 0.0) - float(row.reserved_usdc or 0.0), 6
        ),
        "wallet_address": row.wallet_address,
        "operator": row.operator,
        "state": row.state,
        "backed": bool(row.backed),
        "commit_tx_hash": row.commit_tx_hash,
        "revoke_tx_hash": row.revoke_tx_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _binding_view(row: EscrowBindingModel) -> dict:
    return {
        "binding_id": row.binding_id,
        "buyer_identity_id": row.buyer_identity_id,
        "seller_identity_id": row.seller_identity_id,
        "buyer_profile_id": row.buyer_profile_id,
        "buyer_bill_id": row.buyer_bill_id,
        "seller_bill_id": row.seller_bill_id,
        "amount_usdc": float(row.amount_usdc),
        "stake_usdc": float(row.stake_usdc),
        "state": row.state,
        "task_id": row.task_id,
        "proof_hash": row.proof_hash,
        "bind_tx_hash": row.bind_tx_hash,
        "submit_tx_hash": row.submit_tx_hash,
        "finalize_tx_hash": row.finalize_tx_hash,
        "pull_after": row.pull_after,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/{identity_id}")
async def get_escrow_state(identity_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """The Console's allowance-escrow surface: config, commitments, bindings."""
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)

    commits = await escrow.list_commits(db, identity_id)
    bindings = await escrow.list_bindings(db, identity_id)
    live = [c for c in commits if c.state == escrow.IDLE]
    return {
        "identity_id": identity_id,
        "escrow": escrow.escrow_config(),
        "wallet": await get_bound_wallet(db, identity_id),
        "stake": await seller_stake.stake_summary(db, identity_id=identity_id),
        "committed_usdc": round(sum(float(c.amount_usdc) for c in live), 6),
        "spent_usdc": round(sum(float(c.spent_usdc or 0.0) for c in commits), 6),
        "reserved_usdc": round(sum(float(c.reserved_usdc or 0.0) for c in live), 6),
        "commits": [_commit_view(c) for c in commits],
        "bindings": [_binding_view(b) for b in bindings],
    }


@router.post("/{identity_id}/claim-commit")
async def claim_commit(
    identity_id: str, body: ClaimCommitBody, request: Request, db: AsyncSession = Depends(get_db)
):
    """Credit a wallet-signed ``commit()`` (idempotent; amount read from chain)."""
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)

    wallets = await wallet_lock.allowed_wallets(db, identity_id)
    try:
        row = await escrow.claim_commit(db, identity_id=identity_id, tx_hash=body.tx_hash, wallets=wallets)
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc

    from db.models.orm import IdentityProfileModel

    profile = await db.get(IdentityProfileModel, identity_id)
    if profile is not None and not (profile.bound_wallet_address or "").strip():
        profile.bound_wallet_address = row.wallet_address
        profile.updated_at = datetime.utcnow()

    await db.flush()
    return {"identity_id": identity_id, "commit": _commit_view(row), "idempotent": True}


@router.post("/{identity_id}/claim-revoke")
async def claim_revoke(
    identity_id: str, body: ClaimRevokeBody, request: Request, db: AsyncSession = Depends(get_db)
):
    """Mark a commitment revoked after the owner's own ``revoke()`` transaction."""
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)

    wallets = await wallet_lock.allowed_wallets(db, identity_id)
    try:
        row = await escrow.claim_revoke(
            db, identity_id=identity_id, bill_id=body.bill_id, tx_hash=body.tx_hash, wallets=wallets
        )
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.flush()
    return {"identity_id": identity_id, "commit": _commit_view(row)}


@router.post("/{identity_id}/sync")
async def sync_escrow(identity_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Re-read every recorded bill from the chain so the Console shows the truth.

    ``backed`` is false the moment the wallet lowers its allowance or spends the
    balance — that is the honest state of a non-custodial pledge.
    """
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)
    try:
        rows = await escrow.sync_commits(db, identity_id)
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"identity_id": identity_id, "commits": [_commit_view(r) for r in rows]}


@router.post("/{identity_id}/orders")
async def open_order(
    identity_id: str, body: OrderBody, request: Request, db: AsyncSession = Depends(get_db)
):
    """Bind the buyer's commitment to the seller's stake and submit the proof.

    Called by the buyer's agent (or the Console) once an order is accepted. The
    buyer does not sign here: they already named Karma's operator on their bill.
    """
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)

    if not escrow.can_server_settle():
        raise HTTPException(409, escrow.disabled_detail() or "Karma's settlement operator is not configured")

    buyer_bill = await _resolve_bill(db, identity_id, body.buyer_bill_id, role="buyer")
    seller_bill = await _resolve_bill(db, None, body.seller_bill_id, role="seller")
    seller_identity = seller_bill.identity_id

    # 子身份额度：这一单如果点名了子身份，就花它的额度。先只读地查一次可用额度，
    # 免得链上已经 bind 成功、才因为额度不够把这一单变成孤儿。没有分配过的子身份
    # 不受约束（向后兼容：老 agent 不传 profile_id 照旧）。
    profile_id = body.profile_id
    profile_row = None
    if profile_id:
        profile = await db.get(IdentityRoleProfile, profile_id)
        if profile is None or profile.owner_identity_id != identity_id:
            raise HTTPException(404, f"profile {profile_id} not found for this identity")
        profile_row = await profile_capacity.get_profile_capacity(db, profile_id=profile_id)
        if profile_row is not None and body.amount_usdc > float(
            profile_row.available_credits or 0.0
        ) + 1e-9:
            raise HTTPException(
                409,
                f"insufficient profile credits: need {body.amount_usdc}, "
                f"available {profile_row.available_credits}",
            )

    stake = body.stake_usdc
    if stake is None:
        stake = seller_stake.required_stake_usdc(body.amount_usdc)
    if stake <= 0:
        raise HTTPException(422, "stake_usdc must be positive (or set SETTLEMENT_DEFAULT_PENALTY_BPS)")

    try:
        # bind + submit is one unit: if submit cannot land, the reservation is
        # released instead of being stranded on-chain with no row to match it.
        result = escrow.open_and_submit_order(
            buyer_bill_id=buyer_bill.bill_id,
            seller_bill_id=seller_bill.bill_id,
            amount_usdc=body.amount_usdc,
            stake_usdc=stake,
            scope=body.scope or settings.settlement_scope,
            task_id=body.task_id,
            proof=body.proof,
        )
        submitted = result
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc

    if profile_id and profile_row is not None:
        await profile_capacity.spend_profile_credits(
            db, profile_id=profile_id, amount=float(body.amount_usdc)
        )

    row = EscrowBindingModel(
        binding_id=str(result["binding_id"]),
        buyer_identity_id=identity_id,
        seller_identity_id=seller_identity,
        buyer_profile_id=profile_id,
        buyer_bill_id=buyer_bill.bill_id,
        seller_bill_id=seller_bill.bill_id,
        scope_hash=result["scope_hash"],
        task_id=body.task_id,
        amount_usdc=float(body.amount_usdc),
        stake_usdc=float(stake),
        state="finalizing",
        proof_hash=submitted["proof_hash"],
        bind_tx_hash=result["bind_tx_hash"],
        submit_tx_hash=submitted["submit_tx_hash"],
        pull_after=int(submitted["pull_after"] or 0),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    logger.info(
        "escrow_order_opened",
        identity_id=identity_id,
        binding_id=row.binding_id,
        amount_usdc=row.amount_usdc,
    )
    return {
        "identity_id": identity_id,
        "binding": _binding_view(row),
        "pull_after": row.pull_after,
        "note": "settlement becomes executable once the challenge window elapses",
    }


@router.post("/{identity_id}/orders/{binding_id}/finalize")
async def finalize_order(
    identity_id: str,
    binding_id: str,
    request: Request,
    breach: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Execute the pull, wallet → wallet. Permissionless on-chain once due."""
    validate_public_url_segment("identity_id", identity_id)
    validate_public_url_segment("binding_id", binding_id)
    require_ledger_identity(request, identity_id)

    row = await db.get(EscrowBindingModel, binding_id)
    if row is None or identity_id not in {row.buyer_identity_id, row.seller_identity_id}:
        raise HTTPException(404, "unknown binding for this identity")

    try:
        if breach:
            result = escrow.finalize_breach(binding_id=int(binding_id))
            row.state = "slashed"
            row.finalize_tx_hash = result["breach_tx_hash"]
        else:
            result = escrow.finalize_settlement(binding_id=int(binding_id))
            row.state = "settled"
            row.finalize_tx_hash = result["finalize_tx_hash"]
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc

    row.updated_at = datetime.utcnow()
    if row.buyer_profile_id:
        # 钱真的划走了，把这一单占用的子身份额度结清（in_progress → released）。
        await profile_capacity.release_profile_credits(
            db,
            profile_id=row.buyer_profile_id,
            settled_amount=float(row.amount_usdc),
        )
    await escrow.sync_commits(db, row.buyer_identity_id)
    if row.seller_identity_id:
        await escrow.sync_commits(db, row.seller_identity_id)
    await db.flush()
    return {"identity_id": identity_id, "binding": _binding_view(row), "result": result}


async def _resolve_bill(
    db: AsyncSession, identity_id: str | None, bill_id: str, *, role: str
) -> AllowanceCommitModel:
    """Load a commitment, pinned to ``identity_id`` when the caller owns it.

    The seller's stake is looked up by bill id alone: the buyer's agent may name
    *any* seller pool to bind against, which is exactly how a marketplace works.
    The buyer's own bill is always pinned to the signed-in identity.
    """
    row = await db.get(AllowanceCommitModel, str(bill_id))
    if row is None:
        raise HTTPException(404, f"unknown {role} commitment")
    if identity_id is not None and row.identity_id != identity_id:
        raise HTTPException(404, f"unknown {role} commitment for this identity")
    if row.state != escrow.IDLE:
        raise HTTPException(409, f"{role} commitment is {row.state}")
    return row
