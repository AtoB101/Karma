"""Audited settlement status transitions (shared by HTTP routes and trade pipeline)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import SettlementState, SettlementTransitionAudit, TaskStatus
from core.settlement.engine import canonical_task_status, can_transition
from db.models.orm import SettlementModel, SettlementTransitionAuditModel
from db.stores.settlement_store import PostgresSettlementStore
from services.security_monitoring import SecurityMonitoringEventType, record_security_event

logger = structlog.get_logger(__name__)


PIPELINE_ROUTE_PATH = "/internal/trade_pipeline/v2"
PIPELINE_ACTOR_ID = "trade_pipeline_v2"


async def apply_settlement_transition(
    *,
    db: AsyncSession,
    store: PostgresSettlementStore,
    state: SettlementState,
    target_status: TaskStatus,
    reason: str,
    route_path: str = PIPELINE_ROUTE_PATH,
    actor_id: str | None = PIPELINE_ACTOR_ID,
) -> SettlementState:
    from_status = state.status
    if not can_transition(from_status, target_status):
        detail = f"invalid status transition: {from_status.value} -> {target_status.value}"
        await record_settlement_transition_audit(
            db=db,
            state=state,
            from_status=from_status,
            to_status=target_status,
            transition_allowed=False,
            guard_stage="pipeline",
            reason=detail,
            route_path=route_path,
            actor_id=actor_id,
        )
        raise HTTPException(409, detail)

    # 链上 I/O 会被放到下面的事务之外；那一步失败时要能把业务状态退回来，先取快照。
    prior = await snapshot_settlement_row(db, state.task_id)
    state.status = target_status
    state.updated_at = datetime.utcnow()
    try:
        await store.save(state)
    except ValueError as exc:
        detail = str(exc)
        await record_settlement_transition_audit(
            db=db,
            state=state,
            from_status=from_status,
            to_status=target_status,
            transition_allowed=False,
            guard_stage="store",
            reason=detail,
            route_path=route_path,
            actor_id=actor_id,
        )
        raise HTTPException(409, detail) from exc

    await record_settlement_transition_audit(
        db=db,
        state=state,
        from_status=from_status,
        to_status=target_status,
        transition_allowed=True,
        guard_stage="store",
        reason=reason,
        route_path=route_path,
        actor_id=actor_id,
    )
    # ── 链上 I/O 不许待在事务里（2026-10-01，同 api/routes/settlement.py 的根因）──
    # 这条路径是 agent 下单（intent fulfillment / trade pipeline）走的。以前它一路
    # 不 commit：链上那一段（bind 之前两侧各读一次授权额）实测 ~2s，而这一路在
    # accept_voucher_row 里对 buyer 的 capacity 行做过的 UPDATE 还攥着行锁 ——
    # 同一个 buyer 的并发下单就只能一个接一个排队（L1 实测第 10 单接单等 18.3s，
    # 每单 +2s）。先把这一步落库、把行锁全部放掉，再去动链。链上失败时退回原样。
    await db.commit()
    try:
        await sync_chain_escrow_for_transition(
            db=db, state=state, target_status=target_status
        )
    except Exception:  # noqa: BLE001 - 链上那一步不管怎么坏的，状态都得退回去
        await revert_chain_rejected_transition(
            db=db,
            prior=prior,
            state=state,
            from_status=from_status,
            target_status=target_status,
            reason=reason,
            route_path=route_path,
            actor_id=actor_id,
        )
        raise
    # 链上事实写回的是 ORM 行，不是手里这个 pydantic 快照。不重读的话，下一次
    # transition 的 ``store.save()`` 会拿旧快照（settlement_mode=offchain、
    # onchain_status/onchain_binding_id=None）把刚写回的链上字段整片覆盖掉 ——
    # agent 下单的单子会显示成「链上一片空白」，和链上的 binding 对不上。
    refreshed = await store.get(state.task_id)
    return refreshed or state


_SETTLEMENT_SNAPSHOT_COLUMNS = (
    "status",
    "released_amount",
    "refunded_amount",
    "released_at",
    "arbitration_notes",
    "dispute_reason",
)


async def snapshot_settlement_row(db: AsyncSession, task_id: str) -> dict[str, Any] | None:
    """记下结算行「本步改动前」的样子，供链上失败时还原（只读、不取行锁）。"""
    row = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().first()
    if row is None:
        return None
    return {name: getattr(row, name, None) for name in _SETTLEMENT_SNAPSHOT_COLUMNS}


async def revert_chain_rejected_transition(
    *,
    db: AsyncSession,
    prior: dict[str, Any] | None,
    state: SettlementState,
    from_status: TaskStatus,
    target_status: TaskStatus,
    reason: str,
    route_path: str,
    actor_id: str | None,
) -> None:
    """链上闸门没过：把已经落库的业务状态退回原样。

    与 ``api/routes/settlement.py`` 的同名逻辑一致：``apply_settlement_transition``
    现在先把这一步落库、放掉行锁，再去动链；链上失败时那一行已经提交了。
    不退回来的话，操作台会声称一笔链上根本不认的结算（钱没动，页面却写「已结算」）。
    """
    if prior is None:
        return
    try:
        await db.rollback()
        await db.execute(
            update(SettlementModel)
            .where(SettlementModel.task_id == state.task_id)
            .values(**prior)
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - 还原失败也不能把真正的链上错误吞掉
        logger.warning("settlement_transition_rollback_failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return
    if canonical_task_status(target_status) == TaskStatus.DISPUTED:
        # 开争议那条路在状态机之前就冻了额度，状态退回去，冻结也得退。
        from api.routes.settlement import _release_dispute_freeze_after_revert

        await _release_dispute_freeze_after_revert(
            db, buyer_identity_id=state.client_agent_id, escrow_amount=state.escrow_amount
        )
        await db.commit()
    try:
        await record_settlement_transition_audit(
            db=db,
            state=state,
            from_status=from_status,
            to_status=target_status,
            transition_allowed=False,
            guard_stage="chain",
            reason=f"链上闸门拒绝了这一步（{reason}）：业务状态已退回，交易可重试",
            route_path=route_path,
            actor_id=actor_id,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - 审计写不上不影响主流程
        logger.warning("settlement_chain_reject_audit_failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def sync_chain_escrow_for_transition(
    *,
    db: AsyncSession,
    state: SettlementState,
    target_status: TaskStatus,
    buyer_confirmed: bool = False,
) -> None:
    """账上状态机往前走了，链上托管必须跟着走。

    这条路径专门给 trade pipeline / intent fulfillment 用（agent 下单走的就是它）。
    以前只有 HTTP 结算路由接了链上（``api/routes/settlement._sync_escrow_settlement``），
    于是 agent 建的单：接单没 bind、结算没 submit —— 单子在账上「settled」，
    链上连一条 binding 都没有，钱一分没动，账本扣掉的那点额度还会被
    ``reconcile_capacity_mirror`` 按链上事实补回来。

    实现仍然只有一份：延迟导入 HTTP 路由里的那份（services 层不在导入期反向依赖 api）。
    """
    from api.routes.settlement import _sync_escrow_settlement

    await _sync_escrow_settlement(
        db=db,
        state=state,
        target_status=target_status,
        buyer_confirmed=buyer_confirmed,
    )


async def record_settlement_transition_audit(
    *,
    db: AsyncSession,
    state: SettlementState,
    from_status: TaskStatus | None,
    to_status: TaskStatus,
    transition_allowed: bool,
    guard_stage: str,
    reason: str | None,
    route_path: str | None,
    actor_id: str | None,
) -> SettlementTransitionAudit:
    row = SettlementTransitionAuditModel(
        settlement_id=state.settlement_id,
        task_id=state.task_id,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value,
        transition_allowed=transition_allowed,
        guard_stage=guard_stage,
        reason=reason,
        route_path=route_path,
        actor_id=actor_id,
        metadata_={"source": "settlement_transitions"},
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    record_security_event(
        SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
        metadata={
            "task_id": state.task_id,
            "settlement_id": state.settlement_id,
            "from_status": from_status.value if from_status else None,
            "to_status": to_status.value,
            "transition_allowed": transition_allowed,
            "guard_stage": guard_stage,
            "path": route_path or "unknown",
            "actor_id": actor_id or "anonymous",
            "route_group": "settlement",
        },
    )
    return SettlementTransitionAudit(
        audit_id=row.audit_id,
        settlement_id=row.settlement_id,
        task_id=row.task_id,
        from_status=TaskStatus(row.from_status) if row.from_status else None,
        to_status=TaskStatus(row.to_status),
        transition_allowed=row.transition_allowed,
        guard_stage=row.guard_stage,
        reason=row.reason,
        route_path=row.route_path,
        actor_id=row.actor_id,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
    )
