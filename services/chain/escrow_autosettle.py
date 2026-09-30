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
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import EscrowBindingModel, SettlementModel
from db.session import AsyncSessionLocal
from services import profile_capacity, voucher_reaper
from services.chain import allowance_escrow as escrow
from services.chain import escrow_settlement, wallet_lock
from services.settlement_amounts import normalize_amount

logger = structlog.get_logger(__name__)

#: the state a binding sits in between "submitted" and "executed"
DUE_STATE = "finalizing"
SETTLED_STATE = "settled"

#: 判了违约、等窗口到点就去罚没的 binding（见 escrow_settlement.slash_for_task）
DUE_BREACH_STATE = "breaching"

#: 已 bind、钱没动，也永远等不到下一步的绑定（见 reap_stranded）
ACTIVE_STATE = "active"
SLASHED_STATE = "slashed"

#: 「链上钱已经按合约走完了」的终局。回写 `settlements.tx_hash` 必须是真正动钱的那笔，
#: 不能是开窗那笔 `submitSettlement` —— 见 `escrow_settlement._reflect` 里那道闸。
_MONEY_MOVED_STATES = (SETTLED_STATE, SLASHED_STATE)

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


#: 结算单落在这些状态 = 业务侧早就走完了；链上绑定却还是 active，说明当初那一步
#: 链上动作没成功（RPC 抖了、operator 没 gas、进程被重启）。台账说「完了」，
#: 链上说「钱还被占着」—— 必须以链上为准，把它解开。
_TERMINAL_SETTLEMENT_STATES = ("cancelled", "failed", "expired")
_SETTLEMENT_FINAL_TO_CHAIN_ACTION = {
    "refunded": "slash",
    "settled": "settle",
}

#: 刚 bind 完的绑定是 active，而结算单此刻正是 accepted —— 那是正常路径。
#: 留一段余量，别和接单那一步的内联 sync 抢同一个绑定。
STRANDED_GRACE_SECONDS = 60

#: 业务上「钱归谁已经说定了」的结算单：哪怕还挂着 pending_bind，也不该再去锁买方
#: 的钱 —— 锁了也没有人会去提交 / 释放它，反而是把用户额度白占住。
#: （正常路径上根本不会出现：任何需要绑定的动作都会先 materialize，失败就整笔回滚。）
_DECIDED_SETTLEMENT_STATES = ("settled", "refunded", "cancelled", "failed", "expired")


async def stranded_bindings(
    db: AsyncSession, *, now: datetime | None = None, limit: int | None = None
) -> list[EscrowBindingModel]:
    """业务侧已经终局、链上却还占着额度的绑定。

    只挑「结算单已终局」的绑定：这类绑定不可能再被正常流程推进，占着的是买卖双方
    实实在在的授权额 —— 用户链上还有钱，可用额度却显示不足，一单也开不出来。
    """
    stamp = (now or datetime.utcnow()) - timedelta(seconds=STRANDED_GRACE_SECONDS)
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.state == ACTIVE_STATE)
        .where(EscrowBindingModel.created_at <= stamp)
        .order_by(EscrowBindingModel.created_at)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _settlement_status(db: AsyncSession, task_id: str | None) -> str | None:
    if not task_id:
        return None
    row = (
        await db.execute(
            select(SettlementModel).where(SettlementModel.task_id == task_id)
        )
    ).scalars().first()
    return (row.status or "").strip().lower() if row is not None else None


