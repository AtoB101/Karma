"""过期的授权码必须把额度还回来。

授权码（voucher）被卖方接受的那一刻，买方的可用额度就被挪进 ``reserved`` —— 这是对的，
不然同一个钱包能拿同一笔授权开出两张互相打脸的单子。问题是这条占用**只有**「结算完成」
这一条路会释放，而 ``accept_voucher_row`` 里的过期分支只在「有人再拿它接一次单」时才会
跑到。于是一张被接受、然后没人推进的授权码，会把买方的额度一直冻着 —— **连过期都不解冻**。

线上实测（2026-09-19，W1）：4 张停在 ``accepted`` 的授权码共 22 USDC，把
``available_credits`` 吃成 0；而链上该钱包对托管合约还有 12 USDC 真划得动。结果
``POST /v1/contracts`` 一律 409「escrow_amount exceeds buyer available_credits」——
钱明明还在用户自己钱包里，一单也开不出来。

这里补上那一步：有效期一过就作废；已经占用额度的，把占用原样退回「可用」。
"""
from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import CapacityState, VoucherStatus
from db.models.orm import CapacityModel, SettlementModel, VoucherModel
from services import atomic_ledger
from services.capacity_ledger import assert_capacity_invariants

logger = structlog.get_logger(__name__)

#: 还没被接受：没有占用任何额度，作废即可
PENDING_STATUS = (VoucherStatus.CREATED.value,)
#: 已经接受：接受那一刻就把买方的可用额度挪进了 reserved，作废必须把额度还回去
RESERVING_STATUS = (VoucherStatus.ACCEPTED.value,)
#: 会被回收的状态
SWEEPABLE_STATUS = PENDING_STATUS + RESERVING_STATUS


def enabled() -> bool:
    return bool(getattr(settings, "voucher_expiry_sweep_enabled", True))


def batch_size() -> int:
    try:
        return max(1, int(settings.voucher_expiry_sweep_batch))
    except (TypeError, ValueError):
        return 200


async def due_vouchers(
    db: AsyncSession, *, now: datetime | None = None, limit: int | None = None
) -> list[VoucherModel]:
    """已经过了有效期、还停在「待接单 / 已接单」的授权码。"""
    stamp = now or datetime.utcnow()
    stmt = (
        select(VoucherModel)
        .where(VoucherModel.status.in_(SWEEPABLE_STATUS))
        .where(VoucherModel.expiry_time <= stamp)
        .order_by(VoucherModel.expiry_time)
        .limit(limit if limit is not None else batch_size())
    )
    return list((await db.execute(stmt)).scalars().all())


def _assert_capacity(cap: CapacityModel | None) -> None:
    if cap is None:
        return
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


async def release_reservation(db: AsyncSession, voucher: VoucherModel) -> float:
    """把这张授权码占住的额度原样退回「可用」。

    公开入口：除了「过期回收」，取消订单也要走这一步（见
    ``settlement_voucher.cancel_voucher_reservation_for_task``）—— 否则一张被取消
    的授权码会把买方的可用额度一直冻到有效期结束。
    """
    amount = round(float(voucher.bill_credit_amount or 0.0), 6)
    if amount <= 0:
        return 0.0
    try:
        await atomic_ledger.apply_delta_or_raise(
            db,
            CapacityModel,
            "identity_id",
            voucher.buyer_identity_id,
            {"reserved_credits": -amount, "available_credits": amount},
            guards=[(lambda C, _need=amount: C.reserved_credits + 1e-9 >= _need)],
            message="reserved credits no longer cover this voucher",
        )
    except atomic_ledger.LedgerConflict:
        # 占用已经不在了（已经被别的路径释放过，或者这张券的额度从没真正预留成功）：
        # 额度不能凭空加，作废照做，把这件事记响一点。
        logger.warning(
            "voucher_expiry_release_declined",
            voucher_id=voucher.voucher_id,
            identity_id=voucher.buyer_identity_id,
            amount_usdc=amount,
        )
        return 0.0
    _assert_capacity(await atomic_ledger.reload(db, CapacityModel, voucher.buyer_identity_id))
    return amount


