"""Karma API — Identity capacity ledger (USDC 1:1 anchored)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import CapacityState
from config.settings import settings
from db.models.orm import CapacityModel
from db.session import get_db
from services import atomic_ledger
from services import console_2fa
from services import profile_capacity as profile_capacity_service
from services.console_2fa import TwoFactorError
from services.identity_activation import activation_of
from services.chain import wallet_lock
from services.capacity_ledger import assert_can_release_locked_funds, assert_capacity_invariants
from services.identity_actor import resolve_actor_identity_id
from services.identity_wallet_binding import get_bound_wallet
from services import seller_stake
from services.ledger_party_access import require_ledger_identity
from services.path_param_safety import validate_public_url_segment
from services.runtime_safety import (
    assert_runtime_operation_allowed,
    audit_capacity_anchor_and_maybe_trip,
)

router = APIRouter()


class AmountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    amount: float = Field(gt=0.0)
    profile_id: str | None = None


class AllocateBody(BaseModel):
    """profile_id -> allocated_credits 的额度分配（总和不超 master 锁仓）。"""
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    allocations: dict[str, float] = Field(default_factory=dict)


@router.get("/{identity_id}", response_model=CapacityState)
async def get_capacity(identity_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("identity_id", identity_id)
    row = await db.get(CapacityModel, identity_id)
    if not row:
        return CapacityState(identity_id=identity_id)
    return _to_schema(row)


@router.post("/{identity_id}/lock", response_model=CapacityState)
async def lock_usdc(identity_id: str, body: AmountRequest, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("identity_id", identity_id)
    if body.profile_id:
        validate_public_url_segment("profile_id", body.profile_id)
    require_ledger_identity(request, identity_id)
    assert_runtime_operation_allowed("new_lock")

    # Enforce min/max escrow limits from config
    if body.amount < settings.escrow_min_amount:
        raise HTTPException(422, f"amount below minimum {settings.escrow_min_amount} USDC")
    if body.amount > settings.escrow_max_amount:
        raise HTTPException(422, f"amount exceeds maximum {settings.escrow_max_amount} USDC")

    await audit_capacity_anchor_and_maybe_trip(db=db)
    # 并发安全：锁仓是纯增量，压成一条原子 UPDATE。
    # 历史问题：15 个并发锁仓请求全部返回 200，账上只入账 1 笔（丢更新）。
    await atomic_ledger.ensure_row(
        db,
        CapacityModel,
        "identity_id",
        identity_id,
        defaults={
            "total_locked_usdc": 0.0,
            "total_bill_credits": 0.0,
            "available_credits": 0.0,
            "reserved_credits": 0.0,
            "in_progress_credits": 0.0,
            "confirmed_progress_credits": 0.0,
            "disputed_credits": 0.0,
            "pending_settlement_credits": 0.0,
            "burned_credits": 0.0,
            "released_credits": 0.0,
            "updated_at": datetime.utcnow(),
        },
    )
    rows = await atomic_ledger.apply_delta(
        db,
        CapacityModel,
        "identity_id",
        identity_id,
        {
            "total_locked_usdc": body.amount,
            "total_bill_credits": body.amount,
            "available_credits": body.amount,
        },
        extra_values={"profile_id": body.profile_id} if body.profile_id else None,
    )
    if rows != 1:
        raise HTTPException(409, "capacity row missing; lock was not credited")

    row = await atomic_ledger.reload(db, CapacityModel, identity_id)
    state = _to_schema(row)
    _validate(state)
    await audit_capacity_anchor_and_maybe_trip(db=db)
    return state


@router.post("/{identity_id}/release", response_model=CapacityState)
async def release_unused(identity_id: str, body: AmountRequest, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("identity_id", identity_id)
    if body.profile_id:
        validate_public_url_segment("profile_id", body.profile_id)
    require_ledger_identity(request, identity_id)
    assert_runtime_operation_allowed("release_unused_capacity")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    row = await db.get(CapacityModel, identity_id)
    if not row:
        raise HTTPException(404, f"Capacity for {identity_id} not found")
    state_before = _to_schema(row)
    try:
        assert_can_release_locked_funds(state_before, body.amount)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    # 并发安全：减仓是「可失败」操作，把「余额够减」和「责任额度没被并发改动」
    # 一起写进 WHERE，由数据库判定；否则两个并发请求会双双通过校验、各减一次。
    guards = [
        lambda C: C.available_credits >= body.amount,
        lambda C: C.total_bill_credits >= body.amount,
        lambda C: C.total_locked_usdc >= body.amount,
        *atomic_ledger.responsibility_snapshot_guards(state_before),
    ]
    try:
        await atomic_ledger.apply_delta_or_raise(
            db,
            CapacityModel,
            "identity_id",
            identity_id,
            {
                "available_credits": -body.amount,
                "total_bill_credits": -body.amount,
                "total_locked_usdc": -body.amount,
                "released_credits": body.amount,
            },
            guards=guards,
            extra_values={"profile_id": body.profile_id} if body.profile_id else None,
            message="release rejected: insufficient balance or concurrent change",
        )
    except atomic_ledger.LedgerConflict as exc:
        raise HTTPException(409, str(exc)) from exc

    row = await atomic_ledger.reload(db, CapacityModel, identity_id)
    state = _to_schema(row)
    _validate(state)
    await audit_capacity_anchor_and_maybe_trip(db=db)
    return state


@router.get("/{identity_id}/allocations")
async def get_allocations(identity_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("identity_id", identity_id)
    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != identity_id:
        raise HTTPException(403, "only the identity owner can view allocations")
    rows = await profile_capacity_service.get_allocations(db, identity_id=identity_id)
    capacity = await db.get(CapacityModel, identity_id)
    state = _to_schema(capacity) if capacity is not None else CapacityState(identity_id=identity_id)
    activation = await activation_of(db, identity_id)
    # 主身份页要的三行总账。口径和「已用 = in_progress + pending_settlement + disputed」
    # 一致，免得前端自己再加一遍、又和别处对不上。
    allocated = round(sum(float(r.get("allocated_credits") or 0.0) for r in rows), 6)
    in_use = round(
        sum(
            float(r.get("in_progress_credits") or 0.0)
            + float(r.get("pending_settlement_credits") or 0.0)
            + float(r.get("disputed_credits") or 0.0)
            for r in rows
        ),
        6,
    )
    return {
        "allocations": rows,
        # 子身份额度加起来的上限：v1 是锁仓台账，v2 是钱包给出的有效 commit 之和。
        "locked_usdc": await profile_capacity_service.master_ceiling_usdc(
            db, identity_id=identity_id
        ),
        "ceiling": await profile_capacity_service.ceiling_breakdown(
            db, identity_id=identity_id
        ),
        "allocated_usdc": allocated,
        "in_use_usdc": in_use,
        "available_usdc": round(max(0.0, allocated - in_use), 6),
        "activated": activation["activated"],
        "activation": activation,
        "capacity": state.model_dump(mode="json"),
    }


@router.put("/{identity_id}/allocations")
async def set_allocations(identity_id: str, body: AllocateBody, request: Request, db: AsyncSession = Depends(get_db)):
    """授权额度：加额 / 减额 / 取消授权（置 0）都走这一条。

    动额度 = 给出支配权，所以在钱包签名之外还要过一次 2FA 验证码
    （``X-Karma-2FA-Code``）。绑了 2FA 的身份**必须**带码；没绑的按设置放行，
    由操作台一直提示去绑定（``CONSOLE_2FA_REQUIRED_FOR_FUNDS=true`` 时连没绑也不许动）。
    """
    validate_public_url_segment("identity_id", identity_id)
    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != identity_id:
        raise HTTPException(403, "only the identity owner can set allocations")
    try:
        await console_2fa.require_code(
            db,
            actor,
            request.headers.get("X-Karma-2FA-Code"),
            what="setting sub-identity allocations",
        )
    except TwoFactorError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    rows = await profile_capacity_service.allocate(db, identity_id=identity_id, allocations=body.allocations)
    return {
        "allocations": rows,
        "locked_usdc": await profile_capacity_service.master_ceiling_usdc(
            db, identity_id=identity_id
        ),
    }


class ClaimBillBody(BaseModel):
    """A ``KarmaBilateral.lock()`` transaction the user signed in their wallet."""
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃

    tx_hash: str = Field(min_length=66, max_length=66)


class ClaimUnlockBody(BaseModel):
    """A ``KarmaBilateral.unlock(billId)`` transaction the user signed."""
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃

    bill_id: str = Field(min_length=1, max_length=80)
    tx_hash: str = Field(min_length=66, max_length=66)


class StakeRequestBody(BaseModel):
    """Karma rule input: 30% of this order value is staked from the seller pool."""
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃

    order_amount: float = Field(gt=0.0)
    task_id: str = Field(min_length=1, max_length=64)


class StakeReleaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    task_id: str = Field(min_length=1, max_length=64)


@router.post("/{identity_id}/stake/reserve")
async def reserve_seller_stake(
    identity_id: str,
    body: StakeRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reserve the automatic seller stake for one accepted order.

    Default is ``SETTLEMENT_DEFAULT_PENALTY_BPS`` (30%) of the order value, taken
    from the seller's pre-locked pool and cumulative across orders. Sellers never
    post margin by hand; a short pool is refused with the exact shortfall.
    """
    validate_public_url_segment("identity_id", identity_id)
    validate_public_url_segment("task_id", body.task_id)
    require_ledger_identity(request, identity_id)
    result = await seller_stake.reserve_stake(
        db,
        seller_identity_id=identity_id,
        order_amount=body.order_amount,
        task_id=body.task_id,
    )
    if not result.get("ok"):
        raise HTTPException(409, result.get("reason", "seller stake unavailable"))
    return result


