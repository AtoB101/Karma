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
from services import profile_capacity, voucher_reaper
from services.chain import allowance_escrow as escrow
from services.chain import wallet_lock

logger = structlog.get_logger(__name__)

#: the state a binding sits in between "submitted" and "executed"
DUE_STATE = "finalizing"
SETTLED_STATE = "settled"

#: 判了违约、等窗口到点就去罚没的 binding（见 escrow_settlement.slash_for_task）
DUE_BREACH_STATE = "breaching"
SLASHED_STATE = "slashed"

#: what the *chain* says about a binding (see allowance_escrow.BINDING_STATE)
CHAIN_FINALIZING = 2
CHAIN_SETTLED = 3
CHAIN_SLASHED = 4
CHAIN_CANCELLED = 5
_CHAIN_DONE = {
    CHAIN_SETTLED: SETTLED_STATE,
    CHAIN_SLASHED: "slashed",
    CHAIN_CANCELLED: "cancelled",
}

#: Once an attempt fails, leave that binding alone for a while. The usual causes
#: (an allowance that is not funded yet, an RPC hiccup, a revert) do not fix
#: themselves within one tick, and the operator account pays for every retry.
RETRY_BACKOFF_SECONDS = 120.0

#: 合约要的是 ``block.timestamp >= settleAfter``，而我们判断「到点了没」用的是本机
#: 时钟。两者差个一两秒很正常，卡在边界上发出去的 finalize 会被 SettleDelayActive
#: 拒掉 —— 白烧一笔 operator 的手续费，这一单还要再等一整个退避周期。留一点余量。
SETTLE_DELAY_MARGIN_SECONDS = 5
_failed_at: dict[str, float] = {}


def reset_backoff() -> None:
    """Forget failed attempts (tests, and an operator-triggered retry)."""
    _failed_at.clear()


async def due_bindings(
    db: AsyncSession, *, now: int | None = None, limit: int | None = None
) -> list[EscrowBindingModel]:
    """Bindings whose challenge window has elapsed and that nobody executed.

    留了 ``SETTLE_DELAY_MARGIN_SECONDS`` 的余量：卡在 ``settleAfter`` 那一刻发出去
    会被合约以 ``SettleDelayActive`` 拒掉，operator 白付一笔 gas，还要再等一整个退避。
    """
    stamp = int(time.time()) if now is None else int(now)
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.state == DUE_STATE)
        .where(EscrowBindingModel.pull_after.is_not(None))
        .where(EscrowBindingModel.pull_after > 0)
        .where(EscrowBindingModel.pull_after + SETTLE_DELAY_MARGIN_SECONDS <= stamp)
        .order_by(EscrowBindingModel.pull_after)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    return list((await db.execute(stmt)).scalars().all())


async def due_breach_bindings(
    db: AsyncSession, *, now: int | None = None, limit: int | None = None
) -> list[EscrowBindingModel]:
    """判了违约、窗口已过点、还没罚没的 binding。"""
    stamp = int(time.time()) if now is None else int(now)
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.state == DUE_BREACH_STATE)
        .where(EscrowBindingModel.pull_after.is_not(None))
        .where(EscrowBindingModel.pull_after > 0)
        .where(EscrowBindingModel.pull_after + SETTLE_DELAY_MARGIN_SECONDS <= stamp)
        .order_by(EscrowBindingModel.pull_after)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    return list((await db.execute(stmt)).scalars().all())


def _backed_off(binding_id: str) -> bool:
    last = _failed_at.get(binding_id)
    return last is not None and (time.monotonic() - last) < RETRY_BACKOFF_SECONDS


async def _onchain_state(binding_id: str) -> int | None:
    """Ask the contract. An RPC hiccup must not stall the tick, so it returns None."""
    try:
        return await asyncio.to_thread(escrow.binding_state, binding_id=int(binding_id))
    except Exception as exc:  # noqa: BLE001 - read-only, best effort
        logger.warning(
            "escrow_autosettle_state_read_failed", binding_id=binding_id, error=str(exc)
        )
        return None


