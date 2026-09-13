"""Karma API — 收付中心台账（只读聚合）。

前端「收付中心」的全部数据来自这里：一个 GET 画出总览 + 收入明细 + 支出明细
+ 确认区 + 争议区；点开某一单再用 /entries/{kind}/{ref_id} 拿详情与流转历史。

只读、只认本人、子身份按档案 id 归属。归一逻辑在 services/payment_ledger.py。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import (
    AllowanceCommitModel,
    EscrowBindingModel,
    IdentityRoleProfile,
    SettlementModel,
    VoucherModel,
)
from db.session import get_db
from services import payment_ledger as ledger
from services.identity_actor import resolve_actor_identity_id
from services.path_param_safety import validate_public_url_segment

router = APIRouter()

ENTRY_KINDS = ("settlement", "binding", "voucher", "lock")


async def _resolve_scope(
    request: Request,
    db: AsyncSession,
    identity_id: str | None,
    profile_id: str | None,
) -> tuple[str, str | None]:
    """调用方只能看自己名下的账；子身份必须是自己的档案。"""
    actor = await resolve_actor_identity_id(db, request)
    target = (identity_id or "").strip() or (actor or "").strip()
    if not target:
        raise HTTPException(403, "连接钱包完成认证后才能查看收付中心")
    if actor and target != actor:
        raise HTTPException(403, "只能查看自己身份名下的收付记录")

    profile = (profile_id or "").strip() or None
    if profile:
        validate_public_url_segment("profile_id", profile)
        row = await db.get(IdentityRoleProfile, profile)
        if row is None or row.owner_identity_id != target:
            raise HTTPException(404, f"子身份 {profile} 不属于该身份")
    return target, profile


@router.get("/ledger")
async def get_payment_ledger(
    identity_id: str | None = Query(default=None, max_length=128),
    profile_id: str | None = Query(default=None, max_length=128),
    direction: str = Query(default="all", pattern="^(all|in|out)$"),
    kind: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=48),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """收付中心主接口。total 按 tab 过滤后计，summary 永远覆盖整个作用域。"""
    target, profile = await _resolve_scope(request, db, identity_id, profile_id)
    body = await ledger.build_ledger(db, identity_id=target, profile_id=profile)

    scoped = body["entries"]
    confirmation = [e for e in scoped if e["phase"] == ledger.PHASE_CONFIRM]
    disputes = [e for e in scoped if e["phase"] == ledger.PHASE_DISPUTE]

    rows = scoped
    if direction != "all":
        rows = [e for e in rows if e["direction"] == direction]
    if kind:
        rows = [e for e in rows if e["kind"] == kind]
    if status:
        rows = [e for e in rows if e["status"] == status]

    page = rows[offset : offset + limit]
    return {
        "identity_id": target,
        "profile_id": profile,
        "generated_at": datetime.utcnow().isoformat(),
        "summary": body["summary"],
        "entries": page,
        "confirmation": confirmation,
        "disputes": disputes,
        "totals": {"matched": len(rows), "returned": len(page), "scoped": len(scoped)},
    }


async def _load_entry(db: AsyncSession, kind: str, ref_id: str, identity_id: str) -> dict:
    if kind == "settlement":
        result = await db.execute(
            select(SettlementModel).where(SettlementModel.task_id == ref_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(404, f"结算单 {ref_id} 不存在")
        if identity_id not in (row.client_agent_id, row.worker_agent_id):
            raise HTTPException(403, "这一单不属于当前身份")
        return ledger.settlement_entry(row, identity_id)

    if kind == "binding":
        row = await db.get(EscrowBindingModel, ref_id)
        if row is None:
            raise HTTPException(404, f"链上结算单 {ref_id} 不存在")
        if identity_id not in (row.buyer_identity_id, row.seller_identity_id):
            raise HTTPException(403, "这一单不属于当前身份")
        return ledger.binding_entry(row, identity_id)

    if kind == "voucher":
        row = await db.get(VoucherModel, ref_id)
        if row is None:
            raise HTTPException(404, f"付款授权码 {ref_id} 不存在")
        if identity_id not in (row.buyer_identity_id, row.seller_identity_id):
            raise HTTPException(403, "这一单不属于当前身份")
        return ledger.voucher_entry(row, identity_id)

    if kind == "lock":
        # bill_id 是字符串主键，不能按数字查（Postgres 会直接拒绝 int 参数）。
        row = await db.get(AllowanceCommitModel, ref_id)
        if row is None:
            raise HTTPException(404, f"锁仓凭证 {ref_id} 不存在")
        if row.identity_id != identity_id:
            raise HTTPException(403, "这条锁仓不属于当前身份")
        return ledger.lock_entry(row, identity_id)

    raise HTTPException(404, f"未知的台账类型 {kind}")


@router.get("/entries/{kind}/{ref_id}")
async def get_payment_entry(
    kind: str,
    ref_id: str,
    identity_id: str | None = Query(default=None, max_length=128),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """单笔详情：条目本身 + 状态流转 / 事件历史。"""
    if kind not in ENTRY_KINDS:
        raise HTTPException(404, f"未知的台账类型 {kind}")
    validate_public_url_segment("ref_id", ref_id)
    target, _ = await _resolve_scope(request, db, identity_id, None)

    entry = await _load_entry(db, kind, ref_id, target)
    history: list[dict] = []
    if kind == "settlement":
        history = await ledger.settlement_history(db, ref_id)
    elif kind == "voucher":
        history = await ledger.voucher_history(db, ref_id)
    return {"identity_id": target, "entry": entry, "history": history}
