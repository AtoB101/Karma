"""Karma API — Settlement (public state endpoints)"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import resolve_agent_id_from_auth_headers
from config.settings import settings
from core.schemas import (
    ProgressConfirmationStatus,
    RejectionReason,
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


async def _sync_payment_intents_after_settled(db: AsyncSession, task_id: str) -> None:
    from services.payment_intent_service import mark_intents_settled_for_task

    await mark_intents_settled_for_task(db, task_id)


class CreateSettlementRequest(BaseModel):
    task_id: str
    client_agent_id: str
    escrow_amount: float
    currency: str = "USD"
    voucher_id: str | None = None
    delivery_deadline_at: datetime | None = None
    profile_id: str | None = None


class LockRequest(BaseModel):
    worker_agent_id: str


class BuyerRejectRequest(BaseModel):
    """MVVS V1 — Buyer rejection with mandatory reason_code."""
    reason_code: RejectionReason = Field(description="MVVS V1 standardized rejection code (required)")
    reason: str | None = Field(default=None, max_length=2000, description="Optional free-text detail")

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


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
    reason_code: RejectionReason | None = Field(
        default=None,
        description="MVVS V1 — standardized rejection reason code",
    )

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_regret_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


class DisputeRequest(BaseModel):
    reason: str | None = None
    reason_code: RejectionReason | None = Field(
        default=None,
        description="MVVS V1 — standardized rejection reason code",
    )

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
    if body.profile_id:
        validate_public_url_segment("profile_id", body.profile_id)
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
        profile_id=body.profile_id,
        status=TaskStatus.DRAFT,
        settlement_mode=_s.settlement_mode,
        chain_id=_s.testnet_chain_id if _s.settlement_mode != "offchain" else None,
        contract_address=_s.karma_bilateral_address or _s.karma_engine_address or None,
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
    new_state = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.ACCEPTED,
        reason="worker accepted settlement",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )
    # On-chain (testnet/hybrid): on acceptance, auto-lock buyer escrow + seller
    # penalty + bind. Guarded by is_onchain() so offchain/test runs never touch
    # the Celery broker.
    escrow_wei = _settlement_escrow_wei(state)
    if escrow_wei > 0:
        from services.chain.settlement_adapter import settlement_router
        if settlement_router.is_onchain():
            from worker.tasks import lock_and_bind_onchain
            lock_and_bind_onchain.delay(task_id, escrow_wei)
    return new_state


def _settlement_escrow_wei(state) -> int:
    """Convert the off-chain USD escrow amount to the token's raw wei units.

    Off-chain escrow is tracked in USD float; the on-chain KarmaBilateral works in
    the token's raw units (6-decimal stablecoin). Returns 0 when the amount is
    unset or non-numeric (the on-chain lock is then skipped).
    """
    from config.settings import settings
    try:
        usd = float(state.escrow_amount or 0)
    except (TypeError, ValueError):
        return 0
    if usd <= 0:
        return 0
    return int(usd * (10 ** settings.settlement_token_decimals))


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


def _scene_id_from_settlement(state: SettlementState) -> str | None:
    spec = getattr(state, "progress_rule_spec", None) or {}
    if isinstance(spec, dict):
        sid = spec.get("scene_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


def _seal_p8_attestation(state: SettlementState, *, scene_id: str | None, agent_auto: bool = False) -> dict | None:
    """P8: seal encrypted public attestation + scene reputation after SETTLED."""
    sid = (scene_id or _scene_id_from_settlement(state) or "").strip()
    if not sid or not state.worker_agent_id:
        return None
    try:
        from services.delivery_verification import get_verification_for_task
        from services.settlement_reputation import seal_settlement_attestation

        dv = get_verification_for_task(state.task_id)
        spec = getattr(state, "progress_rule_spec", None) or {}
        capture_id = None
        if isinstance(spec, dict):
            if_meta = spec.get("important_fields") or {}
            capture_id = if_meta.get("capture_id")
        return seal_settlement_attestation(
            task_id=state.task_id,
            scene_id=sid,
            buyer_agent_id=state.client_agent_id,
            seller_agent_id=state.worker_agent_id,
            amount=float(state.released_amount or state.escrow_amount or 0),
            currency="USDC",
            outcome="SETTLED",
            capture_id=capture_id,
            delivery_verification_id=(dv or {}).get("verification_id"),
            agent_auto_verified=agent_auto,
        )
    except Exception:  # noqa: BLE001
        return None


def _assert_p7_delivery_gate(task_id: str, state: SettlementState, *, stage: str) -> dict:
    """P7: physical/ticket sessions must be VERIFIED before deliver/settle release."""
    from services.delivery_verification import (
        DeliveryVerificationError,
        get_verification_for_task,
        require_verified_for_settle,
        scene_policy,
    )

    scene_id = _scene_id_from_settlement(state)
    sess = get_verification_for_task(task_id)
    if sess is None and not scene_id:
        return {"ok": True, "skipped": True, "reason": "no_scene_or_session"}
    mode = (sess or {}).get("mode") or scene_policy(scene_id or "api_tool_call").get("mode")
    # digital without session: allow (auto_complete / receipt path)
    if mode in {"digital_light", "ride_track"} and sess is None:
        return {"ok": True, "skipped": True, "reason": "digital_no_session", "mode": mode}
    try:
        return require_verified_for_settle(
            task_id=task_id,
            scene_id=scene_id,
            allow_missing_session_for_digital=True,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(
            409,
            {
                "error": "delivery_verification_required",
                "stage": stage,
                "detail": str(exc),
                "scene_id": scene_id,
                "mode": mode,
                "verification": sess,
                "next_steps": [
                    "POST /v1/delivery-verification/sessions",
                    "seller-ship → logistics-intake → capture-challenge → logistics-deliver",
                    "buyer-confirm (or wait silent default after POD)",
                ],
            },
        ) from exc


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
    # P7 gate: if a delivery-verification session exists for physical scenes, must be VERIFIED
    _assert_p7_delivery_gate(task_id, state, stage="submit")
    out = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.DELIVERED,
        reason="delivery submitted",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )
    from services.openclaw_webhook import emit_openclaw_event

    emit_openclaw_event(
        "settlement.delivered",
        {
            "task_id": task_id,
            "buyer_identity_id": out.client_agent_id,
            "seller_identity_id": out.worker_agent_id or "",
            "voucher_id": out.voucher_id,
            "status": out.status.value if hasattr(out.status, "value") else str(out.status),
            "escrow_amount": float(out.escrow_amount),
        },
    )
    return out


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
    st = canonical_task_status(state.status)
    # P0-9: splits must not exceed confirmed claimed liability; without any confirmed progress,
    # partial release is only allowed after formal delivery (submit) so settlement does not skip
    # the delivered checkpoint from in_progress.
    if body.settled_value_percent > 1e-4:
        if confirmed_claimed > 1e-9:
            if body.settled_value_percent > confirmed_claimed + 1e-4:
                raise HTTPException(
                    400,
                    f"settled_value_percent exceeds confirmed claimed value ceiling ({confirmed_claimed:.4f}%)",
                )
        elif st != TaskStatus.DELIVERED:
            raise HTTPException(
                400,
                "partial settlement with no confirmed progress requires delivered status "
                "(POST /v1/settlement/{task_id}/submit first); otherwise confirm progress receipts "
                "up to the intended split",
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
    await _sync_payment_intents_after_settled(db, task_id)
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
    await _sync_payment_intents_after_settled(db, task_id)
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
    state.rejection_reason_code = body.reason_code.value if body.reason_code else None
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
async def buyer_accept_settlement(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    confirmation_session_id: str | None = None,
    scene_id: str | None = None,
):
    """P0: full release to seller after delivery — requires at least one successful execution receipt.

    P4: when scene policy marks ``buyer_accept_settle`` as OWNER_CONFIRM, require a
    CONFIRMED confirmation session (skipped for AUTO/POLICY_AUTO or demo env).
    """
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

    # P7: delivery verification must be VERIFIED when session/scene requires it
    settle_scene_hint = (scene_id or "").strip() or _scene_id_from_settlement(state)
    if settle_scene_hint and not getattr(state, "progress_rule_spec", None):
        # attach hint for gate when progress_rule_spec missing
        try:
            state.progress_rule_spec = {"scene_id": settle_scene_hint}  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    _assert_p7_delivery_gate(task_id, state, stage="buyer-accept")

    # P4 settle confirmation gate (reality: hotel/B2B/high-risk need owner Yes)
    from services.human_confirmation_policy import (
        ConfirmationPolicyError,
        allow_demo_confirmation_bypass,
        assert_step_allowed,
        create_confirmation_session,
        is_high_risk_scene,
        resolve_gate,
    )

    # Hard-require OWNER_CONFIRM / high-risk using settlement scene (query OR stored).
    # Omitting scene_id must not bypass the gate (adversarial soft-spot closed).
    settle_scene = (settle_scene_hint or "").strip()
    if settle_scene:
        settle_gate = resolve_gate(
            scene_id=settle_scene, role="buyer", step="buyer_accept_settle"
        )
        must_settle_confirm = (
            settle_gate.get("mode") == "OWNER_CONFIRM" or is_high_risk_scene(settle_scene)
        )
        if must_settle_confirm and not (
            allow_demo_confirmation_bypass() and not is_high_risk_scene(settle_scene)
        ):
            try:
                assert_step_allowed(
                    scene_id=settle_scene,
                    role="buyer",
                    step="buyer_accept_settle",
                    confirmation_session_id=confirmation_session_id,
                    policy_auto_allowed=False,
                    expected_owner_agent_id=state.client_agent_id,
                    amount=float(state.escrow_amount or 0),
                    consume=True,
                )
            except ConfirmationPolicyError as exc:
                sess = create_confirmation_session(
                    scene_id=settle_scene,
                    role="buyer",
                    step="buyer_accept_settle",
                    owner_agent_id=state.client_agent_id,
                    context={
                        "amount": float(state.escrow_amount or 0),
                        "currency": "USDC",
                    },
                    interaction_ref=f"settle:{task_id}",
                    policy_auto_allowed=False,
                )
                raise HTTPException(
                    403,
                    {
                        "error": "buyer_accept_settle_confirmation_required",
                        "detail": str(exc),
                        "scene_id": settle_scene,
                        "confirmation": sess,
                        "owner_prompt_zh": sess.get("prompt_zh"),
                        "next_steps": [
                            f"POST /v1/confirmations/sessions/{sess.get('session_id')}/decide "
                            '{"confirm": true, "actor_agent_id": "<buyer>"}',
                            f"POST /v1/settlement/{task_id}/buyer-accept"
                            f"?confirmation_session_id={sess.get('session_id')}"
                            f"&scene_id={settle_scene}",
                        ],
                    },
                ) from exc

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
    await _sync_payment_intents_after_settled(db, task_id)
    settle_scene_final = settle_scene or _scene_id_from_settlement(state) or "api_tool_call"
    if state.worker_agent_id:
        from services.settlement_reputation import apply_settle_reputation

        await apply_settle_reputation(
            db,
            seller_agent_id=state.worker_agent_id,
            scene_id=settle_scene_final,
            amount=float(state.released_amount or state.escrow_amount or 0),
            success=True,
            buyer_agent_id=state.client_agent_id,
            exclude_task_id=task_id,
        )
    p8_attest = _seal_p8_attestation(state, scene_id=settle_scene_final, agent_auto=False)
    await db.flush()
    from services.openclaw_webhook import emit_openclaw_event

    emit_openclaw_event(
        "settlement.settled",
        {
            "task_id": task_id,
            "buyer_identity_id": state.client_agent_id,
            "seller_identity_id": state.worker_agent_id or "",
            "voucher_id": state.voucher_id,
            "status": state.status.value if hasattr(state.status, "value") else str(state.status),
            "escrow_amount": float(state.escrow_amount),
            "settled_amount": float(state.released_amount or 0),
            "attestation_id": (p8_attest or {}).get("attestation_id"),
            "outcome_commitment": (p8_attest or {}).get("outcome_commitment"),
        },
    )
    # Attach P8 public attestation on response via arbitration_notes extension field unused —
    # clients should GET /v1/settlement-reputation/tasks/{id}/attestation
    if p8_attest and hasattr(state, "arbitration_notes"):
        state.arbitration_notes = (
            f"{state.arbitration_notes or ''}; p8_attestation={p8_attest.get('attestation_id')}"
        ).strip("; ")
    return state


@router.post("/{task_id}/auto-confirm", response_model=SettlementState)
async def auto_confirm_settlement(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    MVVS V1 — Timeout-based auto-confirmation.
    """
    validate_public_url_segment("task_id", task_id)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    if canonical_task_status(state.status) != TaskStatus.DELIVERED:
        raise HTTPException(409, f"auto-confirm requires delivered, got {state.status.value}")
    if state.confirm_window_hours is None:
        raise HTTPException(409, "confirm_window_hours not set")
    now = datetime.utcnow()
    if state.confirm_deadline_at is None and state.updated_at:
        state.confirm_deadline_at = state.updated_at + timedelta(hours=state.confirm_window_hours)
    if state.confirm_deadline_at and now < state.confirm_deadline_at:
        remaining = (state.confirm_deadline_at - now).total_seconds() / 3600
        raise HTTPException(409, f"confirm window not expired — {remaining:.1f}h remaining")
    require_buyer_or_worker(request, state)
    assert_runtime_operation_allowed("new_settlement")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    # P7/P8: auto-confirm still requires delivery verification when session/scene demands it
    _assert_p7_delivery_gate(task_id, state, stage="auto-confirm")
    scene_for_auto = _scene_id_from_settlement(state) or "api_tool_call"
    from services.settlement_reputation import agent_auto_verify_decision

    auto_dec = agent_auto_verify_decision(
        scene_id=scene_for_auto,
        task_id=task_id,
        delivery_verified=True,
    )
    # High-risk / OWNER_CONFIRM delayed scenes must not silently settle via this path
    if not auto_dec.get("allowed") and scene_for_auto in {
        "financial_services",
        "healthcare_medical",
    }:
        raise HTTPException(
            409,
            {
                "error": "auto_confirm_forbidden_for_scene",
                "scene_id": scene_for_auto,
                "detail": auto_dec.get("reason_zh"),
            },
        )
    state.arbitration_notes = f"auto-confirmed after {state.confirm_window_hours}h window"
    state.updated_at = now
    state = await _apply_transition(db=db, store=store, state=state,
        target_status=TaskStatus.AUTO_CONFIRMED,
        reason=f"confirm window ({state.confirm_window_hours}h) expired",
        route_path=str(request.url.path), actor_id=_resolve_actor_id(request))
    state.released_amount = round(state.escrow_amount, 2)
    state.refunded_amount = 0.0
    state.released_at = now
    state = await _apply_transition(db=db, store=store, state=state,
        target_status=TaskStatus.SETTLED,
        reason="auto-confirmed → settled",
        route_path=str(request.url.path), actor_id=_resolve_actor_id(request))
    await apply_capacity_resolution(db=db, buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount, settled_amount=state.escrow_amount, refunded_amount=0.0)
    await mark_voucher_used_if_linked(db, task_id)
    await _sync_payment_intents_after_settled(db, task_id)
    if state.worker_agent_id:
        from services.settlement_reputation import apply_settle_reputation

        await apply_settle_reputation(
            db,
            seller_agent_id=state.worker_agent_id,
            scene_id=scene_for_auto,
            amount=float(state.released_amount or state.escrow_amount or 0),
            success=True,
            buyer_agent_id=state.client_agent_id,
            exclude_task_id=task_id,
        )
    p8_attest = _seal_p8_attestation(state, scene_id=scene_for_auto, agent_auto=True)
    await db.flush()
    if p8_attest and hasattr(state, "arbitration_notes"):
        state.arbitration_notes = (
            f"{state.arbitration_notes or ''}; p8_attestation={p8_attest.get('attestation_id')}"
        ).strip("; ")
    return state


@router.post("/{task_id}/buyer-reject", response_model=SettlementState)
async def buyer_reject_settlement(
    task_id: str,
    body: BuyerRejectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    MVVS V1 — Buyer rejection with mandatory reason_code.

    Requires DELIVERED status. Buyer must provide a standardized RejectionReason.
    Rejection opens a dispute automatically. Free-text reason is optional supplementary.
    """
    validate_public_url_segment("task_id", task_id)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404, f"Settlement {task_id} not found")
    require_buyer(request, state)
    if canonical_task_status(state.status) != TaskStatus.DELIVERED:
        raise HTTPException(
            409,
            f"buyer reject requires delivered status, got {state.status.value}",
        )
    state.dispute_reason = (
        f"[{body.reason_code.value}] {body.reason or ''}".strip()
    )
    state.rejection_reason_code = body.reason_code.value
    await move_reserved_to_disputed(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
    )
    return await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.DISPUTED,
        reason=f"buyer rejected: {body.reason_code.value}",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )


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
    if decision == TaskStatus.SETTLED:
        await _sync_payment_intents_after_settled(db, task_id)
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
