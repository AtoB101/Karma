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
