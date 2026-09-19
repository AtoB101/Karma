"""操作台站内提醒 —— 主人自己的钥匙/授权发生了什么，落库留痕。

为什么要落库而不是只在页面上闪一行：取消绑定是不可逆动作（钥匙立刻谁都花不了，
agent 要重新申请接入）。闪一行提示关掉就没了；落一条记录，主人下次进操作台仍然看得见，
并且要点过才消。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import ConsoleNoticeModel

# agent 申请接入、主人输码成功 —— 这把钥匙从此代表主人花钱。
NOTICE_KEY_BOUND = "key_bound"
# 主人亲手取消绑定 —— 钥匙回到未激活，谁都花不了。
NOTICE_KEY_UNBOUND = "key_unbound"

MAX_LIMIT = 100
DEFAULT_LIMIT = 20


async def add_notice(
    db: AsyncSession,
    *,
    karma_identity_id: str,
    kind: str,
    payload: dict | None = None,
) -> ConsoleNoticeModel:
    row = ConsoleNoticeModel(
        karma_identity_id=str(karma_identity_id or ""),
        kind=str(kind or "")[:32],
        payload=dict(payload or {}),
    )
    db.add(row)
    await db.flush()
    return row


async def list_notices(
    db: AsyncSession,
    *,
    karma_identity_id: str,
    limit: int | None = DEFAULT_LIMIT,
    unread_only: bool = False,
) -> list[ConsoleNoticeModel]:
    try:
        capped = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        capped = DEFAULT_LIMIT
    capped = max(1, min(capped, MAX_LIMIT))
    stmt = select(ConsoleNoticeModel).where(
        ConsoleNoticeModel.karma_identity_id == str(karma_identity_id or "")
    )
    if unread_only:
        stmt = stmt.where(ConsoleNoticeModel.read_at.is_(None))
    res = await db.execute(stmt.order_by(ConsoleNoticeModel.id.desc()).limit(capped))
    return list(res.scalars().all())


async def unread_notice_count(db: AsyncSession, *, karma_identity_id: str) -> int:
    res = await db.execute(
        select(func.count())
        .select_from(ConsoleNoticeModel)
        .where(
            ConsoleNoticeModel.karma_identity_id == str(karma_identity_id or ""),
            ConsoleNoticeModel.read_at.is_(None),
        )
    )
    return int(res.scalar_one() or 0)


async def ack_notices(
    db: AsyncSession,
    *,
    karma_identity_id: str,
    notice_ids: list[int] | None = None,
) -> int:
    """点过就算读过。不给 id 就是「全部标记已读」。"""
    stmt = (
        update(ConsoleNoticeModel)
        .where(
            ConsoleNoticeModel.karma_identity_id == str(karma_identity_id or ""),
            ConsoleNoticeModel.read_at.is_(None),
        )
        .values(read_at=datetime.utcnow())
    )
    if notice_ids:
        ids = [int(i) for i in notice_ids]
        stmt = stmt.where(ConsoleNoticeModel.id.in_(ids))
    res = await db.execute(stmt)
    await db.flush()
    return int(res.rowcount or 0)


def notice_view(row: ConsoleNoticeModel) -> dict:
    return {
        "id": int(row.id),
        "kind": row.kind,
        "payload": row.payload or {},
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "read": row.read_at is not None,
    }
