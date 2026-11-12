"""Durable Runtime Key daily spend tracking (multi-instance safe)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import RuntimeKeyDailySpendModel
from services.runtime_key_service import get_daily_used as get_daily_used_memory
from services.runtime_key_service import record_daily_spend as record_daily_spend_memory


def _today_iso() -> str:
    return date.today().isoformat()


async def get_daily_used_async(db: AsyncSession, key_id: str) -> float:
    if not settings.runtime_daily_spend_persist:
        return get_daily_used_memory(key_id)
    row = await db.get(RuntimeKeyDailySpendModel, (key_id, _today_iso()))
    if row:
        return float(row.amount_used)
    return get_daily_used_memory(key_id)


async def record_daily_spend_async(db: AsyncSession, *, key_id: str, amount: float) -> None:
    record_daily_spend_memory(key_id=key_id, amount=amount)
    if not settings.runtime_daily_spend_persist:
        return
    spend_date = _today_iso()
    row = await db.get(RuntimeKeyDailySpendModel, (key_id, spend_date))
    if row:
        row.amount_used = float(row.amount_used) + float(amount)
        row.updated_at = datetime.utcnow()
    else:
        db.add(
            RuntimeKeyDailySpendModel(
                key_id=key_id,
                spend_date=spend_date,
                amount_used=float(amount),
                updated_at=datetime.utcnow(),
            )
        )
    await db.flush()
