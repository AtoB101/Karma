"""Karma API — Settlement (public state endpoints)"""
from __future__ import annotations

import logging
import math

import structlog
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import resolve_agent_id_from_request
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
    require_party_read,
    require_worker,
)
from services.settlement_cycle_guard import assert_lock_does_not_close_payment_cycle
from services.settlement_receipt_release_guard import ensure_success_execution_receipt_before_seller_payout
from services.task_contract_guard import ensure_task_contract_exists
from services.text_safety import validate_json_strings_safe, validate_safe_storage_text_optional
from services.settlement_amounts import assert_token_precision, normalize_amount, split_amounts

router = APIRouter()

logger = logging.getLogger(__name__)


async def _sync_payment_intents_after_settled(db: AsyncSession, task_id: str) -> None:
    from services.payment_intent_service import mark_intents_settled_for_task

    await mark_intents_settled_for_task(db, task_id)


async def _release_profile_credits_if_bound(db: AsyncSession, state: Any) -> None:
    """最后一环：结算后释放档案冻结额度 + 回写档案声誉。"""
    profile_id = getattr(state, "profile_id", None)
    if not profile_id:
        return
    from services import profile_capacity

    await profile_capacity.release_profile_credits(
        db,
        profile_id=profile_id,
        settled_amount=float(state.released_amount or state.escrow_amount or 0),
        refunded_amount=float(state.refunded_amount or 0),
    )

    from db.models.orm import IdentityRoleProfile
    from services.identity_reputation import record_profile_settlement_outcome

    profile = await db.get(IdentityRoleProfile, profile_id)
    if profile is not None:
        await record_profile_settlement_outcome(
            db,
            profile_id=profile_id,
            owner_identity_id=profile.owner_identity_id,
            identity_class=profile.class_,
            success=float(state.released_amount or state.escrow_amount or 0) > 0,
            disputed=bool(getattr(state, "disputed_credits", 0) or 0),
            volume=float(state.released_amount or state.escrow_amount or 0),
        )


class CreateSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    task_id: str
    client_agent_id: str
    escrow_amount: float
    currency: str = "USD"
    voucher_id: str | None = None
    delivery_deadline_at: datetime | None = None
    profile_id: str | None = None
    # 这一单属于哪种生意（服务类型）。单笔订单状态图按它选阶段表；带了 voucher 就
    # 以 voucher 上锁定的那份为准 —— 那份是买方签过名的，不能被这次调用改掉。
    progress_rule_spec: dict | None = Field(
        default=None,
        description="Service scene spec ({scene_id: ...}). Ignored when voucher_id is set.",
    )

    @field_validator("progress_rule_spec")
    @classmethod
    def _safe_progress_spec(cls, v: dict | None) -> dict | None:
        if v is None:
            return None
        validate_json_strings_safe(v, field="progress_rule_spec")
        scene = v.get("scene_id")
        if scene is not None and (not isinstance(scene, str) or not scene.strip()):
            raise ValueError("progress_rule_spec.scene_id must be a non-empty string")
        return v


class LockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    worker_agent_id: str
    profile_id: str | None = None


class BuyerRejectRequest(BaseModel):
    """MVVS V1 — Buyer rejection with mandatory reason_code."""
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    reason_code: RejectionReason = Field(description="MVVS V1 standardized rejection code (required)")
    reason: str | None = Field(default=None, max_length=2000, description="Optional free-text detail")

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


class PartialSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    settled_value_percent: float = Field(gt=0.0, le=100.0)
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _safe_reason(cls, v: object) -> str | None:
        if v is None:
            return None
        return validate_safe_storage_text_optional(str(v), field="reason")


class RegretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
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
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
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
    progress_rule_spec = body.progress_rule_spec
    profile_id = body.profile_id
    escrow_amount = body.escrow_amount
    # 金额只允许有一个口径：链上能表示多少小数位，账上就只能有多少。
    if not math.isfinite(float(escrow_amount)):
        raise HTTPException(400, "escrow_amount must be a finite number")
    assert_token_precision(escrow_amount, field="escrow_amount")
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
        if vrow.profile_id and not profile_id:
            profile_id = vrow.profile_id

    state = SettlementState(
        task_id=body.task_id,
        escrow_amount=escrow_amount,
        currency=body.currency,
        client_agent_id=body.client_agent_id,
        profile_id=profile_id,
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
    if body.profile_id:
        validate_public_url_segment("profile_id", body.profile_id)
        from db.models.orm import IdentityRoleProfile

        profile = await db.get(IdentityRoleProfile, body.profile_id)
        if profile is None or profile.owner_identity_id != body.worker_agent_id:
            raise HTTPException(
                404, f"profile {body.profile_id} not found for worker {body.worker_agent_id}"
            )
        state.worker_profile_id = body.profile_id
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
        from services.chain import escrow_settlement
        from services.chain.settlement_adapter import settlement_router

        # 托管通道（allowance escrow）在 _apply_transition 里已经**同步**把链上 bind 做完了，
        # 这里再投一次 Celery 就是两条路各绑一次 —— 同一笔钱会在两个托管合约里各锁一份。
        # 只有托管通道没开、走老的 KarmaBilateral 异步路时，才轮到下面这段。
        if settlement_router.is_onchain() and not escrow_settlement.enabled():
            from worker.tasks import lock_and_bind_onchain

            # 真上链绑定是异步做的（实测 20–30s），同步响应里给不出 onchain_binding_id。
            # 以前这里直接返回一个 null，调用方分不清「正在绑」和「压根没绑」。
            # 现在先把 onchain_status 置成 pending_bind 再投递，调用方据此轮询
            # GET /v1/settlement/{task_id}，直到变成 bound（成功）或 failed（失败）。
            # reconcile_onchain_status 这个 beat 任务会拿链上真相覆盖这一列。
            new_state.onchain_status = "pending_bind"
            await store.save(new_state)
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
    # MVVS V1 — 交付即开始算买方的确认窗口。窗口写进结算单（confirm_window_hours +
    # confirm_deadline_at），到期还没人表态就由 POST /auto-confirm 兜底放款。
    # 不写这两个字段的话，买方不表态的单子没有任何出口：既不能取消，唯一的超时兜底
    # 又永远 409，钱会一直卡在托管里（F6 报告第 9 条）。
    window_hours = int(getattr(settings, "settlement_confirm_window_hours", 0) or 0)
    if window_hours > 0:
        state.confirm_window_hours = window_hours
        state.confirm_deadline_at = datetime.utcnow() + timedelta(hours=window_hours)
    else:
        state.confirm_window_hours = None
        state.confirm_deadline_at = None
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
    out = await _apply_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.CANCELLED,
        reason="task failed and cancelled",
        route_path=str(request.url.path),
        actor_id=_resolve_actor_id(request),
    )
    # 取消也要把账上的可用额度还回去（F10-1）：授权码占住的 reserved 只在「结算完成」
    # 或「授权码过期」时才释放，取消订单两条都不走 —— 买方会看着自己的额度被冻 7 天，
    # 而链上明明还有钱。托管没启用时同样要还，所以放在这一层，不挂在链上那一步。
    from services.settlement_voucher import cancel_voucher_reservation_for_task

    await cancel_voucher_reservation_for_task(db, task_id)
    return out


