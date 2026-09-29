"""Audited settlement status transitions (shared by HTTP routes and trade pipeline)."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import SettlementState, SettlementTransitionAudit, TaskStatus
from core.settlement.engine import can_transition
from db.models.orm import SettlementTransitionAuditModel
from db.stores.settlement_store import PostgresSettlementStore
from services.security_monitoring import SecurityMonitoringEventType, record_security_event


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
    await sync_chain_escrow_for_transition(
        db=db, state=state, target_status=target_status
    )
    # 链上事实写回的是 ORM 行，不是手里这个 pydantic 快照。不重读的话，下一次
    # transition 的 ``store.save()`` 会拿旧快照（settlement_mode=offchain、
    # onchain_status/onchain_binding_id=None）把刚写回的链上字段整片覆盖掉 ——
    # agent 下单的单子会显示成「链上一片空白」，和链上的 binding 对不上。
    refreshed = await store.get(state.task_id)
    return refreshed or state


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