async def expire_due(
    db: AsyncSession, *, now: datetime | None = None, limit: int | None = None
) -> list[dict]:
    """作废所有过期的授权码，并把它们占的额度还回去。返回被回收的那几张。"""
    if not enabled():
        return []
    reclaimed: list[dict] = []
    for voucher in await due_vouchers(db, now=now, limit=limit):
        was_reserving = voucher.status in RESERVING_STATUS
        released = await release_reservation(db, voucher) if was_reserving else 0.0
        voucher.status = VoucherStatus.EXPIRED.value
        if hasattr(voucher, "expired_at"):
            voucher.expired_at = datetime.utcnow()
        if released > 0:
            reclaimed.append(
                {
                    "voucher_id": voucher.voucher_id,
                    "identity_id": voucher.buyer_identity_id,
                    "released_usdc": released,
                }
            )
        logger.info(
            "voucher_expired",
            voucher_id=voucher.voucher_id,
            buyer_identity_id=voucher.buyer_identity_id,
            released_usdc=released,
        )
    return reclaimed


#: 结算单走到这三个状态 = 这单不会再从 ``reserved`` 里拿钱了（见 core.settlement.engine）。
#: 其余状态（accepted / delivered / disputed / arbitrated / frozen …）都还在路上。
_TERMINAL_SETTLEMENT_STATUSES = ("settled", "refunded", "cancelled")


async def restore_leaked_reservations(db: AsyncSession, *, limit: int = 200) -> list[dict]:
    """把「没有任何东西占着、却还挂在 ``reserved`` 上」的额度还给「可用额度」。

    占用只有一个来源：卖方接单那一刻把买方的可用额度挪进 ``reserved``
    （``voucher_lifecycle.accept_voucher_row``）。所以这条不变式必须成立：

        ``reserved == Σ (还在 accepted 的授权码的 bill_credit_amount)``

    每条释放路径都带守卫（``reserved >= amount``），只要历史上出现过一次「少还一点」
    —— 老 bug、人工修库、金额口径改过 —— 余数就永远挂在 ``reserved`` 上：链上钱一分
    没少，用户的可用额度却少一截，而且再也没有任何东西会去动它。

    线上实测（2026-09-20，W1）：``reserved`` 剩 0.055，名下一张活券、一张在途单都没有。

    只在**这个身份名下没有任何在途结算单**时才动手：在途单自己也占着 ``reserved``，
    光比券会把它占的那部分当成泄漏放出去 —— 那就是凭空多发额度。宁可不动。
    """
    rows = (
        await db.execute(
            select(CapacityModel)
            .where(CapacityModel.reserved_credits > 1e-9)
            .order_by(CapacityModel.identity_id)
            .limit(limit)
        )
    ).scalars().all()
    healed: list[dict] = []
    for cap in rows:
        inflight = (
            await db.execute(
                select(func.count())
                .select_from(SettlementModel)
                .where(SettlementModel.client_agent_id == cap.identity_id)
                .where(SettlementModel.status.notin_(_TERMINAL_SETTLEMENT_STATUSES))
            )
        ).scalar_one()
        if inflight:
            continue
        held = (
            await db.execute(
                select(func.coalesce(func.sum(VoucherModel.bill_credit_amount), 0.0))
                .where(VoucherModel.buyer_identity_id == cap.identity_id)
                .where(VoucherModel.status == VoucherStatus.ACCEPTED.value)
            )
        ).scalar_one()
        excess = round(float(cap.reserved_credits or 0.0) - float(held or 0.0), 6)
        if excess <= 1e-9:
            continue
        try:
            await atomic_ledger.apply_delta_or_raise(
                db,
                CapacityModel,
                "identity_id",
                cap.identity_id,
                {"reserved_credits": -excess, "available_credits": excess},
                guards=[(lambda C, _need=excess: C.reserved_credits + 1e-9 >= _need)],
                message="reserved credits are not held by any live voucher",
            )
        except atomic_ledger.LedgerConflict:
            logger.warning(
                "reserved_restore_declined", identity_id=cap.identity_id, excess_usdc=excess
            )
            continue
        _assert_capacity(await atomic_ledger.reload(db, CapacityModel, cap.identity_id))
        healed.append({"identity_id": cap.identity_id, "returned_usdc": excess})
        logger.info(
            "reserved_restored", identity_id=cap.identity_id, returned_usdc=excess
        )
    return healed