@router.post("/{identity_id}/stake/release")
async def release_seller_stake(
    identity_id: str,
    body: StakeReleaseBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return a reserved stake bill to the pool."""
    validate_public_url_segment("identity_id", identity_id)
    validate_public_url_segment("task_id", body.task_id)
    require_ledger_identity(request, identity_id)
    result = await seller_stake.release_stake(
        db, seller_identity_id=identity_id, task_id=body.task_id
    )
    if not result.get("ok"):
        raise HTTPException(409, result.get("reason", "no reserved stake"))
    return result


@router.get("/{identity_id}/chain")
async def get_chain_lock_state(identity_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """On-chain deposit surface for the Console: config, recorded bills, totals.

    ``ledger_locked_usdc`` is what the identity can actually spend right now;
    ``onchain_locked_usdc`` is the USDC those credits are anchored to. They are
    reported separately so the Console can be honest about which mode a deposit
    used (a ledger-only dev deposit has no on-chain backing).
    """
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)

    rows = await wallet_lock.list_locks(db, identity_id)
    cap = await db.get(CapacityModel, identity_id)
    locked_rows = [r for r in rows if r.state == "locked"]
    return {
        "identity_id": identity_id,
        "chain": wallet_lock.chain_config(),
        "wallet": await get_bound_wallet(db, identity_id),
        "stake": await seller_stake.stake_summary(db, identity_id=identity_id),
        "ledger_locked_usdc": float(cap.total_locked_usdc) if cap else 0.0,
        "onchain_locked_usdc": sum(float(r.amount_usdc) for r in locked_rows),
        "onchain_released_usdc": sum(float(r.amount_usdc) for r in rows if r.state == "released"),
        "bills": [
            {
                "bill_id": r.bill_id,
                "amount_usdc": float(r.amount_usdc),
                "amount_wei": r.amount_wei,
                "wallet_address": r.wallet_address,
                "state": r.state,
                "lock_tx_hash": r.lock_tx_hash,
                "unlock_tx_hash": r.unlock_tx_hash,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/{identity_id}/claim-bill", response_model=CapacityState)
async def claim_bill(
    identity_id: str,
    body: ClaimBillBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Credit a wallet-signed on-chain lock to this identity (idempotent).

    The amount is read from the on-chain ``BillMinted`` event, so the client
    cannot choose how many credits it gets; replaying a transaction is a no-op.
    """
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)
    assert_runtime_operation_allowed("new_lock")
    await audit_capacity_anchor_and_maybe_trip(db=db)

    wallets = await wallet_lock.allowed_wallets(db, identity_id)
    try:
        row = await wallet_lock.claim_lock_bill(
            db, identity_id=identity_id, tx_hash=body.tx_hash, wallets=wallets
        )
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc

    # First proven lock binds the wallet to the identity profile, so later
    # on-chain actions (seller stake, withdrawals) verify against the same wallet.
    from db.models.orm import IdentityProfileModel

    profile = await db.get(IdentityProfileModel, identity_id)
    if profile is not None and not (profile.bound_wallet_address or "").strip():
        profile.bound_wallet_address = row.wallet_address
        profile.updated_at = datetime.utcnow()

    capacity = await db.get(CapacityModel, identity_id)
    state = _to_schema(capacity)
    _validate(state)
    await audit_capacity_anchor_and_maybe_trip(db=db)
    await db.flush()
    return state


