"""Guards monetary release to the seller without on-chain execution evidence (KSA2-006)."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import ToolStatus
from db.stores.receipt_store import PostgresReceiptStore


async def ensure_success_execution_receipt_before_seller_payout(
    db: AsyncSession,
    task_id: str,
    *,
    settled_amount: float,
) -> None:
    """
    Any settlement path that credits the seller (released_amount > 0) must show at least one
    successful execution receipt for the task, unless disabled via settings.
    """
    if not settings.settlement_requires_success_execution_receipt_for_seller_release:
        return
    if settled_amount <= 1e-6:
        return
    rstore = PostgresReceiptStore(db)
    receipts = await rstore.list_by_task(task_id)
    if not any(r.status == ToolStatus.SUCCESS for r in receipts):
        raise HTTPException(
            status_code=409,
            detail=(
                "at least one successful execution receipt is required before releasing funds to the seller"
            ),
        )