@router.get("/{task_id}", response_model=SettlementState)
async def get_settlement(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """读结算状态。

    P1-7：与合同／流转同口径 —— 结算里有金额、对手方与仲裁结果，此前任何身份
    都能读。现在默认只有当事人（买/卖）或平台运维岗能读；
    ``TASK_RECORDS_PUBLIC_READ=true`` 可恢复公开（产品决策开关）。
    """
    validate_public_url_segment("task_id", task_id)
    store = PostgresSettlementStore(db)
    state = await store.get(task_id)
    if not state:
        raise HTTPException(404)
    parties = {state.client_agent_id}
    if state.worker_agent_id:
        parties.add(state.worker_agent_id)
    await require_party_read(
        db,
        request,
        {p for p in parties if p},
        public_read=bool(settings.task_records_public_read),
    )
    from services.chain import escrow_settlement

    if escrow_settlement.enabled():
        try:
            if await escrow_settlement.reconcile_task(db, task_id=task_id):
                state = await store.get(task_id) or state
        except Exception:  # 对账是读的附加动作，坏了也不能让读状态失败
            logger.warning("escrow_settlement_reconcile_failed", exc_info=True)
    return state


@router.get("/{task_id}/transitions", response_model=list[SettlementTransitionAudit])
async def list_settlement_transitions(
    task_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """读结算流转审计。

    P1-7：此前任何身份都能读别人的流转记录（含争议理由、金额）。现在默认只有
    当事人（买/卖）或平台运维岗能读；``TASK_RECORDS_PUBLIC_READ=true`` 可公开。
    """
    validate_public_url_segment("task_id", task_id)
    state = await PostgresSettlementStore(db).get(task_id)
    if state is None:
        raise HTTPException(404, f"Settlement {task_id} not found")
    parties = {state.client_agent_id}
    if state.worker_agent_id:
        parties.add(state.worker_agent_id)
    await require_party_read(
        db,
        request,
        {p for p in parties if p},
        public_read=bool(settings.task_records_public_read),
    )
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
    settled_amount, refunded_amount = split_amounts(
        state.escrow_amount, body.settled_value_percent
    )

    # 幂等重放（2026-09-20 实测新增）。背景：/partial 是一条「撤绑 → 重绑 → 划款」
    # 的同步长事务，实测要 40s 以上，客户端很容易先超时。超时后客户端重试时，服务端
    # 其实**已经执行完了**，但旧代码会甩一句 400 "requires delivered status"（因为状态
    # 已经变成 settled），调用方既判断不出到底成没成，文案还指错了方向。
    # 现在：同一个比例直接回 200 + 当前状态（答案就是「成了」）；比例不同回 409 并
    # 明确告诉这一单已经按什么比例结完了。终局单同理，不再用中间态的文案糊弄。
    if st == TaskStatus.SETTLED:
        done_amount = round(float(state.released_amount or 0.0), 2)
        done_refund = round(float(state.refunded_amount or 0.0), 2)
        if abs(done_amount - settled_amount) <= 0.01:
            return state
        raise HTTPException(
            409,
            {
                "error": "already_settled",
                "detail": (
                    "this settlement is already settled and cannot be re-split; "
                    f"released={done_amount} refunded={done_refund}"
                ),
                "released_amount": done_amount,
                "refunded_amount": done_refund,
            },
        )
    if st in {TaskStatus.CANCELLED, TaskStatus.REFUNDED}:
        raise HTTPException(
            409,
            {
                "error": "settlement_not_open_for_partial",
                "detail": (
                    f"settlement is {st.value}; "
                    "partial settlement is not applicable to a finalized settlement"
                ),
            },
        )

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
                f"(POST /v1/settlement/{{task_id}}/submit first); this settlement is {st.value}. "
                "Either submit the delivery first, or confirm progress receipts up to the intended split.",
            )

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
        # 买方本人点的放款：链上打 buyerConfirm，划款不等争议窗口（v4）。
        buyer_confirmed=True,
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
    settled_amount, refunded_amount = split_amounts(state.escrow_amount, confirmed_percent)

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
        # 买方本人点的放款：链上打 buyerConfirm，划款不等争议窗口（v4）。
        buyer_confirmed=True,
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
                try:
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
                except ConfirmationPolicyError as session_exc:
                    # 场景没登记 / 策略读不到：这是「你调错了」而不是「服务器坏了」。
                    # 之前这条会一路冒到 ASGI，用户看到 500，完全不知道差在哪。
                    logger.warning(
                        "settle_confirmation_session_failed",
                        extra={"task_id": task_id, "scene_id": settle_scene, "detail": str(session_exc)},
                    )
                    raise HTTPException(
                        409,
                        f"这一单需要主人确认，但确认场景 {settle_scene!r} 没有登记：{session_exc}",
                    ) from session_exc
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

    state.released_amount = normalize_amount(state.escrow_amount)
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
        # 买方本人点的放款：链上打 buyerConfirm，划款不等争议窗口（v4）。
        buyer_confirmed=True,
    )
    await apply_capacity_resolution(
        db=db,
        buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount,
        settled_amount=state.escrow_amount,
        refunded_amount=0.0,
    )
    await _release_profile_credits_if_bound(db, state)
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
    # 授权先于状态：没资格的人不该靠 409 文案推算出这笔单子的交付时间。
    require_buyer_or_worker(request, state)
    if canonical_task_status(state.status) != TaskStatus.DELIVERED:
        raise HTTPException(409, f"auto-confirm requires delivered, got {state.status.value}")
    if state.confirm_window_hours is None:
        raise HTTPException(
            409,
            "this settlement has no confirm window (confirm_window_hours is null); "
            "the buyer has to accept or reject it explicitly",
        )
    now = datetime.utcnow()
    if state.confirm_deadline_at is None and state.updated_at:
        # 老单兜底：交付时还没写 deadline 的行，用 updated_at 现算一次。
        state.confirm_deadline_at = state.updated_at + timedelta(hours=state.confirm_window_hours)
    if state.confirm_deadline_at and now < state.confirm_deadline_at:
        remaining = (state.confirm_deadline_at - now).total_seconds() / 3600
        raise HTTPException(409, f"confirm window not expired — {remaining:.1f}h remaining")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    return await _auto_confirm_release(
        db,
        store=store,
        state=state,
        now=now,
        actor_id=_resolve_actor_id(request),
        route_path=str(request.url.path),
    )