@router.post("/{identity_id}/claim-unlock", response_model=CapacityState)
async def claim_unlock(
    identity_id: str,
    body: ClaimUnlockBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Release ledger credits after the user withdraws an unbound bill on-chain."""
    validate_public_url_segment("identity_id", identity_id)
    require_ledger_identity(request, identity_id)
    assert_runtime_operation_allowed("release_unused_capacity")
    await audit_capacity_anchor_and_maybe_trip(db=db)

    wallets = await wallet_lock.allowed_wallets(db, identity_id)
    try:
        await wallet_lock.claim_unlock(
            db,
            identity_id=identity_id,
            bill_id=body.bill_id,
            tx_hash=body.tx_hash,
            wallets=wallets,
        )
    except wallet_lock.WalletLockError as exc:
        raise HTTPException(409, str(exc)) from exc

    capacity = await db.get(CapacityModel, identity_id)
    state = _to_schema(capacity)
    _validate(state)
    await audit_capacity_anchor_and_maybe_trip(db=db)
    await db.flush()
    return state


def _to_schema(row: CapacityModel) -> CapacityState:
    return CapacityState(
        identity_id=row.identity_id,
        profile_id=row.profile_id,
        total_locked_usdc=row.total_locked_usdc,
        total_bill_credits=row.total_bill_credits,
        available_credits=row.available_credits,
        reserved_credits=row.reserved_credits,
        in_progress_credits=row.in_progress_credits,
        confirmed_progress_credits=row.confirmed_progress_credits,
        disputed_credits=row.disputed_credits,
        pending_settlement_credits=row.pending_settlement_credits,
        burned_credits=row.burned_credits,
        released_credits=row.released_credits,
        updated_at=row.updated_at,
    )


def _validate(state: CapacityState) -> None:
    try:
        assert_capacity_invariants(state)
    except ValueError as exc:
        raise HTTPException(500, "capacity invariant check failed") from exc

