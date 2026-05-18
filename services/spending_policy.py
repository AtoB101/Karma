"""Pre-launch spending policy checks (automation-policy limits + daily budget)."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentAutomationPolicyModel, TradeOrderModel


async def sum_buyer_launch_amount_today(db: AsyncSession, buyer_identity_id: str) -> float:
    today_start = datetime.combine(date.today(), datetime.min.time())
    res = await db.execute(
        select(TradeOrderModel).where(
            TradeOrderModel.buyer_identity_id == buyer_identity_id,
            TradeOrderModel.created_at >= today_start,
            TradeOrderModel.status.not_in(("rejected", "failed")),
        )
    )
    total = 0.0
    for row in res.scalars():
        spec = row.decomposed_spec or {}
        total += float(spec.get("amount") or 0)
    return total


async def assert_pre_launch_spending_policy(
    db: AsyncSession,
    *,
    buyer_policy: AgentAutomationPolicyModel,
    additional_amount: float,
) -> None:
    """Enforce buyer daily_limit across successful trade launches today."""
    daily = float(buyer_policy.daily_limit or 0)
    if daily <= 0:
        return
    used = await sum_buyer_launch_amount_today(db, buyer_policy.karma_identity_id)
    projected = used + float(additional_amount)
    if projected > daily + 1e-9:
        raise HTTPException(
            status_code=409,
            detail=(
                f"trade launch would exceed buyer daily_limit: used={used:.6f} "
                f"+ amount={additional_amount:.6f} > daily_limit={daily:.6f}"
            ),
        )
