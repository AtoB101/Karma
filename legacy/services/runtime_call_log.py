"""Runtime Key 逐条调用记录 —— 「这把钥匙最近替我做了什么」。

额度表（``runtime_key_daily_spend``）只有汇总：今天花了多少。主人真正想知道的是
「钱是被哪一次调用花掉的、哪一次被拒了」。这张表按请求逐条落账。

写入是旁路：调用方一律走 ``_log_call_safe`` 包一层，写不进日志绝不影响 agent 的请求 ——
一把钥匙能不能花钱，由权限、额度和服务端状态决定，不由日志表决定。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import RuntimeKeyCallLogModel

MAX_DETAIL_CHARS = 200
MAX_LIMIT = 100
DEFAULT_LIMIT = 20


async def record_key_call(
    db: AsyncSession,
    *,
    key_id: str,
    karma_identity_id: str,
    endpoint: str,
    method: str = "POST",
    outcome: str = "ok",
    http_status: int = 200,
    amount: float | None = None,
    detail: str = "",
) -> RuntimeKeyCallLogModel:
    row = RuntimeKeyCallLogModel(
        key_id=str(key_id or ""),
        karma_identity_id=str(karma_identity_id or ""),
        endpoint=str(endpoint or "")[:64],
        method=str(method or "POST")[:8],
        outcome=str(outcome or "ok")[:16],
        http_status=int(http_status),
        amount=amount,
        detail=str(detail or "")[:MAX_DETAIL_CHARS],
    )
    db.add(row)
    await db.flush()
    return row


def clamp_limit(limit: int | None) -> int:
    try:
        value = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


async def list_key_calls(
    db: AsyncSession, *, key_id: str, limit: int | None = DEFAULT_LIMIT
) -> list[RuntimeKeyCallLogModel]:
    res = await db.execute(
        select(RuntimeKeyCallLogModel)
        .where(RuntimeKeyCallLogModel.key_id == str(key_id or ""))
        .order_by(RuntimeKeyCallLogModel.id.desc())
        .limit(clamp_limit(limit))
    )
    return list(res.scalars().all())


def call_view(row: RuntimeKeyCallLogModel) -> dict:
    return {
        "endpoint": row.endpoint,
        "method": row.method,
        "outcome": row.outcome,
        "http_status": int(row.http_status or 0),
        "amount": row.amount,
        "detail": row.detail or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