async def reap_stranded(db: AsyncSession, *, now: datetime | None = None) -> list[dict]:
    """把「业务已终局、链上还占着」的绑定推到最后一步，把钱放出来。"""
    if not escrow.escrow_enabled() or not escrow.can_server_settle():
        return []
    freed: list[dict] = []
    for row in await stranded_bindings(db, now=now):
        # 先问链：钱可能早就被划走了（保护期一到，任何地址都能推 finalizeSettlement），
        # 只是我们这边没记上。链上说落定就把台账补齐 —— 再 submit 只会换来一笔 revert。
        if await _reconcile_from_chain(db, row, freed):
            logger.info("escrow_stranded_reconciled_from_chain", binding_id=row.binding_id)
            await db.commit()
            continue
        # 链上窗口已经开着（submit 的交易上链了、写库断在中间）：这一单的钱有了
        # 受款人，合约不再放行 cancelBinding（v4 的状态机闸）。先把台账拉到链上，
        # 否则每一轮都会重发一笔注定被 WrongBindingState 拒掉的交易。
        if await escrow_settlement.adopt_chain_finalizing(db, row=row, task_id=row.task_id):
            logger.info(
                "escrow_stranded_adopted_finalizing", binding_id=row.binding_id, task_id=row.task_id
            )
            await db.commit()
            continue
        status = await _settlement_status(db, row.task_id)
        if status is None:
            continue
        try:
            if status in _TERMINAL_SETTLEMENT_STATES:
                out = await escrow_settlement.cancel_for_task(db, task_id=row.task_id)
            else:
                action = _SETTLEMENT_FINAL_TO_CHAIN_ACTION.get(status)
                if action is None:
                    await db.commit()
                    continue
                if action == "slash":
                    out = await escrow_settlement.slash_for_task(db, task_id=row.task_id)
                else:
                    out = await escrow_settlement.submit_for_task(db, task_id=row.task_id)
        except Exception as exc:  # noqa: BLE001 - 一条解不开不能拖住别的
            logger.warning(
                "escrow_stranded_reap_failed",
                binding_id=row.binding_id,
                task_id=row.task_id,
                settlement_status=status,
                error=str(exc),
            )
            await db.commit()
            continue
        freed.append(
            {"binding_id": row.binding_id, "task_id": row.task_id,
             "settlement_status": status, "result": out}
        )
        logger.info(
            "escrow_stranded_reaped",
            binding_id=row.binding_id,
            task_id=row.task_id,
            settlement_status=status,
        )
        # 每条绑定一个事务：挂牌链上那一步要等回执，行锁不留给下一条。
        await db.commit()
    return freed


def _backed_off(binding_id: str) -> bool:
    last = _failed_at.get(binding_id)
    return last is not None and (time.monotonic() - last) < RETRY_BACKOFF_SECONDS