# 后台兜底放款的操作者标识。链上 finalizeSettlement 是 permissionless 的，账上也得
# 有个说得清的 actor：推这一下的不是买卖任何一方按的按钮，是「交付 + 验证通过 +
# 买方沉默到期」这条规则本身。
AUTO_CONFIRM_ACTOR_ID = "system:auto-confirm"
# 这两类场景走的是 OWNER_CONFIRM：主人没点头，任何超时都不许替他把钱付出去。
AUTO_CONFIRM_FORBIDDEN_SCENES = frozenset({"financial_services", "healthcare_medical"})

#: 兜底放款自己的日志出口。这个路由模块用的是 stdlib logging，而进程只把 structlog
#: 接进了日志管道 —— stdlib 的 INFO 打不出来。被按住不放的那一单必须看得见，
#: 否则「钱为什么没到卖方」在生产里查无此据。
_autoconfirm_log = structlog.get_logger("karma.settlement_auto_confirm")
#: 同一单被同一句话按住时只报一次：一轮 15 秒，重复刷会把真正的问题淹掉。
_held_reasons: dict[str, str] = {}


async def _auto_confirm_release(
    db: AsyncSession,
    *,
    store: PostgresSettlementStore,
    state: SettlementState,
    now: datetime,
    actor_id: str | None,
    route_path: str = "/v1/settlement/{task_id}/auto-confirm",
) -> SettlementState:
    """买方沉默到期的唯一出口：DELIVERED -> AUTO_CONFIRMED -> SETTLED，钱划给卖方。

    规则（MVVS V1，买卖双方对表用同一份）：
      * 买方确认 + 验证通过   -> 立即放行，不开窗口（走 buyer-accept，不经过这里）；
      * 买方没确认            -> 交付时写入的 confirm_window_hours / confirm_deadline_at；
      * 窗口到期 + 验证层通过  -> 自动放行（这个函数）；
      * 验证层没过 / 高风险场景 -> 409，钱一步都不许动。

    HTTP 路由和后台兜底（``auto_confirm_expired_settlements``）共用这一份，
    免得两条路各写一套、只有能被手点的那条是对的。
    """
    task_id = state.task_id
    assert_runtime_operation_allowed("new_settlement")
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
    if not auto_dec.get("allowed") and scene_for_auto in AUTO_CONFIRM_FORBIDDEN_SCENES:
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
        route_path=route_path, actor_id=actor_id)
    state.released_amount = normalize_amount(state.escrow_amount)
    state.refunded_amount = 0.0
    state.released_at = now
    state = await _apply_transition(db=db, store=store, state=state,
        target_status=TaskStatus.SETTLED,
        reason="auto-confirmed → settled",
        route_path=route_path, actor_id=actor_id)
    await apply_capacity_resolution(db=db, buyer_identity_id=state.client_agent_id,
        escrow_amount=state.escrow_amount, settled_amount=state.escrow_amount, refunded_amount=0.0)
    await _release_profile_credits_if_bound(db, state)
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


