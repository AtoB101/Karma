"""Karma - automatic escrow settlement (the missing caller).

The promise to the user is simple: lock once, get verified, and the money moves.
The chain already allows that. A binding is *permissionless* once its challenge
window has elapsed, so anybody may execute the pull, payer wallet -> payee
wallet. What was missing was the somebody.

This module is that somebody. It runs inside the API process (the same pattern
as the OpenClaw webhook runner) and on every tick executes the bindings whose
window has elapsed. It never holds a user key and never needs a user token: the
operator account only pays gas, and only the payer's own allowance can move a
cent, revocable by the payer at any time.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import EscrowBindingModel
from db.session import AsyncSessionLocal
from services.chain import allowance_escrow as escrow
from services.chain import wallet_lock

logger = structlog.get_logger(__name__)

#: the state a binding sits in between "submitted" and "executed"
DUE_STATE = "finalizing"
SETTLED_STATE = "settled"

#: Once an attempt fails, leave that binding alone for a while. The usual causes
#: (an allowance that is not funded yet, an RPC hiccup, a revert) do not fix
#: themselves within one tick, and the operator account pays for every retry.
RETRY_BACKOFF_SECONDS = 120.0
_failed_at: dict[str, float] = {}


def reset_backoff() -> None:
    """Forget failed attempts (tests, and an operator-triggered retry)."""
    _failed_at.clear()


async def due_bindings(
    db: AsyncSession, *, now: int | None = None, limit: int | None = None
) -> list[EscrowBindingModel]:
    """Bindings whose challenge window has elapsed and that nobody executed."""
    stamp = int(time.time()) if now is None else int(now)
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.state == DUE_STATE)
        .where(EscrowBindingModel.pull_after.is_not(None))
        .where(EscrowBindingModel.pull_after > 0)
        .where(EscrowBindingModel.pull_after <= stamp)
        .order_by(EscrowBindingModel.pull_after)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    return list((await db.execute(stmt)).scalars().all())


def _backed_off(binding_id: str) -> bool:
    last = _failed_at.get(binding_id)
    return last is not None and (time.monotonic() - last) < RETRY_BACKOFF_SECONDS


async def settle_due(db: AsyncSession, *, now: int | None = None) -> list[dict]:
    """Execute every due binding. Returns the ones that actually settled."""
    if not escrow.escrow_enabled() or not escrow.can_server_settle():
        return []
    settled: list[dict] = []
    for row in await due_bindings(db, now=now):
        if _backed_off(row.binding_id):
            continue
        try:
            result = await asyncio.to_thread(
                escrow.finalize_settlement, binding_id=int(row.binding_id)
            )
        except wallet_lock.WalletLockError as exc:
            _failed_at[row.binding_id] = time.monotonic()
            logger.warning(
                "escrow_autosettle_declined", binding_id=row.binding_id, error=str(exc)
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one bad binding must not stop the rest
            _failed_at[row.binding_id] = time.monotonic()
            logger.warning("escrow_autosettle_failed", binding_id=row.binding_id, error=str(exc))
            continue
        _failed_at.pop(row.binding_id, None)
        row.state = SETTLED_STATE
        row.finalize_tx_hash = result.get("finalize_tx_hash")
        row.updated_at = datetime.now(UTC)
        # The money already moved on-chain, so the binding row is committed
        # first. Re-reading the bills is bookkeeping and stays best-effort: a
        # wobbly RPC must not cost us the record of a real settlement.
        await db.commit()
        for party in (row.buyer_identity_id, row.seller_identity_id):
            if not party:
                continue
            try:
                await escrow.sync_commits(db, party)
                await db.commit()
            except Exception as exc:  # noqa: BLE001 - bookkeeping, not money
                await db.rollback()
                logger.warning(
                    "escrow_autosettle_sync_failed", identity_id=party, error=str(exc)
                )
        logger.info(
            "escrow_autosettle_settled",
            binding_id=row.binding_id,
            tx=row.finalize_tx_hash,
            amount_usdc=row.amount_usdc,
        )
        settled.append(
            {
                "binding_id": row.binding_id,
                "finalize_tx_hash": row.finalize_tx_hash,
                "amount_usdc": row.amount_usdc,
            }
        )
    return settled


async def run_forever() -> None:
    """The loop the API process starts when auto-settlement is switched on."""
    interval = max(3, int(settings.escrow_autosettle_interval_seconds))
    logger.info("escrow_autosettle_started", interval_seconds=interval)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                settled = await settle_due(db)
            if settled:
                logger.info("escrow_autosettle_tick", settled=len(settled))
        except asyncio.CancelledError:
            logger.info("escrow_autosettle_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - a bad tick must never kill the loop
            logger.warning("escrow_autosettle_tick_failed", error=str(exc))
        await asyncio.sleep(interval)
