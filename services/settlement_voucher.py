"""Link settlements to vouchers — mark voucher consumed after terminal settlement."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import VoucherStatus
from db.models.orm import SettlementModel, VoucherModel


async def mark_voucher_used_if_linked(db: AsyncSession, task_id: str) -> None:
    """P0: one-time voucher becomes USED after escrow for this task is fully resolved."""
    result = await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    settlement = result.scalar_one_or_none()
    if not settlement or not settlement.voucher_id:
        return
    voucher = await db.get(VoucherModel, settlement.voucher_id)
    if not voucher:
        return
    if voucher.status == VoucherStatus.ACCEPTED.value:
        voucher.status = VoucherStatus.USED.value


async def cancel_voucher_reservation_for_task(db: AsyncSession, task_id: str) -> dict | None:
    """这一单被取消：立刻把买方被占住的额度放回去，别等授权码自己到期。

    ``accept_voucher_row`` 在卖方接单那一刻就把买方的可用额度挪进了 ``reserved``，
    而过去只有两条路会把它放回来：结算完成（``apply_capacity_resolution``）或者
    授权码过期（``voucher_reaper``）。取消订单两条都不走 —— 链上 binding 撤销了、
    钱一分没动，操作台上的可用额度却被一张没人推进的券吃住，要等有效期（默认 7 天）
    才回来。实测（2026-09-20）：W1 的 40.00 USDC 可用额度被 12 张「订单已取消」的
    授权码占着。

    幂等：券一旦不在 created / accepted 状态就直接返回；额度释放本身带守卫
    （``voucher_reaper.release_reservation``），重复调用不会凭空加额度。
    """
    settlement = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().first()
    if settlement is None or not (settlement.voucher_id or "").strip():
        return None
    voucher = await db.get(VoucherModel, settlement.voucher_id)
    if voucher is None:
        return None
    if voucher.status not in (VoucherStatus.CREATED.value, VoucherStatus.ACCEPTED.value):
        return None
    released = 0.0
    if voucher.status == VoucherStatus.ACCEPTED.value:
        from services import voucher_reaper

        released = await voucher_reaper.release_reservation(db, voucher)
    voucher.status = VoucherStatus.CANCELLED.value
    await db.flush()
    return {"voucher_id": voucher.voucher_id, "released_usdc": released}
