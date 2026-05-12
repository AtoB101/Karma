"""Karma API — Settlement (public state endpoints)"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import resolve_agent_id_from_auth_headers
from core.schemas import (
    CapacityState,
    ProgressConfirmationStatus,
    SettlementState,
    SettlementTransitionAudit,
    TaskStatus,
)
from core.settlement.engine import can_transition
from db.models.orm import CapacityModel, ProgressReceiptModel, SettlementTransitionAuditModel
from db.session import get_db
from db.stores.settlement_store import PostgresSettlementStore
from services.capacity_ledger import assert_capacity_invariants
from services.runtime_safety import (
    assert_runtime_operation_allowed,
    audit_capacity_anchor_and_maybe_trip,
)

router = APIRouter()


class CreateSettlementRequest(BaseModel):
    task_id: str
    client_agent_id: str
    escrow_amount: float
    currency: str = "USD"


class LockRequest(BaseModel):
    worker_agent_id: str


class PartialSettlementRequest(BaseModel):
    settled_value_percent: float = Field(gt=0.0, le=100.0)
    reason: str | None = None


class RegretRequest(BaseModel):
    buyer_identity_id: str | None = None
    reason: str | None = None


class DisputeRequest(BaseModel):
    reason: str | None = None


@router.post("/create", response_model=SettlementState, status_code=201)
async def create_settlement(body: CreateSettlementRequest, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    from config.settings import settings as _s
    state = SettlementState(
        task_id=body.task_id,
        escrow_amount=body.escrow_amount,
        currency=body.currency,
        client_agent_id=body.client_agent_id,
        status=TaskStatus.DRAFT,
        settlement_mode=_s.settlement_mode,
        chain_id=_s.testnet_chain_id if _s.settlement_mode != "offchain" else None,
        contract_address=_s.karma_engine_address or None,
    )
    store = PostgresSettlementStore(db)
    existing = await store.get(body.task_id)
    if existing:
        raise HTTPException(409, f"Settlement already exists for task {body.task_id}")
    await store.save(state)
    await _record_transition_audit(
        db=db,
        state=state,
        from_status=None,
        to_status=TaskStatus.DRAFT,
        transition_allowed=True,
        guard_stage="route",
        reason="settlement created",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )
    return state


@router.post("/{task_id}/pending", response_model=SettlementState)
async def mark_settlement_pending(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.PENDING,
        reason="task moved to pending",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


@router.post("/{task_id}/lock", response_model=SettlementState)
async def lock_settlement(task_id: str, body: LockRequest, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    state.worker_agent_id = body.worker_agent_id
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.ACCEPTED,
        reason="worker accepted settlement",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


@router.post("/{task_id}/start", response_model=SettlementState)
async def start_settlement(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.IN_PROGRESS,
        reason="task execution started",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


@router.post("/{task_id}/submit", response_model=SettlementState)
async def submit_settlement(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.DELIVERED,
        reason="delivery submitted",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


@router.post("/{task_id}/fail", response_model=SettlementState)
async def fail_settlement(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.CANCELLED,
        reason="task failed and cancelled",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


@router.get("/{task_id}", response_model=SettlementState)
async def get_settlement(task_id: str, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    return state


@router.get("/{task_id}/transitions", response_model=list[SettlementTransitionAudit])
async def list_settlement_transitions(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SettlementTransitionAuditModel)
        .where(SettlementTransitionAuditModel.task_id == task_id)
        .order_by(SettlementTransitionAuditModel.created_at.asc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [_transition_audit_to_schema(row) for row in rows]


@router.post("/{task_id}/partial", response_model=SettlementState)
async def partial_settlement(task_id: str, body: PartialSettlementRequest, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_settlement")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    settled_amount = round(state.escrow_amount * body.settled_value_percent / 100.0, 2)
    refunded_amount = round(state.escrow_amount - settled_amount, 2)

    state.released_amount = settled_amount
    state.refunded_amount = refunded_amount
    state.arbitration_notes = body.reason or f"partial settlement at {body.settled_value_percent:.2f}%"
    state.updated_at = datetime.utcnow()
    state.released_at = datetime.utcnow()
    state = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.SETTLED,
        reason="manual partial settlement applied",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )

    await _apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await db.flush()
    return state


@router.post("/{task_id}/regret", response_model=SettlementState)
async def regret_settlement(task_id: str, body: RegretRequest, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_settlement")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    confirmed_percent = await _confirmed_progress_percent(db, task_id)
    settled_amount = round(state.escrow_amount * confirmed_percent / 100.0, 2)
    refunded_amount = round(state.escrow_amount - settled_amount, 2)

    state.dispute_reason = body.reason or "buyer regret"
    state.released_amount = settled_amount
    state.refunded_amount = refunded_amount
    state.arbitration_notes = (
        body.reason or f"buyer regret with confirmed progress {confirmed_percent:.2f}%"
    )
    state.released_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    state = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.SETTLED,
        reason="buyer regret settlement",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )

    await _apply_capacity_resolution(
        db=db,
        buyer_identity_id=body.buyer_identity_id or state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await db.flush()
    return state


@router.post("/{task_id}/dispute", response_model=SettlementState)
async def open_dispute(task_id: str, body: DisputeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    state.dispute_reason = body.reason or "buyer disputed task result"
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.DISPUTED,
        reason="dispute opened",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


@router.post("/{task_id}/auto-arbitrate", response_model=SettlementState)
async def auto_arbitrate(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    state = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.ARBITRATED,
        reason="auto arbitration started",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )

    confirmed_percent = await _confirmed_progress_percent(db, task_id)
    if confirmed_percent <= 0.0:
        decision = TaskStatus.REFUNDED
        settled_amount = 0.0
        refunded_amount = round(state.escrow_amount, 2)
        notes = "auto arbitration: no confirmed progress, buyer wins"
    elif confirmed_percent >= 90.0:
        decision = TaskStatus.SETTLED
        settled_amount = round(state.escrow_amount, 2)
        refunded_amount = 0.0
        notes = "auto arbitration: near-complete confirmed progress, seller wins"
    else:
        decision = TaskStatus.SETTLED
        settled_amount = round(state.escrow_amount * confirmed_percent / 100.0, 2)
        refunded_amount = round(state.escrow_amount - settled_amount, 2)
        notes = f"auto arbitration: partial split by confirmed progress {confirmed_percent:.2f}%"

    state.released_amount = settled_amount
    state.refunded_amount = refunded_amount
    state.arbitration_notes = notes
    state.updated_at = datetime.utcnow()
    state.released_at = datetime.utcnow() if settled_amount > 0 else None
    state = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=decision,
        reason="auto arbitration finalized",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )

    await _apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await db.flush()
    return state


def _resolve_actor_id(request: Request) -> str | None:
    return resolve_agent_id_from_auth_headers(
        authorization=request.headers.get("authorization"),
        api_key=request.headers.get("x-karma-api-key"),
    )


async def _apply_transition(
    *,
    db: AsyncSession,
    store: PostgresSettlementStore,
    state: SettlementState,
    target_status: TaskStatus,
    reason: str,
    route_path: str,
    actor_id: str | None,
) -> SettlementState:
    from_status = state.status
    if not can_transition(from_status, target_status):
        detail = f"invalid status transition: {from_status.value} -> {target_status.value}"
        await _record_transition_audit(
            db=db,
            state=state,
            from_status=from_status,
            to_status=target_status,
            transition_allowed=False,
            guard_stage="route",
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
        await _record_transition_audit(
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

    await _record_transition_audit(
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
    return state


async def _record_transition_audit(
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
        metadata_={},
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    return _transition_audit_to_schema(row)


def _transition_audit_to_schema(row: SettlementTransitionAuditModel) -> SettlementTransitionAudit:
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


async def _confirmed_progress_percent(db: AsyncSession, task_id: str) -> float:
    result = await db.execute(
        select(func.max(ProgressReceiptModel.claimed_value_percent)).where(
            ProgressReceiptModel.task_id == task_id,
            ProgressReceiptModel.confirmation_status == ProgressConfirmationStatus.CONFIRMED.value,
        )
    )
    confirmed = result.scalar_one_or_none()
    if confirmed is None:
        return 0.0
    return float(confirmed)


async def _apply_capacity_resolution(
    *,
    db: AsyncSession,
    buyer_identity_id: str,
    escrow_amount: float,
    settled_amount: float,
    refunded_amount: float,
) -> None:
    # Best-effort accounting sync when capacity is tracked for this identity.
    # No-op if caller does not use capacity ledger.
    cap = await db.get(CapacityModel, buyer_identity_id)
    if not cap:
        return
    if cap.reserved_credits + 1e-9 < escrow_amount:
        raise HTTPException(409, "capacity reserved_credits lower than settlement escrow amount")
    if cap.total_bill_credits + 1e-9 < escrow_amount:
        raise HTTPException(409, "capacity total_bill_credits lower than settlement escrow amount")
    if cap.total_locked_usdc + 1e-9 < escrow_amount:
        raise HTTPException(409, "capacity total_locked_usdc lower than settlement escrow amount")

    cap.reserved_credits -= escrow_amount
    cap.burned_credits += settled_amount
    cap.released_credits += refunded_amount
    cap.total_bill_credits -= escrow_amount
    cap.total_locked_usdc -= escrow_amount
    cap.updated_at = datetime.utcnow()
    _assert_capacity_model(cap)
    await audit_capacity_anchor_and_maybe_trip(db=db)


def _assert_capacity_model(cap: CapacityModel) -> None:
    try:
        assert_capacity_invariants(
            CapacityState(
                identity_id=cap.identity_id,
                total_locked_usdc=cap.total_locked_usdc,
                total_bill_credits=cap.total_bill_credits,
                available_credits=cap.available_credits,
                reserved_credits=cap.reserved_credits,
                in_progress_credits=cap.in_progress_credits,
                confirmed_progress_credits=cap.confirmed_progress_credits,
                disputed_credits=cap.disputed_credits,
                pending_settlement_credits=cap.pending_settlement_credits,
                burned_credits=cap.burned_credits,
                released_credits=cap.released_credits,
                updated_at=cap.updated_at,
            )
        )
    except ValueError as exc:
        raise HTTPException(500, "capacity invariant check failed") from exc
