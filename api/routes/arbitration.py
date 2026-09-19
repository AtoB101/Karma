"""Karma API — P2 arbitration pool and case skeleton."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import (
    ArbitrationArbitratorActivitySummary,
    ArbitrationAssignment,
    ArbitrationCase,
    ArbitrationCaseEvent,
    ArbitrationCaseOverdueItem,
    ArbitrationCaseOpsReport,
    ArbitrationOpsAlert,
    ArbitrationOpsAlertSeverity,
    ArbitrationOpsAlertType,
    ArbitrationCaseStatus,
    ArbitrationEventType,
    ArbitrationMaterialPackage,
    ArbitrationOverdueStage,
    ArbitrationPoolMember,
    ArbitrationPoolMemberStatus,
    ArbitrationVoteDecision,
    SettlementState,
    TaskStatus,
)
from core.settlement.engine import can_transition
from db.models.orm import (
    ArbitrationAssignmentModel,
    ArbitrationCaseModel,
    ArbitrationCaseEventModel,
    ArbitrationMaterialPackageModel,
    ArbitrationPoolMemberModel,
    ArbitrationVoteModel,
)
from db.session import get_db
from db.stores.settlement_store import PostgresSettlementStore
from services import arbitration_rules as arb_rules
from services.actor_guards import require_admin_actor, require_arbitration_operator
from services.capacity_resolution import apply_capacity_resolution
from services.identity_actor import resolve_actor_identity_id
from services.security_monitoring import (
    SecurityMonitoringEventType,
    record_security_event,
)
from services.settlement_voucher import mark_voucher_used_if_linked

router = APIRouter()
DEFAULT_OPEN_CASE_ALERT_THRESHOLD = 5
DEFAULT_VOTING_CASE_ALERT_THRESHOLD = 5
DEFAULT_DECIDED_CASE_ALERT_THRESHOLD = 3
DEFAULT_PARTIAL_RATIO_ALERT_THRESHOLD = 0.5
DEFAULT_OPEN_OVERDUE_HOURS = 24
DEFAULT_VOTING_OVERDUE_HOURS = 24
DEFAULT_DECIDED_OVERDUE_HOURS = 12


class JoinArbitrationPoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    arbitrator_identity_id: str
    stake_amount: float = Field(ge=0.0, default=0.0)


class CreateArbitrationCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    task_id: str
    opened_by: str
    reason: str | None = None
    required_arbitrators: int = Field(default=3, ge=1, le=21)


class AssignArbitratorsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    count: int = Field(default=3, ge=1, le=21)


class SubmitArbitrationMaterialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    submitted_by: str
    bundle_id: str | None = None
    progress_receipt_ids: list[str] = Field(default_factory=list)
    evidence_hashes: list[str] = Field(default_factory=list)
    storage_uri: str | None = None
    format_version: str = "arbitration-material-v1"


class CastArbitrationVoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    arbitrator_identity_id: str
    decision: ArbitrationVoteDecision
    partial_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    rationale: str | None = None


@router.post("/pool/join", response_model=ArbitrationPoolMember)
async def join_arbitration_pool(
    body: JoinArbitrationPoolRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """入池。

    收紧后的三条硬规则（2026-09-17 复核前这里什么也不校验）：
    1. 只能给自己入池 —— 不能把别人塞进仲裁池；
    2. 入池资格走 ``ARBITRATOR_ACTOR_IDS``（除非显式开放申请）；
    3. 质押必须 > 0，且必须由**已锁仓的真实 USDC** 背书。
    """
    arb_rules.require_pool_join_allowed(request)
    await arb_rules.require_identity_binding(
        db, request, body.arbitrator_identity_id, what="arbitration pool join"
    )
    await arb_rules.assert_stake_acceptable(
        db, identity_id=body.arbitrator_identity_id, stake_amount=body.stake_amount
    )

    row = await db.get(ArbitrationPoolMemberModel, body.arbitrator_identity_id)
    if not row:
        row = ArbitrationPoolMemberModel(
            arbitrator_identity_id=body.arbitrator_identity_id,
            stake_amount=body.stake_amount,
            status=ArbitrationPoolMemberStatus.ACTIVE.value,
            joined_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    else:
        row.stake_amount = body.stake_amount
        row.status = ArbitrationPoolMemberStatus.ACTIVE.value
        row.updated_at = datetime.utcnow()
    await db.flush()
    return _pool_to_schema(row)


@router.get("/pool", response_model=list[ArbitrationPoolMember])
async def list_arbitration_pool(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ArbitrationPoolMemberModel).order_by(
            ArbitrationPoolMemberModel.status.asc(),
            ArbitrationPoolMemberModel.joined_at.asc(),
        )
    )
    rows = result.scalars().all()
    return [_pool_to_schema(row) for row in rows]


async def _case_parties(db: AsyncSession, case_row: ArbitrationCaseModel) -> set[str]:
    """案件当事人集合：立案人 + 结算买卖双方（用于读权限与回避）。"""
    parties: set[str] = set()
    if case_row.opened_by:
        parties.add(case_row.opened_by)
    state = await PostgresSettlementStore(db).get(case_row.task_id)
    if state is not None:
        if state.client_agent_id:
            parties.add(state.client_agent_id)
        if state.worker_agent_id:
            parties.add(state.worker_agent_id)
    return parties


async def _require_case_reader(db: AsyncSession, case_row: ArbitrationCaseModel, request: Request) -> None:
    """案件详情/材料/事件只对当事人与运维岗开放（争议材料不该给第三方看）。"""
    if arb_rules.caller_is_operator(request):
        return
    parties = await _case_parties(db, case_row)
    actor_identity = await resolve_actor_identity_id(db, request)
    if actor_identity and actor_identity in parties:
        return
    raise HTTPException(
        403, "only the dispute parties or arbitration operators may read this case"
    )


@router.post("/cases", response_model=ArbitrationCase, status_code=201)
async def create_arbitration_case(
    body: CreateArbitrationCaseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # 校验顺序：输入合法性 → 资源存在 → 授权 → 状态。授权先于状态，
    # 免得「案件是否存在 / 结算到哪一步了」被无关身份探测出来。
    # 人数不能由调用方自填：只能落在平台策略窗口内。
    arb_rules.assert_panel_size_allowed(body.required_arbitrators)

    settlement_store = PostgresSettlementStore(db)
    state = await settlement_store.get(body.task_id)
    if not state:
        raise HTTPException(404, f"settlement {body.task_id} not found")

    # 立案人必须是本案当事人（运维岗可代为立案）。
    parties = {state.client_agent_id}
    if state.worker_agent_id:
        parties.add(state.worker_agent_id)
    if body.opened_by not in parties and not arb_rules.caller_is_operator(request):
        raise HTTPException(403, "only a party to the dispute may open an arbitration case")
    await arb_rules.require_identity_binding(db, request, body.opened_by, what="case creation")

    existing = await db.execute(
        select(ArbitrationCaseModel).where(ArbitrationCaseModel.task_id == body.task_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"arbitration case already exists for task {body.task_id}")

    if state.status not in {TaskStatus.DISPUTED, TaskStatus.ARBITRATED}:
        raise HTTPException(409, "settlement must be disputed before arbitration case creation")

    if state.status == TaskStatus.DISPUTED:
        if not can_transition(state.status, TaskStatus.ARBITRATED):
            raise HTTPException(409, "invalid settlement transition to arbitration")
        from api.routes.settlement import _record_transition_audit

        await _record_transition_audit(
            db=db,
            state=state,
            from_status=TaskStatus.DISPUTED,
            to_status=TaskStatus.ARBITRATED,
            transition_allowed=True,
            guard_stage="arbitration_case_create",
            reason=f"arbitration case opened by {body.opened_by}",
            route_path="/v1/arbitration/cases",
            actor_id=await resolve_actor_identity_id(db, request) or body.opened_by,
        )
        state.status = TaskStatus.ARBITRATED
        state.updated_at = datetime.utcnow()
        await settlement_store.save(state)

    row = ArbitrationCaseModel(
        task_id=body.task_id,
        settlement_id=state.settlement_id,
        opened_by=body.opened_by,
        reason=body.reason,
        status=ArbitrationCaseStatus.OPEN.value,
        required_arbitrators=body.required_arbitrators,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    await _append_case_event(
        db=db,
        case_id=row.case_id,
        event_type=ArbitrationEventType.CASE_CREATED,
        detail="arbitration case created",
        metadata={
            "task_id": row.task_id,
            "opened_by": row.opened_by,
            "required_arbitrators": row.required_arbitrators,
        },
    )
    return _case_to_schema(row)


@router.get("/cases/ops/report", response_model=ArbitrationCaseOpsReport)
async def get_arbitration_case_ops_report(
    _: str = Depends(require_admin_actor),
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    recent_events_limit: int = Query(default=50, ge=1, le=1000),
    arbitrator_limit: int = Query(default=20, ge=1, le=200),
    overdue_limit: int = Query(default=20, ge=1, le=200),
    open_overdue_hours: int = Query(default=24, ge=1, le=24 * 365),
    voting_overdue_hours: int = Query(default=24, ge=1, le=24 * 365),
    decided_overdue_hours: int = Query(default=12, ge=1, le=24 * 365),
    db: AsyncSession = Depends(get_db),
):
    return await _build_arbitration_case_ops_report(
        db=db,
        window_hours=window_hours,
        recent_events_limit=recent_events_limit,
        arbitrator_limit=arbitrator_limit,
        overdue_limit=overdue_limit,
        open_overdue_hours=open_overdue_hours,
        voting_overdue_hours=voting_overdue_hours,
        decided_overdue_hours=decided_overdue_hours,
    )


@router.get("/cases/ops/alerts", response_model=list[ArbitrationOpsAlert])
async def get_arbitration_case_ops_alerts(
    _: str = Depends(require_admin_actor),
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    open_case_threshold: int = Query(default=5, ge=1, le=100000),
    voting_case_threshold: int = Query(default=5, ge=1, le=100000),
    decided_case_threshold: int = Query(default=3, ge=1, le=100000),
    partial_ratio_threshold: float = Query(default=0.5, ge=0.01, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    report = await _build_arbitration_case_ops_report(
        db=db,
        window_hours=window_hours,
        recent_events_limit=50,
        open_case_threshold=open_case_threshold,
        voting_case_threshold=voting_case_threshold,
        decided_case_threshold=decided_case_threshold,
        partial_ratio_threshold=partial_ratio_threshold,
    )
    return report.alerts


@router.get("/cases/ops/arbitrators", response_model=list[ArbitrationArbitratorActivitySummary])
async def get_arbitration_case_ops_arbitrators(
    _: str = Depends(require_admin_actor),
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await _list_arbitrator_activity(
        db=db,
        window_hours=window_hours,
        limit=limit,
    )


@router.get("/cases/ops/overdue", response_model=list[ArbitrationCaseOverdueItem])
async def get_arbitration_case_ops_overdue(
    _: str = Depends(require_admin_actor),
    limit: int = Query(default=20, ge=1, le=200),
    open_overdue_hours: int = Query(default=24, ge=1, le=24 * 365),
    voting_overdue_hours: int = Query(default=24, ge=1, le=24 * 365),
    decided_overdue_hours: int = Query(default=12, ge=1, le=24 * 365),
    db: AsyncSession = Depends(get_db),
):
    return await _list_overdue_cases(
        db=db,
        limit=limit,
        open_overdue_hours=open_overdue_hours,
        voting_overdue_hours=voting_overdue_hours,
        decided_overdue_hours=decided_overdue_hours,
    )


@router.get("/cases/{case_id}", response_model=ArbitrationCase)
async def get_arbitration_case(case_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    row = await db.get(ArbitrationCaseModel, case_id)
    if not row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    await _require_case_reader(db, row, request)
    return _case_to_schema(row)


@router.post("/cases/{case_id}/assign-auto", response_model=list[ArbitrationAssignment])
async def assign_arbitrators(
    case_id: str,
    body: AssignArbitratorsRequest,
    request: Request,
    _: str = Depends(require_arbitration_operator),
    db: AsyncSession = Depends(get_db),
):
    """自动派庭。

    收紧点（2026-09-17 复核前按入池先后取人）：
    * 调用者必须是仲裁员/管理员白名单里的运维岗；
    * 候选人必须 ACTIVE **且质押 > 0**；
    * **回避当事人**：买卖双方、立案人，以及他们名下的子身份与角色档案；
    * **抵押必须覆盖案值**：质押要**严格大于**这笔争议的托管金额（2026-09-17 起）——
      抵押 10 的人不能去裁 100 的争议，否则一次误判就把抵押打穿；
    * 派庭人数不得超过案件声明的 ``required_arbitrators``。
    """
    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    if case_row.status in {ArbitrationCaseStatus.DECIDED.value, ArbitrationCaseStatus.EXECUTED.value}:
        raise HTTPException(409, f"arbitration case already finalized: {case_row.status}")

    existing_result = await db.execute(
        select(ArbitrationAssignmentModel.arbitrator_identity_id).where(
            ArbitrationAssignmentModel.case_id == case_id
        )
    )
    existing_ids = set(existing_result.scalars().all())

    need = int(case_row.required_arbitrators or 0) - len(existing_ids)
    if need <= 0:
        raise HTTPException(409, "arbitration panel is already full for this case")
    want = min(int(body.count or 0), need)

    parties = await _case_parties(db, case_row)
    conflicted = await arb_rules.conflicted_identity_ids(db, parties=parties)

    candidates_result = await db.execute(
        select(ArbitrationPoolMemberModel)
        .where(ArbitrationPoolMemberModel.status == ArbitrationPoolMemberStatus.ACTIVE.value)
        .order_by(ArbitrationPoolMemberModel.joined_at.asc())
    )
    # 案值 = 这笔争议里真正可能被划走的托管金额；抵押盖不住它的人不能入庭。
    case_value = await arb_rules.case_value_of(db, case_row)
    candidates = arb_rules.filter_qualified_members(
        list(candidates_result.scalars().all()),
        conflicted=conflicted,
        exclude_ids=existing_ids,
        case_value=case_value,
    )
    selected = candidates[:want]
    if not selected:
        raise HTTPException(
            409,
            "no qualified arbitrators available for assignment: need ACTIVE members whose "
            f"stake covers the case value {case_value:.6f} "
            f"(stake > {case_value * arb_rules.stake_coverage_multiple():.6f})",
        )

    assignment_rows: list[ArbitrationAssignmentModel] = []
    for member in selected:
        assignment = ArbitrationAssignmentModel(
            case_id=case_id,
            arbitrator_identity_id=member.arbitrator_identity_id,
            assigned_at=datetime.utcnow(),
            status="assigned",
        )
        db.add(assignment)
        assignment_rows.append(assignment)

    case_row.status = ArbitrationCaseStatus.VOTING.value
    case_row.updated_at = datetime.utcnow()
    await db.flush()
    await _append_case_event(
        db=db,
        case_id=case_id,
        event_type=ArbitrationEventType.ARBITRATORS_ASSIGNED,
        detail="arbitrators auto-assigned to case",
        metadata={
            "assigned_count": len(assignment_rows),
            "requested_count": want,
            "required_arbitrators": case_row.required_arbitrators,
            "qualified_candidates": len(candidates),
            "case_value": case_value,
            "stake_coverage_multiple": arb_rules.stake_coverage_multiple(),
            "recused_identity_count": len(conflicted),
            "arbitrator_identity_ids": [row.arbitrator_identity_id for row in assignment_rows],
        },
    )
    return [_assignment_to_schema(row) for row in assignment_rows]


@router.get("/cases/{case_id}/assignments", response_model=list[ArbitrationAssignment])
async def list_case_assignments(case_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    await _require_case_reader(db, case_row, request)
    result = await db.execute(
        select(ArbitrationAssignmentModel)
        .where(ArbitrationAssignmentModel.case_id == case_id)
        .order_by(ArbitrationAssignmentModel.assigned_at.asc())
    )
    rows = result.scalars().all()
    return [_assignment_to_schema(row) for row in rows]


@router.get("/cases/{case_id}/events", response_model=list[ArbitrationCaseEvent])
async def list_case_events(
    case_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    await _require_case_reader(db, case_row, request)
    result = await db.execute(
        select(ArbitrationCaseEventModel)
        .where(ArbitrationCaseEventModel.case_id == case_id)
        .order_by(ArbitrationCaseEventModel.created_at.asc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [_case_event_to_schema(row) for row in rows]


@router.post("/cases/{case_id}/materials", response_model=ArbitrationMaterialPackage, status_code=201)
async def submit_material(
    case_id: str,
    body: SubmitArbitrationMaterialRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    if case_row.status in {ArbitrationCaseStatus.EXECUTED.value, ArbitrationCaseStatus.CANCELLED.value}:
        raise HTTPException(409, f"cannot submit material for case status {case_row.status}")

    # 证据只能由当事人自己提交（运维岗可代为提交）。
    parties = await _case_parties(db, case_row)
    if body.submitted_by not in parties and not arb_rules.caller_is_operator(request):
        raise HTTPException(403, "only a party to the dispute may submit arbitration material")
    await arb_rules.require_identity_binding(db, request, body.submitted_by, what="material submission")

    normalized_hashes = sorted({h.strip().lower() for h in body.evidence_hashes if h and h.strip()})
    progress_ids = sorted({item.strip() for item in body.progress_receipt_ids if item and item.strip()})
    if not body.bundle_id and not normalized_hashes and not progress_ids:
        raise HTTPException(400, "at least one of bundle_id, progress_receipt_ids, evidence_hashes must be provided")

    package_hash = _sha256(
        {
            "case_id": case_id,
            "task_id": case_row.task_id,
            "bundle_id": body.bundle_id,
            "progress_receipt_ids": progress_ids,
            "evidence_hashes": normalized_hashes,
            "format_version": body.format_version,
        }
    )
    existing = await db.execute(
        select(ArbitrationMaterialPackageModel).where(
            ArbitrationMaterialPackageModel.case_id == case_id,
            ArbitrationMaterialPackageModel.package_hash == package_hash,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "duplicate arbitration material package hash")

    row = ArbitrationMaterialPackageModel(
        case_id=case_id,
        task_id=case_row.task_id,
        submitted_by=body.submitted_by,
        bundle_id=body.bundle_id,
        progress_receipt_ids=progress_ids,
        evidence_hashes=normalized_hashes,
        package_hash=package_hash,
        storage_uri=body.storage_uri,
        format_version=body.format_version,
        submitted_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    await _append_case_event(
        db=db,
        case_id=case_id,
        event_type=ArbitrationEventType.MATERIAL_SUBMITTED,
        detail="arbitration material submitted",
        metadata={
            "material_id": row.material_id,
            "submitted_by": row.submitted_by,
            "package_hash": row.package_hash,
        },
    )
    return _material_to_schema(row)


@router.get("/cases/{case_id}/materials", response_model=list[ArbitrationMaterialPackage])
async def list_materials(case_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    await _require_case_reader(db, case_row, request)
    result = await db.execute(
        select(ArbitrationMaterialPackageModel)
        .where(ArbitrationMaterialPackageModel.case_id == case_id)
        .order_by(ArbitrationMaterialPackageModel.submitted_at.asc())
    )
    rows = result.scalars().all()
    return [_material_to_schema(row) for row in rows]


@router.post("/cases/{case_id}/vote", response_model=ArbitrationCase)
async def cast_vote(
    case_id: str,
    body: CastArbitrationVoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """投票。

    此前只校验「这个 id 被指派过」，不校验「你就是这个 id」——
    任何人都能冒用被指派的仲裁员身份代投。现在投票必须由**本人**（或有白名单的
    运维岗代为操作，并留痕在事件里）发起。

    另外：投票才是真正的裁决动作，所以**投之前再校验一次抵押**——派庭之后被减仓
    或被罚没的仲裁员，不能靠一张旧的指派记录继续投票。
    """
    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    if case_row.status in {ArbitrationCaseStatus.DECIDED.value, ArbitrationCaseStatus.EXECUTED.value}:
        raise HTTPException(409, f"arbitration case already finalized: {case_row.status}")

    actor_identity = await resolve_actor_identity_id(db, request)
    await arb_rules.require_identity_binding(
        db, request, body.arbitrator_identity_id, what="arbitration vote"
    )

    assignment = await db.execute(
        select(ArbitrationAssignmentModel).where(
            ArbitrationAssignmentModel.case_id == case_id,
            ArbitrationAssignmentModel.arbitrator_identity_id == body.arbitrator_identity_id,
        )
    )
    if not assignment.scalar_one_or_none():
        raise HTTPException(403, "arbitrator is not assigned to this case")

    # 抵押必须仍然覆盖案值：派庭后减仓 / 罚没的仲裁员不许继续投。
    await arb_rules.assert_arbitrator_covers_case(
        db, case_row=case_row, identity_id=body.arbitrator_identity_id, what="arbitration vote"
    )

    if body.decision == ArbitrationVoteDecision.PARTIAL and body.partial_percent is None:
        raise HTTPException(400, "partial_percent is required when decision is partial")
    if body.decision != ArbitrationVoteDecision.PARTIAL and body.partial_percent is not None:
        raise HTTPException(400, "partial_percent is only allowed for partial decision")

    row = ArbitrationVoteModel(
        case_id=case_id,
        arbitrator_identity_id=body.arbitrator_identity_id,
        decision=body.decision.value,
        partial_percent=body.partial_percent,
        rationale=body.rationale,
        voted_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        await db.flush()
    except Exception as exc:  # pragma: no cover - SQL uniqueness safeguard
        raise HTTPException(409, "duplicate vote for arbitrator in this case") from exc
    # P1-8：投票必须能回溯到「真实的调用者」。本人投票时 voted_by == 被指派者；
    # 运维岗代投（白名单）是唯一允许的不一致，这种情况额外落一条安全告警事件，
    # 事后审计一眼能看出「这一票不是本人投的」。
    voted_by = actor_identity or body.arbitrator_identity_id
    actor_mismatch = actor_identity is not None and actor_identity != body.arbitrator_identity_id
    await _append_case_event(
        db=db,
        case_id=case_id,
        event_type=ArbitrationEventType.VOTE_CAST,
        detail="arbitration vote cast",
        metadata={
            "vote_id": row.vote_id,
            "claimed_arbitrator_id": row.arbitrator_identity_id,
            "actual_actor_id": voted_by,
            "voted_by": voted_by,
            "actor_mismatch": actor_mismatch,
            "decision": row.decision,
            "partial_percent": row.partial_percent,
        },
    )
    if actor_mismatch:
        record_security_event(
            SecurityMonitoringEventType.ARBITRATOR_ACTION,
            metadata={
                "what": "arbitration_vote_on_behalf",
                "case_id": case_id,
                "claimed_arbitrator_id": row.arbitrator_identity_id,
                "actual_actor_id": voted_by,
                "decision": row.decision,
            },
        )

    votes_result = await db.execute(
        select(ArbitrationVoteModel).where(ArbitrationVoteModel.case_id == case_id)
    )
    votes = votes_result.scalars().all()
    if len(votes) >= case_row.required_arbitrators:
        buyer_votes = [v for v in votes if v.decision == ArbitrationVoteDecision.BUYER_WINS.value]
        seller_votes = [v for v in votes if v.decision == ArbitrationVoteDecision.SELLER_WINS.value]
        partial_votes = [v for v in votes if v.decision == ArbitrationVoteDecision.PARTIAL.value]
        if len(buyer_votes) > len(seller_votes):
            outcome = ArbitrationVoteDecision.BUYER_WINS
            partial_percent = None
        elif len(seller_votes) > len(buyer_votes):
            outcome = ArbitrationVoteDecision.SELLER_WINS
            partial_percent = None
        else:
            outcome = ArbitrationVoteDecision.PARTIAL
            partial_values = [v.partial_percent for v in partial_votes if v.partial_percent is not None]
            partial_percent = round(sum(partial_values) / len(partial_values), 2) if partial_values else 50.0
        case_row.status = ArbitrationCaseStatus.DECIDED.value
        case_row.decided_outcome = outcome.value
        case_row.final_partial_percent = partial_percent
        case_row.updated_at = datetime.utcnow()
        await _append_case_event(
            db=db,
            case_id=case_id,
            event_type=ArbitrationEventType.CASE_DECIDED,
            detail="arbitration case reached decision",
            metadata={
                "decided_outcome": outcome.value,
                "final_partial_percent": partial_percent,
                "vote_count": len(votes),
                "required_arbitrators": case_row.required_arbitrators,
            },
        )
    elif case_row.status == ArbitrationCaseStatus.OPEN.value:
        case_row.status = ArbitrationCaseStatus.VOTING.value
        case_row.updated_at = datetime.utcnow()
    await db.flush()
    return _case_to_schema(case_row)


@router.post("/cases/{case_id}/execute", response_model=SettlementState)
async def execute_arbitration_case(
    case_id: str,
    request: Request,
    actor: str = Depends(require_arbitration_operator),
    db: AsyncSession = Depends(get_db),
):
    """把裁决写回结算。

    此前这条路径**不写** ``settlement_transition_audits``，于是同一笔结算
    经仲裁改判后在审计链上是断的。现在每次流转都补一条审计。
    """
    from api.routes.settlement import _record_transition_audit, _sync_escrow_settlement

    case_row = await db.get(ArbitrationCaseModel, case_id)
    if not case_row:
        raise HTTPException(404, f"arbitration case {case_id} not found")
    if case_row.status != ArbitrationCaseStatus.DECIDED.value:
        raise HTTPException(409, f"arbitration case status must be decided, got {case_row.status}")
    if not case_row.decided_outcome:
        raise HTTPException(409, "arbitration decision is missing")

    store = PostgresSettlementStore(db)
    state = await store.get(case_row.task_id)
    if not state:
        raise HTTPException(404, f"settlement {case_row.task_id} not found")

    if state.status == TaskStatus.DISPUTED:
        if not can_transition(state.status, TaskStatus.ARBITRATED):
            raise HTTPException(409, "cannot transition settlement to arbitration")
        await _record_transition_audit(
            db=db,
            state=state,
            from_status=TaskStatus.DISPUTED,
            to_status=TaskStatus.ARBITRATED,
            transition_allowed=True,
            guard_stage="arbitration_execute",
            reason=f"arbitration case {case_id} accepted",
            route_path=f"/v1/arbitration/cases/{case_id}/execute",
            actor_id=actor,
        )
        state.status = TaskStatus.ARBITRATED

    if case_row.decided_outcome == ArbitrationVoteDecision.BUYER_WINS.value:
        target = TaskStatus.REFUNDED
        settled_amount = 0.0
        refunded_amount = round(state.escrow_amount, 2)
        notes = "decentralized pool decision: buyer_wins"
    elif case_row.decided_outcome == ArbitrationVoteDecision.SELLER_WINS.value:
        target = TaskStatus.SETTLED
        settled_amount = round(state.escrow_amount, 2)
        refunded_amount = 0.0
        notes = "decentralized pool decision: seller_wins"
    else:
        target = TaskStatus.SETTLED
        partial_percent = case_row.final_partial_percent if case_row.final_partial_percent is not None else 50.0
        settled_amount = round(state.escrow_amount * partial_percent / 100.0, 2)
        refunded_amount = round(state.escrow_amount - settled_amount, 2)
        notes = f"decentralized pool decision: partial {partial_percent:.2f}%"

    if not can_transition(state.status, target):
        raise HTTPException(409, f"invalid settlement transition: {state.status.value} -> {target.value}")

    await _record_transition_audit(
        db=db,
        state=state,
        from_status=TaskStatus.ARBITRATED,
        to_status=target,
        transition_allowed=True,
        guard_stage="arbitration_execute",
        reason=notes,
        route_path=f"/v1/arbitration/cases/{case_id}/execute",
        actor_id=actor,
    )
    state.status = target
    state.released_amount = settled_amount
    state.refunded_amount = refunded_amount
    state.arbitration_notes = notes
    state.updated_at = datetime.utcnow()
    state.released_at = datetime.utcnow() if settled_amount > 0 else None
    await store.save(state)
    # 裁决必须落到链上（2026-09-20 测试网实测发现）：这条路径此前只改数据库、从不碰链，
    # 于是 DB 说「已退款 / 已结算」而链上的 binding 还挂着 active —— 钱一直锁在托管里，
    # 台账和链上对不上。走 /dispute → /auto-arbitrate 那条路是有这一步的，仲裁庭改判这条路
    # 没有，属于漏接。补上以后两条路对链上行为一致。
    await _sync_escrow_settlement(db=db, state=state, target_status=target)

    await apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await mark_voucher_used_if_linked(db, case_row.task_id)

    case_row.status = ArbitrationCaseStatus.EXECUTED.value
    case_row.executed_at = datetime.utcnow()
    case_row.updated_at = datetime.utcnow()
    await db.flush()
    await _append_case_event(
        db=db,
        case_id=case_id,
        event_type=ArbitrationEventType.CASE_EXECUTED,
        detail="arbitration decision executed into settlement",
        metadata={
            "settlement_status": state.status.value,
            "released_amount": state.released_amount,
            "refunded_amount": state.refunded_amount,
            "arbitration_notes": state.arbitration_notes,
        },
    )
    return state


def _sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _pool_to_schema(row: ArbitrationPoolMemberModel) -> ArbitrationPoolMember:
    return ArbitrationPoolMember(
        arbitrator_identity_id=row.arbitrator_identity_id,
        stake_amount=row.stake_amount,
        status=ArbitrationPoolMemberStatus(row.status),
        joined_at=row.joined_at,
        updated_at=row.updated_at,
    )


def _case_to_schema(row: ArbitrationCaseModel) -> ArbitrationCase:
    return ArbitrationCase(
        case_id=row.case_id,
        task_id=row.task_id,
        settlement_id=row.settlement_id,
        opened_by=row.opened_by,
        reason=row.reason,
        status=ArbitrationCaseStatus(row.status),
        required_arbitrators=row.required_arbitrators,
        decided_outcome=ArbitrationVoteDecision(row.decided_outcome) if row.decided_outcome else None,
        final_partial_percent=row.final_partial_percent,
        created_at=row.created_at,
        updated_at=row.updated_at,
        executed_at=row.executed_at,
    )


def _assignment_to_schema(row: ArbitrationAssignmentModel) -> ArbitrationAssignment:
    return ArbitrationAssignment(
        assignment_id=row.assignment_id,
        case_id=row.case_id,
        arbitrator_identity_id=row.arbitrator_identity_id,
        assigned_at=row.assigned_at,
        status=row.status,
    )


def _material_to_schema(row: ArbitrationMaterialPackageModel) -> ArbitrationMaterialPackage:
    return ArbitrationMaterialPackage(
        material_id=row.material_id,
        case_id=row.case_id,
        task_id=row.task_id,
        submitted_by=row.submitted_by,
        bundle_id=row.bundle_id,
        progress_receipt_ids=row.progress_receipt_ids,
        evidence_hashes=row.evidence_hashes,
        package_hash=row.package_hash,
        storage_uri=row.storage_uri,
        format_version=row.format_version,
        submitted_at=row.submitted_at,
    )


def _case_event_to_schema(row: ArbitrationCaseEventModel) -> ArbitrationCaseEvent:
    return ArbitrationCaseEvent(
        event_id=row.event_id,
        case_id=row.case_id,
        event_type=ArbitrationEventType(row.event_type),
        detail=row.detail,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
    )


async def _append_case_event(
    *,
    db: AsyncSession,
    case_id: str,
    event_type: ArbitrationEventType,
    detail: str,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        ArbitrationCaseEventModel(
            case_id=case_id,
            event_type=event_type.value,
            detail=detail,
            metadata_=metadata or {},
            created_at=datetime.utcnow(),
        )
    )


async def _build_arbitration_case_ops_report(
    *,
    db: AsyncSession,
    window_hours: int = 24,
    recent_events_limit: int = 50,
    arbitrator_limit: int = 20,
    overdue_limit: int = 20,
    open_overdue_hours: int = DEFAULT_OPEN_OVERDUE_HOURS,
    voting_overdue_hours: int = DEFAULT_VOTING_OVERDUE_HOURS,
    decided_overdue_hours: int = DEFAULT_DECIDED_OVERDUE_HOURS,
    open_case_threshold: int = DEFAULT_OPEN_CASE_ALERT_THRESHOLD,
    voting_case_threshold: int = DEFAULT_VOTING_CASE_ALERT_THRESHOLD,
    decided_case_threshold: int = DEFAULT_DECIDED_CASE_ALERT_THRESHOLD,
    partial_ratio_threshold: float = DEFAULT_PARTIAL_RATIO_ALERT_THRESHOLD,
) -> ArbitrationCaseOpsReport:
    now = datetime.utcnow()
    hours = max(1, min(window_hours, 24 * 30))
    limit_value = max(1, min(recent_events_limit, 1000))
    cutoff = now - timedelta(hours=hours)

    total_cases = int(
        (await db.execute(select(func.count()).select_from(ArbitrationCaseModel))).scalar_one() or 0
    )
    status_result = await db.execute(
        select(ArbitrationCaseModel.status, func.count())
        .group_by(ArbitrationCaseModel.status)
    )
    status_counts = {str(status): int(count) for status, count in status_result.all()}

    decision_result = await db.execute(
        select(ArbitrationCaseModel.decided_outcome, func.count())
        .where(ArbitrationCaseModel.decided_outcome.is_not(None))
        .group_by(ArbitrationCaseModel.decided_outcome)
    )
    decision_counts = {str(decision): int(count) for decision, count in decision_result.all() if decision}

    events_result = await db.execute(
        select(ArbitrationCaseEventModel)
        .where(ArbitrationCaseEventModel.created_at >= cutoff)
        .order_by(ArbitrationCaseEventModel.created_at.desc())
        .limit(limit_value)
    )
    recent_event_rows = list(reversed(events_result.scalars().all()))
    recent_events = [_case_event_to_schema(row) for row in recent_event_rows]
    alerts = _build_arbitration_ops_alerts(
        status_counts=status_counts,
        decision_counts=decision_counts,
        generated_at=now,
        open_case_threshold=open_case_threshold,
        voting_case_threshold=voting_case_threshold,
        decided_case_threshold=decided_case_threshold,
        partial_ratio_threshold=partial_ratio_threshold,
    )
    arbitrator_activity = await _list_arbitrator_activity(
        db=db,
        window_hours=hours,
        limit=arbitrator_limit,
    )
    overdue_cases = await _list_overdue_cases(
        db=db,
        limit=overdue_limit,
        open_overdue_hours=open_overdue_hours,
        voting_overdue_hours=voting_overdue_hours,
        decided_overdue_hours=decided_overdue_hours,
    )

    return ArbitrationCaseOpsReport(
        window_hours=hours,
        total_cases=total_cases,
        status_counts=status_counts,
        decision_counts=decision_counts,
        recent_events=recent_events,
        alerts=alerts,
        arbitrator_activity=arbitrator_activity,
        overdue_cases=overdue_cases,
        generated_at=now,
    )


def _build_arbitration_ops_alerts(
    *,
    status_counts: dict[str, int],
    decision_counts: dict[str, int],
    generated_at: datetime,
    open_case_threshold: int,
    voting_case_threshold: int,
    decided_case_threshold: int,
    partial_ratio_threshold: float,
) -> list[ArbitrationOpsAlert]:
    alerts: list[ArbitrationOpsAlert] = []
    open_threshold = max(1, open_case_threshold)
    voting_threshold = max(1, voting_case_threshold)
    decided_threshold = max(1, decided_case_threshold)
    partial_ratio_threshold_value = max(0.01, min(partial_ratio_threshold, 1.0))

    open_count = int(status_counts.get(ArbitrationCaseStatus.OPEN.value, 0))
    voting_count = int(status_counts.get(ArbitrationCaseStatus.VOTING.value, 0))
    decided_count = int(status_counts.get(ArbitrationCaseStatus.DECIDED.value, 0))

    if open_count >= open_threshold:
        alerts.append(
            ArbitrationOpsAlert(
                severity=ArbitrationOpsAlertSeverity.MEDIUM,
                alert_type=ArbitrationOpsAlertType.OPEN_CASE_BACKLOG,
                message=f"arbitration open-case backlog: {open_count}",
                metadata={
                    "open_cases": open_count,
                    "threshold": open_threshold,
                },
                generated_at=generated_at,
            )
        )

    if voting_count >= voting_threshold:
        alerts.append(
            ArbitrationOpsAlert(
                severity=ArbitrationOpsAlertSeverity.HIGH,
                alert_type=ArbitrationOpsAlertType.VOTING_CASE_BACKLOG,
                message=f"arbitration voting-case backlog: {voting_count}",
                metadata={
                    "voting_cases": voting_count,
                    "threshold": voting_threshold,
                },
                generated_at=generated_at,
            )
        )

    if decided_count >= decided_threshold:
        alerts.append(
            ArbitrationOpsAlert(
                severity=ArbitrationOpsAlertSeverity.HIGH,
                alert_type=ArbitrationOpsAlertType.DECISION_TIMEOUT_RISK,
                message=f"decided cases pending execution: {decided_count}",
                metadata={
                    "decided_cases": decided_count,
                    "threshold": decided_threshold,
                },
                generated_at=generated_at,
            )
        )

    partial_count = int(decision_counts.get(ArbitrationVoteDecision.PARTIAL.value, 0))
    decided_total = sum(int(value) for value in decision_counts.values())
    partial_ratio = (partial_count / decided_total) if decided_total > 0 else 0.0
    if decided_total > 0 and partial_ratio >= partial_ratio_threshold_value:
        alerts.append(
            ArbitrationOpsAlert(
                severity=ArbitrationOpsAlertSeverity.MEDIUM,
                alert_type=ArbitrationOpsAlertType.DECISION_PARTIAL_SPIKE,
                message=f"partial decision ratio elevated: {partial_ratio:.2%}",
                metadata={
                    "partial_count": partial_count,
                    "decided_total": decided_total,
                    "partial_ratio": round(partial_ratio, 4),
                    "threshold": partial_ratio_threshold_value,
                },
                generated_at=generated_at,
            )
        )

    severity_order = {
        ArbitrationOpsAlertSeverity.HIGH: 3,
        ArbitrationOpsAlertSeverity.MEDIUM: 2,
        ArbitrationOpsAlertSeverity.INFO: 1,
    }
    return sorted(
        alerts,
        key=lambda item: (
            severity_order[item.severity],
            item.generated_at,
        ),
        reverse=True,
    )


async def _list_arbitrator_activity(
    *,
    db: AsyncSession,
    window_hours: int = 24,
    limit: int = 20,
) -> list[ArbitrationArbitratorActivitySummary]:
    now = datetime.utcnow()
    hours = max(1, min(window_hours, 24 * 30))
    limit_value = max(1, min(limit, 200))
    cutoff = now - timedelta(hours=hours)

    assigned_result = await db.execute(
        select(
            ArbitrationAssignmentModel.arbitrator_identity_id,
            func.count(),
            func.max(ArbitrationAssignmentModel.assigned_at),
        )
        .where(ArbitrationAssignmentModel.assigned_at >= cutoff)
        .group_by(ArbitrationAssignmentModel.arbitrator_identity_id)
    )
    voted_result = await db.execute(
        select(
            ArbitrationVoteModel.arbitrator_identity_id,
            func.count(),
            func.max(ArbitrationVoteModel.voted_at),
        )
        .where(ArbitrationVoteModel.voted_at >= cutoff)
        .group_by(ArbitrationVoteModel.arbitrator_identity_id)
    )

    summaries: dict[str, ArbitrationArbitratorActivitySummary] = {}

    for arbitrator_identity_id, assigned_count, last_assigned_at in assigned_result.all():
        summaries[str(arbitrator_identity_id)] = ArbitrationArbitratorActivitySummary(
            arbitrator_identity_id=str(arbitrator_identity_id),
            assigned_count=int(assigned_count or 0),
            vote_count=0,
            last_assigned_at=last_assigned_at,
            last_voted_at=None,
            last_activity_at=last_assigned_at,
        )

    for arbitrator_identity_id, vote_count, last_voted_at in voted_result.all():
        key = str(arbitrator_identity_id)
        existing = summaries.get(
            key,
            ArbitrationArbitratorActivitySummary(
                arbitrator_identity_id=key,
                assigned_count=0,
                vote_count=0,
                last_assigned_at=None,
                last_voted_at=None,
                last_activity_at=None,
            ),
        )
        existing.vote_count = int(vote_count or 0)
        existing.last_voted_at = last_voted_at
        if existing.last_activity_at is None or (last_voted_at and last_voted_at > existing.last_activity_at):
            existing.last_activity_at = last_voted_at
        summaries[key] = existing

    sorted_items = sorted(
        summaries.values(),
        key=lambda item: (
            item.last_activity_at or datetime.min,
            item.vote_count,
            item.assigned_count,
        ),
        reverse=True,
    )
    return sorted_items[:limit_value]


async def _list_overdue_cases(
    *,
    db: AsyncSession,
    limit: int = 20,
    open_overdue_hours: int = DEFAULT_OPEN_OVERDUE_HOURS,
    voting_overdue_hours: int = DEFAULT_VOTING_OVERDUE_HOURS,
    decided_overdue_hours: int = DEFAULT_DECIDED_OVERDUE_HOURS,
) -> list[ArbitrationCaseOverdueItem]:
    now = datetime.utcnow()
    limit_value = max(1, min(limit, 200))
    open_hours = max(1, open_overdue_hours)
    voting_hours = max(1, voting_overdue_hours)
    decided_hours = max(1, decided_overdue_hours)

    open_cutoff = now - timedelta(hours=open_hours)
    voting_cutoff = now - timedelta(hours=voting_hours)
    decided_cutoff = now - timedelta(hours=decided_hours)

    result = await db.execute(
        select(ArbitrationCaseModel)
        .where(
            or_(
                and_(
                    ArbitrationCaseModel.status == ArbitrationCaseStatus.OPEN.value,
                    ArbitrationCaseModel.created_at <= open_cutoff,
                ),
                and_(
                    ArbitrationCaseModel.status == ArbitrationCaseStatus.VOTING.value,
                    ArbitrationCaseModel.updated_at <= voting_cutoff,
                ),
                and_(
                    ArbitrationCaseModel.status == ArbitrationCaseStatus.DECIDED.value,
                    ArbitrationCaseModel.updated_at <= decided_cutoff,
                ),
            )
        )
        .order_by(ArbitrationCaseModel.updated_at.asc(), ArbitrationCaseModel.created_at.asc())
        .limit(limit_value)
    )
    rows = result.scalars().all()

    items: list[ArbitrationCaseOverdueItem] = []
    for row in rows:
        if row.status == ArbitrationCaseStatus.OPEN.value:
            stage = ArbitrationOverdueStage.OPEN
            base_at = row.created_at
            threshold = open_hours
        elif row.status == ArbitrationCaseStatus.VOTING.value:
            stage = ArbitrationOverdueStage.VOTING
            base_at = row.updated_at
            threshold = voting_hours
        else:
            stage = ArbitrationOverdueStage.DECIDED_PENDING_EXECUTION
            base_at = row.updated_at
            threshold = decided_hours
        age_hours = max(0.0, (now - base_at).total_seconds() / 3600.0)
        items.append(
            ArbitrationCaseOverdueItem(
                case_id=row.case_id,
                task_id=row.task_id,
                status=ArbitrationCaseStatus(row.status),
                opened_by=row.opened_by,
                decided_outcome=ArbitrationVoteDecision(row.decided_outcome) if row.decided_outcome else None,
                overdue_stage=stage,
                age_hours=round(age_hours, 2),
                threshold_hours=threshold,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return items

