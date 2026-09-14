"""Karma — 技能市场（数据 API 商业化入口）。

- ``GET  /v1/skills``                  公开目录（按分类 / 关键词筛）
- ``GET  /v1/skills/mine``             我上架的（本人）
- ``GET  /v1/skills/{slug}``           公开详情
- ``POST /v1/skills``                  上架 / 重新上架（需主体已认证 + 本人钱包签名）
- ``POST /v1/skills/{slug}/pause``     下架（本人）
- ``POST /v1/skills/{slug}/resume``    恢复（本人 + 重新签名）
- ``POST /v1/skills/{slug}/use``       记一次调用（调用方身份），到阈值自动出账
- ``GET  /v1/skills/{slug}/usage``     计费详情（本人或提供方）

调用侧的硬门槛：**调用方必须真的锁了仓**。没锁仓就调用等于让提供方白干，
所以在 ``use`` 这一步先看链上额度够不够这一次，不够直接拒。
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services import skill_registry, usage_billing
from services.chain import allowance_escrow as escrow
from services.identity_actor import resolve_actor_identity_id
from services.path_param_safety import validate_public_url_segment

logger = structlog.get_logger(__name__)

router = APIRouter()


class SkillUpsertBody(BaseModel):
    model_config = {"extra": "allow"}

    slug: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    category: str | None = Field(default=None, max_length=64)
    summary: str = Field(min_length=8, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    endpoint_url: str = Field(min_length=8, max_length=500)
    method: str | None = Field(default=None, max_length=8)
    unit: str | None = Field(default=None, max_length=32)
    unit_price_usdc: float = Field(ge=0.0)
    settlement_threshold_usdc: float = Field(ge=0.0)
    default_cap_usdc: float | None = None
    # 上架时必填；/prepare 只用来生成待签声明，所以这里允许为空并在上架处校验。
    publisher_signature: str | None = Field(default=None, max_length=200)


class UseBody(BaseModel):
    model_config = {"extra": "allow"}

    request_id: str = Field(min_length=1, max_length=80)
    units: int = Field(default=1, ge=1, le=usage_billing.MAX_UNITS_PER_CALL)


class ResumeBody(BaseModel):
    publisher_signature: str | None = Field(default=None, max_length=200)


def _translate(exc: Exception) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status", 400), detail=getattr(exc, "message", str(exc)))


async def _require_self(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required")
    if actor != identity_id:
        raise HTTPException(403, "only the identity owner can do that")
    return actor


async def _load_skill(db: AsyncSession, slug: str):
    validate_public_url_segment("slug", slug)
    row = await skill_registry.find_by_slug(db, slug)
    if row is None:
        raise HTTPException(404, f"技能 {slug} 不存在")
    return row


async def _actor_or_403(db: AsyncSession, request: Request) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required")
    return actor


async def _assert_can_pay(db: AsyncSession, *, skill, payer_identity_id: str) -> None:
    """调用方必须真的锁了仓 —— 否则提供方是在白干。"""
    needed = max(float(skill.unit_price_usdc or 0.0), 0.0)
    rows = await escrow.list_commits(db, payer_identity_id)
    live = [r for r in rows if r.state == escrow.IDLE]
    if not live:
        raise HTTPException(
            409,
            "调用方还没有锁仓额度。请先在操作台「资金」里锁仓 USDC，"
            "授权额就是你能花的上限（钱始终留在你自己的钱包里）",
        )
    if needed <= 0:
        return
    best = max(
        float(r.amount_usdc or 0.0) - float(r.spent_usdc or 0.0) - float(r.reserved_usdc or 0.0)
        for r in live
    )
    if best + 1e-9 < needed:
        raise HTTPException(
            409,
            f"锁仓可用额度不足：这一次需要 {needed} USDC，目前最大可用 {round(best, 6)} USDC",
        )


@router.get("")
async def list_skills(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rows = await skill_registry.list_published(db, category=category, query=q, limit=limit, offset=offset)
    return {
        "count": len(rows),
        "category": category,
        "query": q,
        "skills": [skill_registry.skill_view(r) for r in rows],
    }


@router.get("/mine")
async def my_skills(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    actor = await _actor_or_403(db, request)
    rows = await skill_registry.list_by_owner(db, actor)
    entity = await skill_registry.get_entity(db, actor)
    return {
        "identity_id": actor,
        "entity_status": str(entity.status) if entity is not None else "none",
        "can_publish": bool(entity is not None and str(entity.status) == "verified"),
        "count": len(rows),
        "skills": [skill_registry.skill_view(r, owner=True) for r in rows],
    }


@router.get("/{slug}")
async def get_skill(slug: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await _load_skill(db, slug)
    if str(row.status) not in ("published", "paused"):
        raise HTTPException(404, f"技能 {slug} 不存在")
    return skill_registry.skill_view(row)


@router.post("/prepare")
async def prepare_skill(
    body: SkillUpsertBody, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """返回「待签声明」。客户端只签名，不自己拼串 —— 前后端规范化差一个字节就白签。"""
    actor = await _actor_or_403(db, request)
    try:
        return await skill_registry.prepare_publish(db, identity_id=actor, payload=body.model_dump())
    except skill_registry.SkillError as exc:
        raise _translate(exc) from exc

@router.post("")
async def publish_skill(
    body: SkillUpsertBody, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    actor = await _actor_or_403(db, request)
    if not (body.publisher_signature or "").strip():
        raise HTTPException(422, "上架需要钱包签名：先生成待签声明，再让钱包签它")
    try:
        row = await skill_registry.publish(
            db,
            identity_id=actor,
            payload=body.model_dump(),
            signature=str(body.publisher_signature),
        )
    except skill_registry.SkillError as exc:
        raise _translate(exc) from exc
    await db.commit()
    await db.refresh(row)
    return skill_registry.skill_view(row, owner=True)


@router.post("/{slug}/pause")
async def pause_skill(
    slug: str, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    actor = await _actor_or_403(db, request)
    row = await _load_skill(db, slug)
    try:
        row = await skill_registry.pause(db, identity_id=actor, slug=row.slug)
    except skill_registry.SkillError as exc:
        raise _translate(exc) from exc
    await db.commit()
    await db.refresh(row)
    return skill_registry.skill_view(row, owner=True)


@router.post("/{slug}/resume")
async def resume_skill(
    slug: str, body: ResumeBody, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    actor = await _actor_or_403(db, request)
    row = await _load_skill(db, slug)
    try:
        row = await skill_registry.resume(
            db, identity_id=actor, slug=row.slug, signature=body.publisher_signature
        )
    except skill_registry.SkillError as exc:
        raise _translate(exc) from exc
    await db.commit()
    await db.refresh(row)
    return skill_registry.skill_view(row, owner=True)


@router.post("/{slug}/use")
async def use_skill(
    slug: str, body: UseBody, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """记一次调用 + 到阈值就出账。幂等键是 request_id，重放不会重复计费。"""
    actor = await _actor_or_403(db, request)
    row = await _load_skill(db, slug)
    if str(row.status) != "published":
        raise HTTPException(409, f"技能 {slug} 当前状态是 {row.status}，不接受调用")

    await _assert_can_pay(db, skill=row, payer_identity_id=actor)
    try:
        result = await usage_billing.record_usage(
            db,
            skill=row,
            payer_identity_id=actor,
            request_id=body.request_id,
            units=body.units,
        )
    except usage_billing.UsageBillingError as exc:
        raise _translate(exc) from exc

    settlement: dict[str, Any] | None = None
    if not result["duplicate"]:
        try:
            settlement = await usage_billing.settle_meter(
                db, skill=row, payer_identity_id=actor
            )
        except Exception as exc:  # noqa: BLE001 - 出账失败不能把已经记好的账回滚
            logger.warning("usage_settle_failed", slug=row.slug, payer=actor, error=str(exc))
    try:
        await usage_billing.reconcile_settlements(db)
    except Exception as exc:  # noqa: BLE001 - 对账是尽力而为
        logger.warning("usage_reconcile_failed", error=str(exc))

    await db.commit()
    return {
        "skill": skill_registry.skill_view(row),
        "charge": result["charge"],
        "meter": result["meter"],
        "duplicate": result["duplicate"],
        "amount_usdc": result["amount_usdc"],
        "settlement": settlement,
    }


@router.get("/{slug}/usage")
async def skill_usage(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    payer_identity_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """本人看自己的;提供方看某个付款方的;提供方不传 payer 就看汇总。"""
    actor = await _actor_or_403(db, request)
    row = await _load_skill(db, slug)
    owner = str(row.owner_identity_id)

    await usage_billing.reconcile_settlements(db)

    if payer_identity_id:
        if actor not in (owner, payer_identity_id):
            raise HTTPException(403, "只能看自己的计费明细")
        target = payer_identity_id
        state = await usage_billing.billing_state(
            db, skill_id=row.skill_id, payer_identity_id=target, limit=limit
        )
        await db.commit()
        return {"skill": skill_registry.skill_view(row), **state}

    if actor != owner:
        state = await usage_billing.billing_state(
            db, skill_id=row.skill_id, payer_identity_id=actor, limit=limit
        )
        await db.commit()
        return {"skill": skill_registry.skill_view(row), **state}

    # 提供方：把每个付款方的计费器汇总起来（这是它的收入侧）
    from sqlalchemy import select as _select

    from db.models.orm import UsageMeterModel

    meters = (
        await db.execute(
            _select(UsageMeterModel)
            .where(UsageMeterModel.skill_id == row.skill_id)
            .order_by(UsageMeterModel.updated_at.desc())
            .limit(max(1, min(int(limit), usage_billing.MAX_HISTORY)))
        )
    ).scalars().all()
    await db.commit()
    return {
        "skill": skill_registry.skill_view(row),
        "counting_for": "provider",
        "meters": [usage_billing.meter_view(m) for m in meters],
    }