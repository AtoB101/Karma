"""Durable Runtime Key daily spend tracking (multi-instance safe)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import RuntimeKeyDailySpendModel
from services.runtime_key_service import get_daily_used as get_daily_used_memory
from services.runtime_key_service import record_daily_spend as record_daily_spend_memory

_EPS = 1e-9


def _today_iso() -> str:
    return date.today().isoformat()


async def get_daily_used_async(db: AsyncSession, key_id: str) -> float:
    if not settings.runtime_daily_spend_persist:
        return get_daily_used_memory(key_id)
    row = await db.get(RuntimeKeyDailySpendModel, (key_id, _today_iso()))
    if row:
        return float(row.amount_used)
    return get_daily_used_memory(key_id)


async def _add_amount(db: AsyncSession, *, key_id: str, amount: float) -> None:
    """给当日行原子加账；行还不存在就建一行。

    并发下两个请求可能同时发现"行不存在"并一起插入，撞主键的一方回退到
    SAVEPOINT 再来一轮 —— 那一轮的 UPDATE 就能看见对方刚提交的行。
    """
    spend_date = _today_iso()
    for _ in range(2):
        now = datetime.utcnow()
        res = await db.execute(
            update(RuntimeKeyDailySpendModel)
            .where(
                RuntimeKeyDailySpendModel.key_id == key_id,
                RuntimeKeyDailySpendModel.spend_date == spend_date,
            )
            .values(
                amount_used=RuntimeKeyDailySpendModel.amount_used + float(amount),
                updated_at=now,
            )
        )
        if res.rowcount == 1:
            return
        try:
            async with db.begin_nested():
                db.add(
                    RuntimeKeyDailySpendModel(
                        key_id=key_id,
                        spend_date=spend_date,
                        amount_used=float(amount),
                        updated_at=now,
                    )
                )
                await db.flush()
            return
        except IntegrityError:
            continue


async def record_daily_spend_async(db: AsyncSession, *, key_id: str, amount: float) -> None:
    """记一笔当日花费（不做上限判断）。加账是原子的，并发不会丢更新。"""
    record_daily_spend_memory(key_id=key_id, amount=amount)
    if not settings.runtime_daily_spend_persist:
        return
    await _add_amount(db, key_id=key_id, amount=float(amount))


async def try_reserve_daily_spend(
    db: AsyncSession, *, key_id: str, amount: float, daily_limit: float
) -> bool:
    """原子地「占额度」：只有「当日已用 + amount ≤ daily_limit」才真的加账。

    返回 ``True`` = 占到额度；``False`` = 这一笔会顶过日上限，调用方必须让这笔业务作废
    （抛错回滚，连带撤掉刚建出来的凭证）。

    为什么不能用「先读再算再写」：那是三步，并发请求会读到同一个旧值。实测线上
    「单笔 5 / 日上限 11」并发 6 笔放行了 3 笔 = 15，日上限形同虚设。
    这里的 UPDATE 会拿到行锁，PostgreSQL 在 READ COMMITTED 下基于最新行重新评估
    ``WHERE``，并发调用因此被串行化。
    """
    amt = float(amount)
    limit = float(daily_limit)
    if not settings.runtime_daily_spend_persist:
        used = get_daily_used_memory(key_id)
        if used + amt > limit + _EPS:
            return False
        record_daily_spend_memory(key_id=key_id, amount=amt)
        return True
    spend_date = _today_iso()
    for _ in range(2):
        now = datetime.utcnow()
        res = await db.execute(
            update(RuntimeKeyDailySpendModel)
            .where(
                RuntimeKeyDailySpendModel.key_id == key_id,
                RuntimeKeyDailySpendModel.spend_date == spend_date,
                RuntimeKeyDailySpendModel.amount_used + amt <= limit + _EPS,
            )
            .values(
                amount_used=RuntimeKeyDailySpendModel.amount_used + amt,
                updated_at=now,
            )
        )
        if res.rowcount == 1:
            record_daily_spend_memory(key_id=key_id, amount=amt)
            return True
        # 更新 0 行有两种可能：行已经存在（= 顶到上限了），或者行还没建出来。
        if await db.get(RuntimeKeyDailySpendModel, (key_id, spend_date)) is not None:
            return False
        if amt > limit + _EPS:
            return False
        try:
            async with db.begin_nested():
                db.add(
                    RuntimeKeyDailySpendModel(
                        key_id=key_id,
                        spend_date=spend_date,
                        amount_used=amt,
                        updated_at=now,
                    )
                )
                await db.flush()
        except IntegrityError:
            # 对方并发插了同一行，再来一轮让 UPDATE 看见它。
            continue
        record_daily_spend_memory(key_id=key_id, amount=amt)
        return True
    return False
