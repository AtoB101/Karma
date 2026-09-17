"""Shared capacity accounting for settlement / arbitration (P0–P2)."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import CapacityState
from db.models.orm import CapacityModel
from services import atomic_ledger
from services.capacity_ledger import assert_capacity_invariants
from services.runtime_safety import audit_capacity_anchor_and_maybe_trip


async def move_reserved_to_disputed(
    *,
    db: AsyncSession,
    buyer_identity_id: str,
    escrow_amount: float,
) -> None:
    """P0: when a dispute opens, escrow moves from reserved → disputed bucket."""
    cap = await db.get(CapacityModel, buyer_identity_id)
    if not cap:
        raise HTTPException(409, "buyer has no capacity ledger; cannot open dispute")
    if cap.reserved_credits + 1e-9 < escrow_amount:
        raise HTTPException(409, "insufficient reserved credits to freeze for dispute")
    # 并发安全：冻结进争议桶，用带守卫的原子增量，避免两个并发争议各冻结一次。
    try:
        await atomic_ledger.apply_delta_or_raise(
            db,
            CapacityModel,
            "identity_id",
            buyer_identity_id,
            {"reserved_credits": -escrow_amount, "disputed_credits": escrow_amount},
            guards=[(lambda C, _need=escrow_amount: C.reserved_credits + 1e-9 >= _need)],
            message="insufficient reserved credits to freeze for dispute",
        )
    except atomic_ledger.LedgerConflict as exc:
        raise HTTPException(409, str(exc)) from exc

    cap = await atomic_ledger.reload(db, CapacityModel, buyer_identity_id)
    _assert_capacity(cap)
    await audit_capacity_anchor_and_maybe_trip(db=db)


async def apply_capacity_resolution(
    *,
    db: AsyncSession,
    buyer_identity_id: str,
    escrow_amount: float,
    settled_amount: float,
    refunded_amount: float,
) -> None:
    """
    Release escrow from reserved OR disputed (post-dispute path),
    burn settled bill credits, and credit released (refunded) USDC-side ledger.
    """
    cap = await db.get(CapacityModel, buyer_identity_id)
    if not cap:
        return
    if cap.total_bill_credits + 1e-9 < escrow_amount:
        raise HTTPException(409, "capacity total_bill_credits lower than settlement escrow amount")
    if cap.total_locked_usdc + 1e-9 < escrow_amount:
        raise HTTPException(409, "capacity total_locked_usdc lower than settlement escrow amount")

    # 并发安全：结算放款是「可失败」操作，且必须先命中 disputed 或 reserved 之一。
    # 两次带守卫的原子尝试（高并发下只有一次会成功），避免重复放款/双花。
    base_deltas = {
        "burned_credits": settled_amount,
        "released_credits": refunded_amount,
        "total_bill_credits": -escrow_amount,
        "total_locked_usdc": -escrow_amount,
    }
    common_guards = [
        (lambda C, _need=escrow_amount: C.total_bill_credits + 1e-9 >= _need),
        (lambda C, _need=escrow_amount: C.total_locked_usdc + 1e-9 >= _need),
    ]
    rows = await atomic_ledger.apply_delta(
        db,
        CapacityModel,
        "identity_id",
        buyer_identity_id,
        {**base_deltas, "disputed_credits": -escrow_amount},
        guards=common_guards + [(lambda C, _need=escrow_amount: C.disputed_credits + 1e-9 >= _need)],
    )
    if rows != 1:
        rows = await atomic_ledger.apply_delta(
            db,
            CapacityModel,
            "identity_id",
            buyer_identity_id,
            {**base_deltas, "reserved_credits": -escrow_amount},
            guards=common_guards + [(lambda C, _need=escrow_amount: C.reserved_credits + 1e-9 >= _need)],
        )
    if rows != 1:
        raise HTTPException(
            409,
            "capacity: neither disputed_credits nor reserved_credits cover escrow amount",
        )

    cap = await atomic_ledger.reload(db, CapacityModel, buyer_identity_id)
    _assert_capacity(cap)
    await audit_capacity_anchor_and_maybe_trip(db=db)


def _assert_capacity(cap: CapacityModel) -> None:
    try:
        assert_capacity_invariants(
            CapacityState(
                identity_id=cap.identity_id,
                total_locked_usdc=cap.total_locked_usdc,
                total_bill_credits=cap.total_bill_credits,
                available_credits=cap.available_credits,
                reserved_credits=cap.reserved_credits,
                in_progress_credits=cap.in_progress_credits,
                confirmed_progress_credits=cap.confirmed_progress_credits,
                disputed_credits=cap.disputed_credits,
                pending_settlement_credits=cap.pending_settlement_credits,
                burned_credits=cap.burned_credits,
                released_credits=cap.released_credits,
                updated_at=cap.updated_at,
            )
        )
    except ValueError as exc:
        raise HTTPException(500, "capacity invariant check failed") from exc