async def bind_due(db: AsyncSession, *, limit: int | None = None) -> list[dict]:
    """把接单时推迟的链上绑定补上（见 escrow_settlement.bind_for_task_deferred）。

    接单（→ ACCEPTED）现在只在台账上落一个 ``pending_bind`` 就返回，不等 Sepolia
    那个区块。真 bind 在这里跑：一轮最多 ``escrow_autosettle_batch`` 笔。慢还是慢在
    等交易回执上，但这一轮不占用户请求那条路 —— 一单卡住只脏它自己，不会把并发
    下单拖成 504。

    只挑「业务上还站着」的单子：已经取消 / 失败 / 过期的单子不该再锁买方的钱。
    真到终局（已结算 / 已退款）的那几步，``materialize_pending_bind`` 已经在请求
    路径里把绑定补实了，所以这里不该再看到终局的单子。
    """
    stmt = (
        select(SettlementModel)
        .where(SettlementModel.onchain_status == escrow_settlement.PENDING_BIND)
        .where(SettlementModel.settlement_mode == "escrow_allowance")
        .where(SettlementModel.status.not_in(_DECIDED_SETTLEMENT_STATES))
        .order_by(SettlementModel.created_at)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    bound: list[dict] = []
    for model in rows:
        if _backed_off(model.task_id):
            continue
        try:
            out = await escrow_settlement.materialize_pending_bind(db, task_id=model.task_id)
        except Exception as exc:  # noqa: BLE001 - 一轮里坏一笔不能拖死整轮
            _failed_at[model.task_id] = time.monotonic()
            logger.warning(
                "escrow_autosettle_bind_failed", task_id=model.task_id, error=str(exc)
            )
            # 坏一笔也要结事务：补绑在 FOR UPDATE 里等链上回执，那个行锁不该被
            # 下一笔继承（死锁环里就有这么一条边）。
            await db.commit()
            continue
        if out:
            bound.append({"task_id": model.task_id, "result": out})
            logger.info(
                "escrow_settlement_bound_deferred",
                task_id=model.task_id,
                binding_id=out.get("binding_id"),
                amount_usdc=out.get("amount_usdc"),
                tx=out.get("bind_tx_hash"),
            )
        # 同上：一笔补完就结事务，别把行锁一路带到这一轮的最后。
        await db.commit()
    return bound


async def _onchain_state(row: EscrowBindingModel) -> int | None:
    """Ask the contract. An RPC hiccup must not stall the tick, so it returns None.

    问的是**这条绑定自己**那台合约（合约换过地址之后，新合约不认识旧 binding id）。

    问链的 id 一律过 ``chain_binding_id``：账上主键跨合约唯一，换过合约之后会写成
    ``<合约地址>:<链上 id>``（见 ``escrow_settlement.local_binding_id``）。曾经这里
    直接 ``int(row.binding_id)``，于是**每一次合约升级之后**，所有撞上历史号数的绑定
    在对账那一遍里都抛 ValueError —— 链上早就 CANCELLED / SETTLED 了，台账永远停在
    active，worker 每轮刷一条警告，用户的额度也永远回不来（2026-09-21 v5 实测抓到的：
    ``invalid literal for int() with base 10: '0x65eb…:4'``）。
    """
    binding_id = row.binding_id
    try:
        return await asyncio.to_thread(
            escrow.binding_state,
            binding_id=escrow_settlement.chain_binding_id(row),
            contract_address=escrow.binding_contract(row),
        )
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
            settled_amount=0.0 if refunded else normalize_amount(float(row.amount_usdc)),
            refunded_amount=normalize_amount(float(row.amount_usdc)) if refunded else 0.0,
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
    if state in _MONEY_MOVED_STATES and not row.finalize_tx_hash:
        # 链上落定但台账没记下那笔（别人推的 finalize / 没等到回执）：先回链找回来，
        # 再写「结算交易」。找不回来就留空 —— 下游 `_reflect` 不会把不动钱的 submit 写上去。
        await escrow_settlement.recover_money_tx_hash(row, onchain_status=state)
    row.updated_at = datetime.now(UTC)
    # 链上落定的那一刻，账上那行也必须跟着落定：操作台读的是 settlements.onchain_status，
    # 只改 escrow_bindings 会让页面永远停在 finalizing / breaching（F10-2）。
    await escrow_settlement.reflect_final(
        db,
        task_id=row.task_id or "",
        binding=row,
        onchain_status=state,
        tx_hash=row.finalize_tx_hash or row.submit_tx_hash,
    )
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
    state = await _onchain_state(row)
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
    rows = [r for r in await due_bindings(db, now=now) if not _backed_off(r.binding_id)]
    if not rows:
        return settled

    # ── 一问、一广播、一记账，三段分开 ────────────────────────────────────────
    # 原来这里是「一笔一笔：问链 -> 发交易 -> 等回执 -> 写库」，5 笔就是 5 个区块的
    # 串行等待（2026-10-01 实测 settle_due 74~90s，而安静时整轮只要 6s）。链上那两
    # 段是纯网络等待、彼此无关，可以并排；DB 那一段留在本协程里顺序做。
    # 广播本身仍然是串行的 —— nonce 的分配与广播由 allowance_escrow._broadcast_tx
    # 的进程锁护着，等回执在锁外，所以「并排」只是并排等，不会并排抢 nonce。
    states = await asyncio.gather(
        *(_onchain_state(r) for r in rows), return_exceptions=True
    )
    pull: list[EscrowBindingModel] = []
    for row, state in zip(rows, states):
        if isinstance(state, BaseException):  # _onchain_state 自己吞异常，这里只是保险
            state = None
        if state in _CHAIN_DONE:
            # 上一轮发的交易只是慢，不是失败：链上说落定就把台账补上。
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
                "escrow_autosettle_reconciled",
                binding_id=row.binding_id,
                onchain_state=state,
            )
            continue
        pull.append(row)

    if pull:
        results = await asyncio.gather(
            *(
                asyncio.to_thread(
                    escrow.finalize_settlement,
                    binding_id=escrow_settlement.chain_binding_id(row),
                    contract_address=escrow.binding_contract(row),
                )
                for row in pull
            ),
            return_exceptions=True,
        )
        for row, result in zip(pull, results):
            if isinstance(result, wallet_lock.WalletLockError):
                if await _reconcile_from_chain(db, row, settled):
                    continue
                _failed_at[row.binding_id] = time.monotonic()
                logger.warning(
                    "escrow_autosettle_declined", binding_id=row.binding_id, error=str(result)
                )
                continue
            if isinstance(result, BaseException):  # 一条坏不能拖住别的
                if await _reconcile_from_chain(db, row, settled):
                    continue
                _failed_at[row.binding_id] = time.monotonic()
                logger.warning(
                    "escrow_autosettle_failed", binding_id=row.binding_id, error=str(result)
                )
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
    state = await _onchain_state(row)
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


#: 还没走到终局的 binding：链上说钱动了，账上就必须跟着走。
_OPEN_BINDING_STATES = (ACTIVE_STATE, DUE_STATE, DUE_BREACH_STATE)


