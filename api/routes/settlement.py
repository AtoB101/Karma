"""Karma API — Settlement (public state endpoints)"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import resolve_agent_id_from_auth_headers
from config.settings import settings
from core.schemas import (
    ProgressConfirmationStatus,
    SettlementState,
    SettlementTransitionAudit,
    TaskStatus,
    VoucherStatus,
)
from core.settlement.engine import can_transition, canonical_task_status
from db.models.orm import ProgressReceiptModel, SettlementTransitionAuditModel, VoucherModel
from db.session import get_db
from db.stores.receipt_store import PostgresReceiptStore
from db.stores.settlement_store import PostgresSettlementStore
from services.capacity_resolution import apply_capacity_resolution, move_reserved_to_disputed
from services.auto_arbitration_rules import adjust_auto_split_for_rules, build_auto_arbitration_context
from services.runtime_safety import (
    assert_runtime_operation_allowed,
    audit_capacity_anchor_and_maybe_trip,
)
from services.security_monitoring import SecurityMonitoringEventType, record_security_event
from services.settlement_voucher import mark_voucher_used_if_linked
from services.path_param_safety import validate_public_url_segment
from services.settlement_party_access import (
    require_buyer,
    require_buyer_on_create,
    require_buyer_or_worker,
    require_worker,
)
from services.settlement_cycle_guard import assert_lock_does_not_close_payment_cycle
from services.settlement_receipt_release_guard import ensure_success_execution_receipt_before_seller_payout
from services.task_contract_guard import ensure_task_contract_exists
from services.text_safety import validate_safe_storage_text_optional

router = APIRouter()


class CreateSettlementRequest(BaseModel):
    task_id: str
    client_agent_id: str
    escrow_amount: float
    currency: str = "USD"
    voucher_id: str | None = None
    delivery_deadline_at: datetime | None = None


class LockRequest(BaseModel):
    worker_agent_id: str


class PartialSettlementRequest(BaseModel):
    settled_value_percent: float = Field(gt=0.0, le=100.0)
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


class RegretRequest(BaseModel):
    buyer_identity_id: str | None = None
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_regret_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


class DisputeRequest(BaseModel):
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_dispute_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


@router.post("/create", response_model=SettlementState, status_code=201)
async def create_settlement(body: CreateSettlementRequest, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    validate_public_url_segment("task_id", body.task_id)
    validate_public_url_segment("client_agent_id", body.client_agent_id)
    if body.voucher_id:
        validate_public_url_segment("voucher_id", body.voucher_id)
    require_buyer_on_create(request, body.client_agent_id)
    await ensure_task_contract_exists(db, body.task_id)
    from config.settings import settings as _s

    voucher_id = body.voucher_id
    delivery_deadline_at = body.delivery_deadline_at
    progress_rule_spec = None
    escrow_amount = body.escrow_amount
    if voucher_id:
        vrow = await db.get(VoucherModel, voucher_id)
        if not vrow:
            raise HTTPException(404, f"voucher {voucher_id} not found")
        if vrow.status != VoucherStatus.ACCEPTED.value:
            raise HTTPException(409, f"voucher must be accepted before settlement bind, got {vrow.status}")
        if vrow.buyer_identity_id != body.client_agent_id:
            raise HTTPException(409, "settlement client_agent_id must match voucher buyer_identity_id")
        if abs(vrow.bill_credit_amount - body.escrow_amount) > 1e-6:
            raise HTTPException(409, "escrow_amount must equal voucher bill_credit_amount when voucher_id is set")
        progress_rule_spec = vrow.progress_rule_spec

    state = SettlementState(
        task_id=body.task_id,
        escrow_amount=escrow_amount,
        currency=body.currency,
        client_agent_id=body.client_agent_id,
        status=TaskStatus.DRAFT,
        settlement_mode=_s.settlement_mode,
        chain_id=_s.testnet_chain_id if _s.settlement_mode != "offchain" else None,
        contract_address=_s.karma_engine_address or None,
        voucher_id=voucher_id,
        delivery_deadline_at=delivery_deadline_at,
        progress_rule_spec=progress_rule_spec,
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
    validate_public_url_segment("task_id", task_id)
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    require_buyer(request, state)
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
    validate_public_url_segment("task_id", task_id)
    validate_public_url_segment("worker_agent_id", body.worker_agent_id)
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    require_buyer(request, state)
    if body.worker_agent_id == state.client_agent_id:
        raise HTTPException(
            status_code=409,
            detail="worker_agent_id cannot equal settlement buyer (client_agent_id)",
        )
    await assert_lock_does_not_close_payment_cycle(
        db,
        task_id=task_id,
        buyer_id=state.client_agent_id,
        worker_id=body.worker_agent_id,
    )
    if settings.settlement_lock_requires_pending and canonical_task_status(state.status) == TaskStatus.DRAFT:
        raise HTTPException(
            409,
            "settlement must be moved to pending before lock (settlement_lock_requires_pending)",
        )
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
    validate_public_url_segment("task_id", task_id)
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    require_worker(request, state)
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
    validate_public_url_segment("task_id", task_id)
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    require_worker(request, state)
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
    validate_public_url_segment("task_id", task_id)
    assert_runtime_operation_allowed("new_task")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    require_buyer_or_worker(request, state)
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
    validate_public_url_segment("task_id", task_id)
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
    validate_public_url_segment("task_id", task_id)
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
    validate_public_url_segment("task_id", task_id)
    assert_runtime_operation_allowed("new_settlement")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    require_buyer(request, state)
    confirmed_claimed = await _confirmed_progress_percent(db, task_id)
    if confirmed_claimed > 1e-9 and body.settled_value_percent > confirmed_claimed + 1e-4:
        raise HTTPException(
            400,
            f"settled_value_percent exceeds confirmed claimed value ceiling ({confirmed_claimed:.4f}%)",
        )
    settled_amount = round(state.escrow_amount * body.settled_value_percent / 100.0, 2)
    refunded_amount = round(state.escrow_amount - settled_amount, 2)

    await ensure_success_execution_receipt_before_seller_payout(db, task_id, settled_amount=settled_amount)

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

    await apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await mark_voucher_used_if_linked(db, task_id)
    await db.flush()
    return state


@router.post("/{task_id}/regret", response_model=SettlementState)
async def regret_settlement(task_id: str, body: RegretRequest, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("task_id", task_id)
    assert_runtime_operation_allowed("new_settlement")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    require_buyer(request, state)
    if body.buyer_identity_id is not None and body.buyer_identity_id != state.client_agent_id:
        raise HTTPException(403, "buyer_identity_id does not match settlement buyer (client_agent_id)")
    confirmed_percent = await _confirmed_progress_percent(db, task_id)
    settled_amount = round(state.escrow_amount * confirmed_percent / 100.0, 2)
    refunded_amount = round(state.escrow_amount - settled_amount, 2)

    await ensure_success_execution_receipt_before_seller_payout(db, task_id, settled_amount=settled_amount)

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

    await apply_capacity_resolution(
        db=db,
        buyer_identity_id=body.buyer_identity_id or state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await mark_voucher_used_if_linked(db, task_id)
    await db.flush()
    return state


@router.post("/{task_id}/dispute", response_model=SettlementState)
async def open_dispute(task_id: str, body: DisputeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("task_id", task_id)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    require_buyer(request, state)
    await move_reserved_to_disputed(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
    )
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


@router.post("/{task_id}/buyer-accept", response_model=SettlementState)
async def buyer_accept_settlement(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """P0: full release to seller after delivery — requires at least one successful execution receipt."""
    validate_public_url_segment("task_id", task_id)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    require_buyer(request, state)
    if state.status != TaskStatus.DELIVERED:
        raise HTTPException(409, "buyer accept requires delivered status")
    assert_runtime_operation_allowed("new_settlement")
    await audit_capacity_anchor_and_maybe_trip(db=db)

    await ensure_success_execution_receipt_before_seller_payout(
        db, task_id, settled_amount=float(state.escrow_amount)
    )

    state.released_amount = round(state.escrow_amount, 2)
    state.refunded_amount = 0.0
    state.arbitration_notes = "buyer accepted delivery — full settlement to seller"
    state.released_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    state = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.SETTLED,
        reason="buyer accepted delivered work",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )
    await apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=state.escrow_amount,
        refunded_amount=0.0,
    )
    await mark_voucher_used_if_linked(db, task_id)
    await db.flush()
    return state


@router.post("/{task_id}/auto-arbitrate", response_model=SettlementState)
async def auto_arbitrate(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("task_id", task_id)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    require_buyer_or_worker(request, state)
    status_before = state.status
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
    ctx = await build_auto_arbitration_context(
        db,
        task_id=task_id,
        state_status=status_before,
        delivery_deadline_at=state.delivery_deadline_at,
    )
    settled_amount, refunded_amount, rule_notes = adjust_auto_split_for_rules(
        ctx,
        confirmed_percent=confirmed_percent,
        escrow_amount=state.escrow_amount,
    )
    await ensure_success_execution_receipt_before_seller_payout(db, task_id, settled_amount=settled_amount)
    decision = TaskStatus.REFUNDED if settled_amount <= 1e-6 else TaskStatus.SETTLED
    notes = rule_notes
    if ctx.notes:
        notes = notes + " | " + "; ".join(ctx.notes)

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

    await apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=settled_amount,
        refunded_amount=refunded_amount,
    )
    await mark_voucher_used_if_linked(db, task_id)
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
