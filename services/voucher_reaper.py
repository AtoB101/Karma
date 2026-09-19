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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import CapacityState, VoucherStatus
from db.models.orm import CapacityModel, VoucherModel
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


async def _release(db: AsyncSession, voucher: VoucherModel) -> float:
    """把这张授权码占住的额度原样退回「可用」。"""
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
        released = await _release(db, voucher) if was_reserving else 0.0
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
