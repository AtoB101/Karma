"""Post-launch audit hooks — runtime daily spend alignment."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import RuntimeKeyModel
from services.runtime_daily_spend import record_daily_spend_async


async def record_buyer_trade_launch_daily_spend(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    amount: float,
) -> str | None:
    """
    Mirror launch amount into active Runtime Key daily spend (unified policy limits).

    Returns runtime ``key_id`` when recorded, else None.
    """
    if not settings.trade_launch_record_runtime_daily_spend:
        return None
    now = datetime.utcnow()
    res = await db.execute(
        select(RuntimeKeyModel).where(
            RuntimeKeyModel.karma_identity_id == buyer_identity_id,
            RuntimeKeyModel.status == "active",
            RuntimeKeyModel.expire_at > now,
        )
    )
    row = res.scalars().first()
    if not row:
        return None
    await record_daily_spend_async(db, key_id=row.key_id, amount=float(amount))
    return row.key_id