def auto_confirm_deadline(state: SettlementState) -> datetime | None:
    """这一单的买方确认截止时间；None = 这一单没有窗口，只能由人显式表态。"""
    hours = int(state.confirm_window_hours or 0)
    if hours <= 0:
        return None
    if state.confirm_deadline_at is not None:
        return state.confirm_deadline_at
    if state.updated_at is None:
        return None
    # 老单兜底：交付时还没写 deadline 的行，用 updated_at 现算一次（和路由里同一口径）。
    return state.updated_at + timedelta(hours=hours)


async def auto_confirm_expired_settlements(
    db: AsyncSession,
    *,
    limit: int | None = None,
    now: datetime | None = None,
) -> list[str]:
    """后台兜底：交付后买方沉默超过确认窗口、且验证层已经通过的单子，自动放行。

    没有它，``POST /auto-confirm`` 就只是一扇没人敲的门：买方不表态，钱永远卡在
    托管里，卖方也拿不到本该拿到的款。这里只负责「到期 + 验证通过」这一条，
    验证层没过的会被 ``_auto_confirm_release`` 挡下（409），原样留给争议/仲裁那条路。
    """
    store = PostgresSettlementStore(db)
    current = now or datetime.utcnow()
    confirmed: list[str] = []
    for state in await store.list_by_status(TaskStatus.DELIVERED):
        if limit is not None and len(confirmed) >= limit:
            break
        deadline = auto_confirm_deadline(state)
        if deadline is None or current < deadline:
            continue
        try:
            # 一单一个 savepoint：这单在链上/账上走到一半炸了，回滚的是这单，
            # 不会把同一轮里其他单子已经写好的东西一起带走。
            async with db.begin_nested():
                await _auto_confirm_release(
                    db,
                    store=store,
                    state=state,
                    now=current,
                    actor_id=AUTO_CONFIRM_ACTOR_ID,
                    route_path="/internal/auto-confirm",
                )
        except HTTPException as exc:
            # 验证层没通过（没有成功回执 / 交付验证没过）/ 高风险场景不许兜底：
            # 钱不动，下一轮再看 —— 但要让运维看见是谁把它按住了。
            reason = f"{exc.status_code}:{str(exc.detail)[:200]}"
            if _held_reasons.get(state.task_id) != reason:
                _held_reasons[state.task_id] = reason
                _autoconfirm_log.warning(
                    "settlement_auto_confirm_held",
                    task_id=state.task_id,
                    status=exc.status_code,
                    detail=str(exc.detail)[:300],
                )
            continue
        except Exception as exc:  # noqa: BLE001 - 一单卡住不许拖住其他单
            _autoconfirm_log.warning(
                "settlement_auto_confirm_failed",
                task_id=state.task_id,
                error=str(exc),
            )
            continue
        _held_reasons.pop(state.task_id, None)
        confirmed.append(state.task_id)
        _autoconfirm_log.info(
            "settlement_auto_confirmed",
            task_id=state.task_id,
            window_hours=int(state.confirm_window_hours or 0),
            actor_id=AUTO_CONFIRM_ACTOR_ID,
        )
    return confirmed


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
    # Runtime-Gateway-delegated calls carry their verified actor on request.state.
    return resolve_agent_id_from_request(request)


