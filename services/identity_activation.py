"""Identity activation — 主身份刷脸认证通过才算「激活」。

规则（用户拍板）：
- 连接钱包只拿到身份号（对外显示 Kid1…），此时是**未激活**状态。
- 主身份本人完成实名认证（证件 + 刷脸，即 ``identity_verifications.status == "verified"``）
  才算激活；信誉记录从激活这一刻才开始记。
- 未激活时：可以锁仓、可以给子身份划额度（花的是用户自己的钱），但**不能接单、
  不能被撮合、信誉分不对外显示**。

「激活」是**派生**出来的（直接读 identity_verifications），不新增可变字段 —— 规则改了
不会留下一堆互相矛盾的历史状态；历史信誉行一条都不删，未激活只是「闸门 + 展示口径」。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import IdentityVerificationModel

ACTIVATION_SOURCE = "master_identity_verification"
REQUIRED_ACTION_ZH = "主身份本人实名认证：证件 + 刷脸"

ACTIVATED_NOTE_ZH = "已激活：信誉记录从现在开始记，可以接单、可以被撮合。"
NOT_ACTIVATED_NOTE_ZH = (
    "未激活：主身份本人完成「证件 + 刷脸」认证后自动激活，"
    "信誉记录才会开始记；未激活期间可以锁仓、可以给身份划额度，但不能接单、不能被撮合。"
)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def activation_view(row: IdentityVerificationModel | None, identity_id: str) -> dict[str, Any]:
    """把「主身份认证明细」收敛成操作台要的一个布尔 + 一句人话。"""
    status = ((getattr(row, "status", None) or "none").strip() or "none")
    activated = status == "verified"
    return {
        "identity_id": identity_id,
        "activated": activated,
        "status": status,
        "level": getattr(row, "level", None) or "basic",
        "verified_at": _iso(getattr(row, "verified_at", None)),
        "source": ACTIVATION_SOURCE,
        "required": REQUIRED_ACTION_ZH,
        "note_zh": ACTIVATED_NOTE_ZH if activated else NOT_ACTIVATED_NOTE_ZH,
    }


async def activation_of(db: AsyncSession, identity_id: str) -> dict[str, Any]:
    iid = (identity_id or "").strip()
    if not iid:
        return activation_view(None, "")
    row = await db.get(IdentityVerificationModel, iid)
    return activation_view(row, iid)


async def is_activated(db: AsyncSession, identity_id: str) -> bool:
    return bool((await activation_of(db, identity_id))["activated"])


async def inactive_identities(db: AsyncSession, identity_ids: "list[str] | set[str]") -> set[str]:
    """给定一批主身份号，一次查完，返回其中**未激活**的那些（撮合闸门用）。"""
    ids = {str(x).strip() for x in identity_ids if str(x or "").strip()}
    if not ids:
        return set()
    result = await db.execute(
        select(IdentityVerificationModel.identity_id, IdentityVerificationModel.status).where(
            IdentityVerificationModel.identity_id.in_(sorted(ids))
        )
    )
    verified = {row[0] for row in result.all() if (row[1] or "") == "verified"}
    return {i for i in ids if i not in verified}


def activation_error(identity_id: str, *, action: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=(
            f"identity {identity_id} is not activated: {action} requires master identity "
            f"verification (证件 + 刷脸). 主身份完成实名认证后自动激活。"
        ),
    )


async def assert_activated(db: AsyncSession, identity_id: str, *, action: str) -> dict[str, Any]:
    view = await activation_of(db, identity_id)
    if not view["activated"]:
        raise activation_error(identity_id, action=action)
    return view


__all__ = [
    "ACTIVATION_SOURCE",
    "REQUIRED_ACTION_ZH",
    "activation_error",
    "activation_of",
    "activation_view",
    "assert_activated",
    "inactive_identities",
    "is_activated",
]