"""Capacity ledger helpers enforcing 1:1 anchored constraints."""
from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import CapacityState
from db.models.orm import CapacityModel

logger = structlog.get_logger(__name__)

EPSILON = 1e-9


def active_credits(state: CapacityState) -> float:
    return (
        state.available_credits
        + state.reserved_credits
        + state.in_progress_credits
        + state.confirmed_progress_credits
        + state.disputed_credits
        + state.pending_settlement_credits
    )


def responsibility_credits(state: CapacityState) -> float:
    """Bill credits in active responsibility buckets (non-available)."""
    return (
        state.reserved_credits
        + state.in_progress_credits
        + state.confirmed_progress_credits
        + state.disputed_credits
        + state.pending_settlement_credits
    )


def assert_can_release_locked_funds(state: CapacityState, amount: float) -> None:
    """Phase 1: cannot release anchored USDC while any bill credit holds responsibility."""
    if amount <= 0:
        raise ValueError("release amount must be > 0")
    if state.available_credits + 1e-9 < amount:
        raise ValueError("insufficient available credits")
    if responsibility_credits(state) > EPSILON:
        raise ValueError(
            "cannot release locked funds while bill credits hold active responsibility "
            "(reserved, in_progress, confirmed, disputed, or pending_settlement)"
        )


def assert_capacity_invariants(state: CapacityState) -> None:
    active = active_credits(state)
    if abs(state.total_bill_credits - active) > EPSILON:
        raise ValueError("capacity invariant violated: total_bill_credits != active credit sum")
    if state.total_locked_usdc + EPSILON < active:
        raise ValueError("capacity invariant violated: locked usdc below active credits")


def capacity_conservation_gap(row: CapacityModel) -> dict[str, float] | None:
    """这一行离守恒式差多少；守恒时返回 ``None``。

    两条守恒式（都是**派生**关系，所以能就地重算）：

    * ``total_bill_credits == active``（active = 可用 + 全部责任桶）
    * ``total_locked_usdc >= active``
    """
    active = (
        float(row.available_credits or 0.0)
        + float(row.reserved_credits or 0.0)
        + float(row.in_progress_credits or 0.0)
        + float(row.confirmed_progress_credits or 0.0)
        + float(row.disputed_credits or 0.0)
        + float(row.pending_settlement_credits or 0.0)
    )
    locked = float(row.total_locked_usdc or 0.0)
    bill = float(row.total_bill_credits or 0.0)
    if abs(bill - active) <= EPSILON and locked + EPSILON >= active:
        return None
    return {
        "active": active,
        "total_bill_credits": bill,
        "total_locked_usdc": locked,
    }


def _capacity_active_expr(available_expr):
    """活跃额度合计，交给数据库按**当前那一行**现算。"""
    return (
        available_expr
        + CapacityModel.reserved_credits
        + CapacityModel.in_progress_credits
        + CapacityModel.confirmed_progress_credits
        + CapacityModel.disputed_credits
        + CapacityModel.pending_settlement_credits
    )


async def heal_capacity_conservation(
    db: AsyncSession, identity_id: str, *, context: str
) -> dict[str, float] | None:
    """派生列被写坏时按守恒式原地修复；返回修复前后的账目（无需修复时返回 ``None``）。

    为什么是「修复」而不是「报错」：``total_bill_credits`` 是纯派生字段，它不承载任何
    「钱在哪」的信息；``total_locked_usdc`` 是链上锚的下界。两者同时从同一行的其它列
    推得出来，所以被写坏时**没有任何理由**把用户挡在门外 —— 每个动钱的入口都会在
    ``assert_capacity_invariants`` 上 500，钱一分没动，用户却办不了事（2026-09-29 真钱
    实测：``POST /v1/settlement/{task}/dispute`` 500 "capacity invariant check failed"）。

    修复只可能把 ``total_locked_usdc`` **抬高**（``max(现值, active)``），绝不会凭空
    放出额度；并且**大声记日志**（``capacity_conservation_repaired``），因为出现它本身
    就说明上游有个写入窗口没堵住，不能被当成正常路径。

    并发安全：两条派生列都在同一条 UPDATE 里由数据库现算，谁在中间动过责任桶都算得进去。
    """
    row = await db.get(CapacityModel, identity_id)
    if row is None:
        return None
    db.expire(row)
    await db.refresh(row)
    gap = capacity_conservation_gap(row)
    if gap is None:
        return None

    active = _capacity_active_expr(CapacityModel.available_credits)
    locked = CapacityModel.total_locked_usdc
    await db.execute(
        update(CapacityModel)
        .where(CapacityModel.identity_id == identity_id)
        .values(
            total_bill_credits=active,
            total_locked_usdc=case((locked > active, locked), else_=active),
            updated_at=datetime.utcnow(),
        )
    )
    await db.flush()
    fixed = await db.get(CapacityModel, identity_id)
    db.expire(fixed)
    await db.refresh(fixed)
    logger.warning(
        "capacity_conservation_repaired",
        identity_id=identity_id,
        context=context,
        active=round(gap["active"], 6),
        total_bill_credits_before=round(gap["total_bill_credits"], 6),
        total_locked_usdc_before=round(gap["total_locked_usdc"], 6),
        total_bill_credits_after=round(float(fixed.total_bill_credits or 0.0), 6),
        total_locked_usdc_after=round(float(fixed.total_locked_usdc or 0.0), 6),
    )
    return gap