async def _sync_escrow_settlement(
    *,
    db: AsyncSession,
    state: SettlementState,
    target_status: TaskStatus,
    buyer_confirmed: bool = False,
) -> None:
    """把状态机的两个关键点接到链上（详见 services/chain/escrow_settlement.py）。

    接单（→ ACCEPTED）  ：买方承诺 + 卖方质押在链上 bind 成一个 binding。
    结算（→ SETTLED）   ：提交结算、打开挑战期，钱由 autosettle 从买方钱包直划卖方。
    全额退款（REFUNDED）：卖方违约 → 罚没质押划给买方（submit 开窗 + autosettle 到点罚没）。
    取消（CANCELLED）   ：撤销 binding，把买方被占住的授权放回去，钱一步没动。

    链上没落定，业务状态就不许往前走 —— 这一层存在的意义就是让「已结算」在链上
    有对应的钱，而不是数据库里的一个数字。托管未启用时整段是空操作。

    ``buyer_confirmed`` 只有买方本人表态的那几条路会传 True（验收 / 部分结算 /
    买方让步结算）：验证已经过了、买方也点了头，链上就打一笔 ``buyerConfirm``，
    划款不必再等争议窗口（v4）。
    """
    from services.chain import escrow_settlement

    if not escrow_settlement.enabled():
        return
    status = canonical_task_status(target_status)
    try:
        if status == TaskStatus.ACCEPTED:
            await escrow_settlement.bind_for_task(
                db,
                task_id=state.task_id,
                buyer_identity_id=state.client_agent_id,
                seller_identity_id=state.worker_agent_id,
                amount_usdc=float(state.escrow_amount or 0.0),
            )
        elif status == TaskStatus.SETTLED:
            await escrow_settlement.submit_for_task(
                db,
                task_id=state.task_id,
                released_amount=state.released_amount,
                buyer_confirmed=buyer_confirmed,
            )
        elif status == TaskStatus.REFUNDED:
            # 全额退款 = 这次交付被裁定为一文不值 = 卖方违约：质押划给买方。
            await escrow_settlement.slash_for_task(db, task_id=state.task_id)
        elif status == TaskStatus.CANCELLED:
            await escrow_settlement.cancel_for_task(db, task_id=state.task_id)
    except escrow_settlement.EscrowSettlementError as exc:
        logger.warning(
            "escrow_settlement_gate_blocked",
            extra={"task_id": state.task_id, "target": status.value, "detail": exc.message},
        )
        raise HTTPException(exc.status, exc.message) from exc


async def _apply_transition(
    *,
    db: AsyncSession,
    store: PostgresSettlementStore,
    state: SettlementState,
    target_status: TaskStatus,
    reason: str,
    route_path: str,
    actor_id: str | None,
    buyer_confirmed: bool = False,
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
    await _sync_escrow_settlement(
        db=db, state=state, target_status=target_status, buyer_confirmed=buyer_confirmed
    )
    # 上面那句链上调用是**同步**的：钱在链上动了，真相由 escrow_settlement 写回数据库行
    # （onchain_status / onchain_binding_id / tx_hash）。但它改的是 ORM 行，不是手里这个
    # pydantic 对象 —— 直接把 state 返回出去，操作台刚接完单就会看到 onchain_status=null，
    # 数据库里明明写着 bound。重读一次，让响应说的是链上事实。
    refreshed = await store.get(state.task_id)
    return refreshed or state


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
