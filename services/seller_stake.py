"""Seller stake rule — 30% of every order, taken from a pre-locked pool, automatically.

The seller side is meant to be *automatic*: the seller locks a stake pool once
(real USDC, one wallet signature) and Karma's own rules then reserve the default
30% stake (``SETTLEMENT_DEFAULT_PENALTY_BPS``) for every order the seller takes —
cumulative, one bill per order, no per-order margin posting.

Why a pool: ``KarmaBilateral.lock()`` moves USDC with ``transferFrom(msg.sender)``,
so only the wallet that owns the money can lock it. Locking once and reserving
per order is what makes "接单自动锁定质押" possible without the seller signing
on every order. Locking more than the minimum is a credibility signal — it is
exactly how many orders the pool can cover.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import ChainLockModel
from services.chain import wallet_lock

EPSILON = 1e-9
IDLE = "idle"
RESERVED = "reserved"


def stake_bps() -> int:
    try:
        return int(settings.settlement_default_penalty_bps)
    except (TypeError, ValueError):
        return 0


def required_stake_usdc(order_amount: float) -> float:
    """Default stake for one order: 30% of the order value."""
    bps = stake_bps()
    try:
        amount = float(order_amount or 0)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0 or bps <= 0:
        return 0.0
    return round(amount * bps / 10_000.0, 6)


def bill_state(row: ChainLockModel) -> str:
    return str(getattr(row, "stake_state", None) or IDLE)


def idle_bills(rows: Iterable[ChainLockModel]) -> list[ChainLockModel]:
    return [r for r in rows if r.state == "locked" and bill_state(r) == IDLE]


def reserved_bills(rows: Iterable[ChainLockModel]) -> list[ChainLockModel]:
    return [r for r in rows if r.state == "locked" and bill_state(r) == RESERVED]


def pool_total(rows: Iterable[ChainLockModel]) -> float:
    return round(sum(float(r.amount_usdc) for r in rows if r.state == "locked"), 6)


def select_stake_bill(
    rows: Sequence[ChainLockModel], required: float
) -> ChainLockModel | None:
    """Smallest idle bill that still covers ``required`` (keeps big bills free)."""
    candidates = [r for r in idle_bills(rows) if float(r.amount_usdc) + EPSILON >= required]
    if not candidates:
        return None
    return min(candidates, key=lambda r: float(r.amount_usdc))


def orders_covered(available_usdc: float, order_amount: float) -> int:
    """How many orders of this size the available stake still covers."""
    required = required_stake_usdc(order_amount)
    if required <= 0:
        return 0
    return int((float(available_usdc) + EPSILON) // required)


async def stake_summary(
    db: AsyncSession, *, identity_id: str, order_amount: float | None = None
) -> dict[str, Any]:
    """Pool health for the Console: how much stake is free, reserved, and left."""
    rows = await wallet_lock.list_locks(db, identity_id)
    idle = idle_bills(rows)
    reserved = reserved_bills(rows)
    required = required_stake_usdc(order_amount or 0)
    idle_total = round(sum(float(r.amount_usdc) for r in idle), 6)
    return {
        "required_bps": stake_bps(),
        "required_usdc_for_amount": required,
        "order_amount": float(order_amount or 0),
        "pool_total_usdc": pool_total(rows),
        "idle_usdc": idle_total,
        "reserved_usdc": round(sum(float(r.amount_usdc) for r in reserved), 6),
        "orders_covered": orders_covered(idle_total, order_amount or 0),
        "shortfall_usdc": round(max(0.0, required - idle_total), 6) if required else 0.0,
        "idle_bills": [r.bill_id for r in idle],
        "reserved": [
            {"bill_id": r.bill_id, "task_id": r.stake_task_id, "amount_usdc": float(r.amount_usdc)}
            for r in reserved
        ],
    }


async def reserve_stake(
    db: AsyncSession,
    *,
    seller_identity_id: str,
    order_amount: float,
    task_id: str,
) -> dict[str, Any]:
    """Automatically reserve the default stake for one accepted order.

    Karma's rule, not the agent's: pick the smallest free bill that covers 30% of
    the order value and mark it used by this task. Re-running for the same task is
    a no-op, so retries cannot double-charge the pool.
    """
    required = required_stake_usdc(order_amount)
    rows = await wallet_lock.list_locks(db, seller_identity_id)

    for row in rows:
        if row.stake_task_id == task_id and bill_state(row) == RESERVED:
            return _reserved(row, required, already=True)

    if required <= 0:
        return {
            "ok": True,
            "skipped": True,
            "reason": "order amount or stake basis points is zero",
            "required_usdc": 0.0,
        }

    pool = idle_bills(rows)
    bill = select_stake_bill(rows, required)
    if bill is None:
        idle_total = round(sum(float(r.amount_usdc) for r in pool), 6)
        return {
            "ok": False,
            "required_usdc": required,
            "available_usdc": idle_total,
            "shortfall_usdc": round(max(0.0, required - idle_total), 6),
            "reason": (
                f"seller stake pool is short: needs {required:.2f} USDC "
                f"(={stake_bps() / 100:.0f}% of {float(order_amount):.2f}) "
                f"but only {idle_total:.2f} USDC is free"
            ),
        }

    bill.stake_state = RESERVED
    bill.stake_task_id = task_id
    bill.stake_reserved_at = datetime.utcnow()
    bill.updated_at = datetime.utcnow()
    await db.flush()
    return _reserved(bill, required)


def _reserved(row: ChainLockModel, required: float, *, already: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "already_reserved": already,
        "task_id": row.stake_task_id,
        "bill_id": row.bill_id,
        "bill_amount_usdc": float(row.amount_usdc),
        "required_usdc": required,
    }


async def release_stake(
    db: AsyncSession, *, seller_identity_id: str, task_id: str
) -> dict[str, Any]:
    """Give the stake bill back to the pool (order cancelled / settled otherwise)."""
    rows = await wallet_lock.list_locks(db, seller_identity_id)
    for row in rows:
        if row.stake_task_id == task_id and bill_state(row) == RESERVED:
            row.stake_state = IDLE
            row.stake_task_id = None
            row.stake_reserved_at = None
            row.updated_at = datetime.utcnow()
            await db.flush()
            return {"ok": True, "released_bill_id": row.bill_id, "task_id": task_id}
    return {"ok": False, "reason": "no reserved stake for this task", "task_id": task_id}