async def reconcile_from_chain(db: AsyncSession, *, limit: int | None = None) -> list[dict]:
    """链上已经落定的绑定，把台账补齐（状态机对齐的兜底那一遍）。

    正常路径由 ``settle_due`` / ``breach_due`` 回写。这个 tick 兜的是「我们根本没走到
    那一步」的那些：进程重启、receipt 读取超时、或者**别人**先把 ``finalizeSettlement``
    推了（保护期一到，合约对任何地址都放行 —— autosettle 就是靠这个自动放款）。
    链上是最终事实，账上不许停在 finalizing / breaching / active。
    """
    if not escrow.escrow_enabled() or not escrow.can_server_settle():
        return []
    aligned: list[dict] = []
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.state.in_(_OPEN_BINDING_STATES))
        .order_by(EscrowBindingModel.created_at)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    for row in (await db.execute(stmt)).scalars().all():
        if await _reconcile_from_chain(db, row, aligned):
            logger.info(
                "escrow_binding_aligned_from_chain", binding_id=row.binding_id, state=row.state
            )
    return aligned


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
                escrow.finalize_breach,
                binding_id=escrow_settlement.chain_binding_id(row),
                contract_address=escrow.binding_contract(row),
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


async def align_disputed_settlements(db: AsyncSession, *, limit: int | None = None) -> list[dict]:
    """业务还挂在争议里、链上却已经落定 —— 把冻结放掉，业务状态机跟着走。

    ``_record_final`` 会在链上落定的那一刻就地补一次；这一遍兜的是「补的时候撞上
    并发没写成」和「修这条之前就已经卡住的老账」。判据刻意选在**业务状态还停在
    ``disputed``**：那份 ``disputed_credits`` 的冻结由开争议那一笔建立、由裁决落地
    那一笔释放，两者都伴随业务状态进出 DISPUTED，所以这个字就是「冻结还在不在
    账上」的凭据（详见 ``escrow_settlement.settle_chain_terminal_bookkeeping``）。

    卡住的代价是真钱：操作台永久显示「争议冻结 N，等待仲裁推进」，而且
    ``assert_can_release_locked_funds`` 会把解锁一直挡着 —— 用户锁在托管里的钱取不回来。
    """
    if not escrow.escrow_enabled() or not escrow.can_server_settle():
        return []
    stmt = (
        select(SettlementModel)
        .where(SettlementModel.status == "disputed")
        .where(SettlementModel.onchain_status.in_(tuple(_CHAIN_DONE.values())))
        .order_by(SettlementModel.updated_at)
        .limit(limit if limit is not None else settings.escrow_autosettle_batch)
    )
    healed: list[dict] = []
    for row in (await db.execute(stmt)).scalars().all():
        try:
            out = await escrow_settlement.settle_chain_terminal_bookkeeping(
                db, task_id=row.task_id, onchain_status=row.onchain_status or ""
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - 一笔补不上不能拖住别的
            await db.rollback()
            logger.warning(
                "escrow_settlement_dispute_align_failed",
                task_id=row.task_id,
                onchain_status=row.onchain_status,
                error=str(exc),
            )
            continue
        if not out:
            continue
        healed.append({"task_id": row.task_id, **out})
        logger.info(
            "escrow_settlement_dispute_aligned",
            task_id=row.task_id,
            onchain_status=row.onchain_status,
            freeze_released=out.get("freeze_released"),
            status_hops=out.get("status_hops"),
        )
    return healed


async def run_forever() -> None:
    """The loop the API process starts when auto-settlement is switched on."""
    interval = max(3, int(settings.escrow_autosettle_interval_seconds))
    # 放款那一步在结算路由里（和 POST /auto-confirm 共用同一份实现），这里延迟导入：
    # services 层不在导入期反过来依赖 api 包。
    from api.routes.settlement import auto_confirm_expired_settlements
    logger.info("escrow_autosettle_started", interval_seconds=interval)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                _tick_steps: list[tuple[str, float]] = []
                _tick_last = time.perf_counter()

                async def _lap(_name: str) -> None:
                    nonlocal _tick_last
                    _now = time.perf_counter()
                    _tick_steps.append((_name, round(_now - _tick_last, 3)))
                    _tick_last = _now
                    # 每一步各自结事务：这一步的行锁不带到下一步去。死锁环里有一条
                    # 边就是「tick 还攥着上一步拿到的 settlements 行锁，去开下一步」。
                    await db.commit()

                # 接单时推迟的链上绑定：先补上，后面所有「需要 binding」的步骤
                # （开结算窗 / 罚没 / 对账 / 收尾）才看得到它。
                bound = await bind_due(db)
                await _lap("bind_due")
                settled = await settle_due(db)
                await _lap("settle_due")
                slashed = await breach_due(db)
                await _lap("breach_due")
                # 链上已经落定、账上还停在半路的绑定：对齐（别人推了 finalize 也算）。
                aligned = await reconcile_from_chain(db)
                await _lap("reconcile_from_chain")
                # 交付后买方一直不表态、验证层又已经通过的单子：窗口到期就自动放行。
                # 少这一段的话，SETTLEMENT_CONFIRM_WINDOW_HOURS 写的那个 72 小时
                # 就只是个没人执行的承诺，钱一直卡在托管里（P2-4）。
                auto_confirmed = await auto_confirm_expired_settlements(
                    db, limit=settings.escrow_autosettle_batch
                )
                await _lap("auto_confirm_expired_settlements")
                # 业务侧已经终局、链上还占着额度的绑定：把它们推到最后一步，
                # 别让用户的可用额度被一个永远不会再有人推进的绑定吃住。
                freed = await reap_stranded(db)
                await _lap("reap_stranded")
                # 业务还挂在争议里、链上却已经落定：把 disputed 桶里那份冻结放掉，
                # 业务状态机跟着链上走。不放掉的话，操作台永远停在「争议冻结 N」，
                # 用户的钱也永远解不了锁。
                dispute_healed = await align_disputed_settlements(db)
                await _lap("align_disputed_settlements")
                # 过期授权码占住的额度要还回去 —— 否则用户「可用额度」被一张
                # 没人推进的券永久吃光，链上明明还有钱却一单也开不出来。
                reclaimed = await voucher_reaper.expire_due(db)
                await _lap("voucher_reaper.expire_due")
                # 没有任何东西占着、却还挂在 reserved 上的额度：还回可用额度。
                # （释放路径每次「少还一点」都会留下这样的余数，链上的钱一分没少。）
                returned = await voucher_reaper.restore_leaked_reservations(db)
                await _lap("voucher_reaper.restore_leaked")
                # 台账自愈：v2 承诺必须一直等于链上的可用责任额度，否则用户锁仓
                # 之后会看到 0 可用额度（付款码 / 任务合同 / agent 请求凭证全被拒）。
                mirrored = await escrow.reconcile_all_capacity_mirrors(db)
                await _lap("reconcile_capacity_mirrors")
                await db.commit()
                await _lap("commit")
            _slow = sorted(_tick_steps, key=lambda s: s[1], reverse=True)
            if _slow and _slow[0][1] >= 1.0:
                # 一轮 tick 里哪一步慢，直接落日志：这些步骤在请求路径里是同步跑的，
                # 慢一步就是整个 API 卡一步。
                logger.warning("escrow_autosettle_tick_slow",
                               total_s=round(sum(s[1] for s in _tick_steps), 3),
                               steps=_tick_steps)
            if bound:
                logger.info("escrow_autosettle_bind_tick", bound=len(bound))
            if settled:
                logger.info("escrow_autosettle_tick", settled=len(settled))
            if slashed:
                logger.info("escrow_autosettle_breach_tick", slashed=len(slashed))
            if aligned:
                logger.info("escrow_chain_reconcile_tick", aligned=len(aligned))
            if mirrored:
                logger.info("escrow_capacity_mirror_tick", identities=len(mirrored))
            if freed:
                logger.info("escrow_stranded_reap_tick", freed=len(freed))
            if dispute_healed:
                logger.info("escrow_dispute_align_tick", healed=len(dispute_healed))
            if reclaimed:
                logger.info("voucher_expiry_tick", vouchers=len(reclaimed))
            if returned:
                logger.info("voucher_reserved_restore_tick", identities=len(returned))
            if auto_confirmed:
                logger.info("settlement_auto_confirm_tick", settled=len(auto_confirmed))
        except asyncio.CancelledError:
            logger.info("escrow_autosettle_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - a bad tick must never kill the loop
            logger.warning("escrow_autosettle_tick_failed", error=str(exc))
            if "deadlock" in str(exc).lower():
                # 死锁不是「这轮没活干」，是「这轮白干」。Postgres 已经回滚了这一轮，
                # 立刻重来一次就够（等满一个 interval 只会让已经到点的单子多等一轮）。
                await asyncio.sleep(1)
                continue
        await asyncio.sleep(interval)