async def _release_quota(db: AsyncSession, row: EscrowBindingModel, *, refunded: bool) -> None:
    """结清这一单占用的子身份额度（纯台账；失败只记日志，不碰链上事实）。"""
    if not row.buyer_profile_id:
        return
    try:
        await profile_capacity.release_profile_credits(
            db,
            profile_id=row.buyer_profile_id,
            settled_amount=0.0 if refunded else float(row.amount_usdc),
            refunded_amount=float(row.amount_usdc) if refunded else 0.0,
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping, not money
        logger.warning(
            "escrow_autosettle_profile_release_failed",
            binding_id=row.binding_id,
            profile_id=row.buyer_profile_id,
            error=str(exc),
        )


async def _record_final(
    db: AsyncSession,
    row: EscrowBindingModel,
    *,
    state: str,
    tx_hash: str | None,
    refunded: bool = False,
) -> dict:
    """Write the outcome, clear the quota, then re-read the bills (best effort).

    The money has already moved on-chain by the time we get here, so the binding
    row is committed first: a wobbly RPC must never cost us the record of a real
    settlement.
    """
    row.state = state
    if tx_hash:
        row.finalize_tx_hash = tx_hash
    row.updated_at = datetime.now(UTC)
    await _release_quota(db, row, refunded=refunded)
    await db.commit()
    for party in (row.buyer_identity_id, row.seller_identity_id):
        if not party:
            continue
        try:
            await escrow.sync_commits(db, party)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - bookkeeping, not money
            await db.rollback()
            logger.warning("escrow_autosettle_sync_failed", identity_id=party, error=str(exc))
    return {
        "binding_id": row.binding_id,
        "finalize_tx_hash": row.finalize_tx_hash,
        "amount_usdc": row.amount_usdc,
    }


async def _reconcile_from_chain(
    db: AsyncSession, row: EscrowBindingModel, settled: list[dict]
) -> bool:
    """链上已经落定就别再发交易 —— 把台账补上，返回 True。

    这一条是为了「我们没等到回执，但交易其实上链了」：receipt 等待超时只说明
    我们没看见。旧代码把这当成失败，于是钱已经 wallet→wallet 划走，绑定行却永远
    停在 finalizing，它占的子身份额度也永远不释放。链说了算。
    """
    state = await _onchain_state(row.binding_id)
    if state not in _CHAIN_DONE:
        return False
    _failed_at.pop(row.binding_id, None)
    settled.append(
        await _record_final(
            db,
            row,
            state=_CHAIN_DONE[state],
            tx_hash=row.finalize_tx_hash,
            refunded=state == CHAIN_CANCELLED,
        )
    )
    logger.info(
        "escrow_autosettle_reconciled", binding_id=row.binding_id, onchain_state=state
    )
    return True


async def settle_due(db: AsyncSession, *, now: int | None = None) -> list[dict]:
    """Execute every due binding. Returns the ones that actually settled."""
    if not escrow.escrow_enabled() or not escrow.can_server_settle():
        return []
    settled: list[dict] = []
    for row in await due_bindings(db, now=now):
        if _backed_off(row.binding_id):
            continue
        # 先问链：可能上一轮发的交易只是慢，不是失败。
        if await _reconcile_from_chain(db, row, settled):
            continue
        try:
            result = await asyncio.to_thread(
                escrow.finalize_settlement, binding_id=int(row.binding_id)
            )
        except wallet_lock.WalletLockError as exc:
            if await _reconcile_from_chain(db, row, settled):
                continue
            _failed_at[row.binding_id] = time.monotonic()
            logger.warning(
                "escrow_autosettle_declined", binding_id=row.binding_id, error=str(exc)
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one bad binding must not stop the rest
            if await _reconcile_from_chain(db, row, settled):
                continue
            _failed_at[row.binding_id] = time.monotonic()
            logger.warning("escrow_autosettle_failed", binding_id=row.binding_id, error=str(exc))
            continue
        _failed_at.pop(row.binding_id, None)
        settled.append(
            await _record_final(
                db, row, state=SETTLED_STATE, tx_hash=result.get("finalize_tx_hash")
            )
        )
        logger.info(
            "escrow_autosettle_settled",
            binding_id=row.binding_id,
            tx=row.finalize_tx_hash,
            amount_usdc=row.amount_usdc,
        )
    return settled


async def _reconcile_breach_from_chain(
    db: AsyncSession, row: EscrowBindingModel, slashed: list[dict]
) -> bool:
    """链上已经落定（罚没/结算/取消）就别再发交易，把台账补上。"""
    state = await _onchain_state(row.binding_id)
    if state not in _CHAIN_DONE:
        return False
    _failed_at.pop(row.binding_id, None)
    slashed.append(
        await _record_final(
            db, row, state=_CHAIN_DONE[state], tx_hash=row.finalize_tx_hash, refunded=True
        )
    )
    logger.info("escrow_autosettle_breach_reconciled", binding_id=row.binding_id, onchain_state=state)
    return True


async def breach_due(db: AsyncSession, *, now: int | None = None) -> list[dict]:
    """执行到期罚没：卖方质押 -> 买方钱包。"""
    if not escrow.escrow_enabled() or not escrow.can_server_settle():
        return []
    slashed: list[dict] = []
    for row in await due_breach_bindings(db, now=now):
        if _backed_off(row.binding_id):
            continue
        if await _reconcile_breach_from_chain(db, row, slashed):
            continue
        try:
            result = await asyncio.to_thread(
                escrow.finalize_breach, binding_id=int(row.binding_id)
            )
        except wallet_lock.WalletLockError as exc:
            if await _reconcile_breach_from_chain(db, row, slashed):
                continue
            _failed_at[row.binding_id] = time.monotonic()
            logger.warning(
                "escrow_autosettle_breach_declined", binding_id=row.binding_id, error=str(exc)
            )
            continue
        except Exception as exc:  # noqa: BLE001 - 一条罚没不能拖住其他绑定
            if await _reconcile_breach_from_chain(db, row, slashed):
                continue
            _failed_at[row.binding_id] = time.monotonic()
            logger.warning(
                "escrow_autosettle_breach_failed", binding_id=row.binding_id, error=str(exc)
            )
            continue
        _failed_at.pop(row.binding_id, None)
        slashed.append(
            await _record_final(
                db,
                row,
                state=SLASHED_STATE,
                tx_hash=result.get("breach_tx_hash"),
                refunded=True,
            )
        )
        logger.info(
            "escrow_autosettle_slashed",
            binding_id=row.binding_id,
            tx=row.finalize_tx_hash,
            stake_usdc=row.stake_usdc,
        )
    return slashed


async def run_forever() -> None:
    """The loop the API process starts when auto-settlement is switched on."""
    interval = max(3, int(settings.escrow_autosettle_interval_seconds))
    logger.info("escrow_autosettle_started", interval_seconds=interval)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                settled = await settle_due(db)
                slashed = await breach_due(db)
                # 过期授权码占住的额度要还回去 —— 否则用户「可用额度」被一张
                # 没人推进的券永久吃光，链上明明还有钱却一单也开不出来。
                reclaimed = await voucher_reaper.expire_due(db)
                # 台账自愈：v2 承诺必须一直等于链上的可用责任额度，否则用户锁仓
                # 之后会看到 0 可用额度（付款码 / 任务合同 / agent 请求凭证全被拒）。
                mirrored = await escrow.reconcile_all_capacity_mirrors(db)
                await db.commit()
            if settled:
                logger.info("escrow_autosettle_tick", settled=len(settled))
            if slashed:
                logger.info("escrow_autosettle_breach_tick", slashed=len(slashed))
            if mirrored:
                logger.info("escrow_capacity_mirror_tick", identities=len(mirrored))
            if reclaimed:
                logger.info("voucher_expiry_tick", vouchers=len(reclaimed))
        except asyncio.CancelledError:
            logger.info("escrow_autosettle_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - a bad tick must never kill the loop
            logger.warning("escrow_autosettle_tick_failed", error=str(exc))
        await asyncio.sleep(interval)
