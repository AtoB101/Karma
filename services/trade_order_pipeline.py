"""Full preauth trade order: decompose → voucher → accept → settlement → execute."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import SettlementState, TaskContract, TaskStatus, VoucherStatus
from core.settlement.engine import canonical_task_status
from db.models.orm import (
    CapacityModel,
    TaskContractModel,
    TradeOrderModel,
    VoucherModel,
)
from db.stores.settlement_store import PostgresSettlementStore
from services.agent_automation_policy import get_automation_policy
from services.identity_agents import ensure_agent_for_identity
from services.openclaw_automation_readiness import evaluate_automation_readiness
from services.openclaw_webhook import emit_openclaw_event
from services.payment_code import build_payment_code_payload, finalize_payload_hash
from services.requirement_decomposer import decompose_buyer_requirement
from services.settlement_cycle_guard import assert_lock_does_not_close_payment_cycle
from services.spending_policy import assert_pre_launch_spending_policy
from services.trade_launch_signing import assert_buyer_signature_for_launch
from services.settlement_transitions import (
    PIPELINE_ACTOR_ID,
    PIPELINE_ROUTE_PATH,
    apply_settlement_transition,
)
from services.signing import sha256_of
from services.trade_auto_execution import (
    auto_confirm_handoff_both_parties,
    kickoff_seller_execution,
    trace_id_from_task,
)
from services.trade_order_idempotency import (
    assert_idempotent_launch_matches,
    build_idempotent_replay_response,
    find_order_by_idempotency_key,
)
from services.trade_pipeline_security import (
    PIPELINE_VERSION,
    clamp_spec_to_policies,
    requirement_fingerprint,
    validate_chain_anchor_for_mode,
    validate_launch_parties,
    validate_requirement_text,
)
from services.voucher_events import record_voucher_event
from services.voucher_lifecycle import accept_voucher_row, reject_voucher_row
from services.voucher_preauth import evaluate_seller_preauth

logger = logging.getLogger(__name__)


async def _assert_pipeline_preauth(db: AsyncSession, identity_id: str, *, role: str) -> None:
    policy = await get_automation_policy(db, identity_id)
    if not policy or not policy.preauth_enabled:
        raise HTTPException(400, detail=f"{role} preauth_enabled required on automation-policy")
    if not policy.responsibility_acknowledged:
        raise HTTPException(400, detail=f"{role} must acknowledge responsibility boundary")
    if not policy.auto_enabled:
        raise HTTPException(400, detail=f"{role} auto_enabled required for auto-execute pipeline")
    if not getattr(policy, "auto_execute_pipeline", False):
        raise HTTPException(
            400,
            detail=f"{role} auto_execute_pipeline must be true (enable in trade preauth save)",
        )
    now = datetime.utcnow()
    from sqlalchemy import select
    from db.models.orm import RuntimeKeyModel

    result = await db.execute(
        select(RuntimeKeyModel).where(
            RuntimeKeyModel.karma_identity_id == identity_id,
            RuntimeKeyModel.status == "active",
            RuntimeKeyModel.expire_at > now,
        )
    )
    if not result.scalars().first():
        raise HTTPException(
            400,
            detail=f"{role} needs active Runtime Key before launch (Settings → 铸造 Runtime Key)",
        )


async def _mark_order_failed(order: TradeOrderModel, detail: str) -> None:
    order.status = "failed"
    order.status_detail = detail[:2000]
    order.updated_at = datetime.utcnow()


async def launch_preauth_trade_order(
    db: AsyncSession,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_text: str,
    buyer_signature: str,
    amount: float | None = None,
    task_precision: float | None = None,
    task_type: str | None = None,
    chain_anchor_hash: str | None = None,
    launch_idempotency_key: str | None = None,
) -> dict[str, Any]:
    validate_launch_parties(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
    )
    cleaned_requirement = validate_requirement_text(requirement_text)
    chain_anchor_hash = validate_chain_anchor_for_mode(chain_anchor_hash)

    fp = requirement_fingerprint(
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=cleaned_requirement,
        amount=amount,
        task_type=task_type,
    )

    if launch_idempotency_key:
        existing = await find_order_by_idempotency_key(db, launch_idempotency_key)
        if existing:
            assert_idempotent_launch_matches(
                existing,
                buyer_identity_id=buyer_identity_id,
                seller_identity_id=seller_identity_id,
                requirement_fingerprint=fp,
            )
            buyer_policy = await get_automation_policy(db, buyer_identity_id)
            boundary = buyer_policy.responsibility_boundary_id if buyer_policy else None
            logger.info(
                "trade launch idempotent replay order_id=%s key=%s",
                existing.order_id,
                launch_idempotency_key[:16],
            )
            return await build_idempotent_replay_response(
                db,
                existing,
                buyer_policy_responsibility_boundary_id=boundary,
            )

    await _assert_pipeline_preauth(db, buyer_identity_id, role="buyer")
    await _assert_pipeline_preauth(db, seller_identity_id, role="seller")

    buyer_policy = await get_automation_policy(db, buyer_identity_id)
    seller_policy = await get_automation_policy(db, seller_identity_id)
    assert buyer_policy and seller_policy

    spec = decompose_buyer_requirement(
        requirement_text=cleaned_requirement,
        seller_identity_id=seller_identity_id,
        buyer_identity_id=buyer_identity_id,
        amount=amount,
        task_precision=task_precision,
        task_type=task_type,
    )
    spec["requirement_fingerprint"] = fp
    spec = clamp_spec_to_policies(
        spec,
        buyer_policy=buyer_policy,
        seller_policy=seller_policy,
    )

    await assert_pre_launch_spending_policy(
        db,
        buyer_policy=buyer_policy,
        additional_amount=float(spec["amount"]),
    )
    await assert_buyer_signature_for_launch(
        db,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=cleaned_requirement,
        amount=float(spec["amount"]),
        task_type=str(spec["task_type"]),
        task_precision=float(spec["task_precision"]),
        buyer_signature=buyer_signature,
        launch_idempotency_key=launch_idempotency_key,
        chain_anchor_hash=chain_anchor_hash,
    )

    task_id = spec["task_id"]
    order_id = str(uuid.uuid4())
    trace_id = trace_id_from_task(task_id)

    order = TradeOrderModel(
        order_id=order_id,
        task_id=task_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=cleaned_requirement,
        decomposed_spec=spec,
        status="decomposed",
        launch_idempotency_key=launch_idempotency_key,
        pipeline_version=PIPELINE_VERSION,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(order)
    await db.flush()

    try:
        return await _execute_pipeline_body(
            db,
            order=order,
            spec=spec,
            buyer_identity_id=buyer_identity_id,
            seller_identity_id=seller_identity_id,
            buyer_policy=buyer_policy,
            buyer_signature=buyer_signature,
            chain_anchor_hash=chain_anchor_hash,
            trace_id=trace_id,
        )
    except HTTPException:
        if order.status not in ("rejected", "execution_started", "failed"):
            await _mark_order_failed(order, "pipeline aborted")
            await db.flush()
        raise
    except Exception as exc:
        await _mark_order_failed(order, str(exc))
        await db.flush()
        logger.exception("trade pipeline failed order_id=%s", order_id)
        raise


async def _execute_pipeline_body(
    db: AsyncSession,
    *,
    order: TradeOrderModel,
    spec: dict[str, Any],
    buyer_identity_id: str,
    seller_identity_id: str,
    buyer_policy: Any,
    buyer_signature: str,
    chain_anchor_hash: str | None,
    trace_id: str,
) -> dict[str, Any]:
    task_id = spec["task_id"]
    order_id = order.order_id

    await ensure_agent_for_identity(db, buyer_identity_id, role="buyer")
    await ensure_agent_for_identity(db, seller_identity_id, role="seller")

    cap = await db.get(CapacityModel, buyer_identity_id)
    if not cap or cap.available_credits < spec["bill_credit_amount"]:
        await _mark_order_failed(order, "insufficient buyer capacity")
        raise HTTPException(409, "insufficient buyer available credits")

    deadline = datetime.utcnow() + timedelta(days=7)
    contract = TaskContract(
        task_id=task_id,
        client_agent_id=buyer_identity_id,
        title=spec["title"],
        description=spec["description"],
        expected_output_schema=spec["expected_output_schema"],
        expected_step_count=spec["expected_step_count"],
        escrow_amount=spec["amount"],
        currency="USD",
        deadline_at=deadline,
    )
    contract.contract_hash = sha256_of(contract.model_dump(exclude={"contract_hash"}))
    db.add(
        TaskContractModel(
            task_id=contract.task_id,
            client_agent_id=contract.client_agent_id,
            worker_agent_id=seller_identity_id,
            title=contract.title,
            description=contract.description,
            expected_output_schema=contract.expected_output_schema,
            expected_step_count=contract.expected_step_count,
            escrow_amount=contract.escrow_amount,
            currency=contract.currency,
            deadline_at=contract.deadline_at,
            contract_hash=contract.contract_hash,
        )
    )
    order.status = "contract_created"
    await db.flush()

    ttl = int(buyer_policy.payment_code_ttl_seconds or 3600)
    expiry = datetime.utcnow() + timedelta(seconds=ttl)
    nonce = secrets.token_hex(16)
    progress_spec = {
        "trade_order_id": order_id,
        "agent_steps": spec["agent_steps"],
        "decomposition_version": spec["decomposition_version"],
        "pipeline_version": PIPELINE_VERSION,
    }

    voucher = VoucherModel(
        voucher_id=str(uuid.uuid4()),
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        amount=spec["amount"],
        currency=spec["currency"],
        bill_credit_amount=spec["bill_credit_amount"],
        task_type=spec["task_type"],
        task_description_hash=spec["requirement_hash"],
        progress_rule_hash=sha256_of(progress_spec),
        evidence_requirement_hash=sha256_of({"task_id": task_id}),
        expiry_time=expiry,
        nonce=nonce,
        buyer_signature=buyer_signature,
        status=VoucherStatus.CREATED.value,
        task_precision=spec["task_precision"],
        payment_mode="preauth",
        chain_anchor_hash=chain_anchor_hash,
        task_id=task_id,
        progress_rule_spec=progress_spec,
    )
    db.add(voucher)
    await db.flush()
    order.voucher_id = voucher.voucher_id
    order.status = "voucher_created"

    await record_voucher_event(
        db,
        voucher_id=voucher.voucher_id,
        event_type="voucher.created",
        actor_identity_id=buyer_identity_id,
        target_identity_id=seller_identity_id,
        payload={
            "task_id": task_id,
            "order_id": order_id,
            "payment_mode": "preauth",
            "pipeline_version": PIPELINE_VERSION,
        },
    )
    emit_openclaw_event(
        "voucher.created",
        {
            "voucher_id": voucher.voucher_id,
            "task_id": task_id,
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "order_id": order_id,
        },
        trace_id=trace_id,
    )

    seller_eval = await evaluate_seller_preauth(db, seller_identity_id=seller_identity_id, voucher=voucher)
    if seller_eval.accept:
        await accept_voucher_row(db, voucher, seller_identity_id=seller_identity_id, actor="preauth_pipeline")
        order.status = "accepted"
    else:
        await reject_voucher_row(
            db,
            voucher,
            seller_identity_id=seller_identity_id,
            reason=seller_eval.reason,
            actor=seller_eval.code,
        )
        order.status = "rejected"
        order.status_detail = seller_eval.reason
        await db.flush()
        return _build_terminal_response(
            order=order,
            spec=spec,
            voucher=voucher,
            buyer_policy=buyer_policy,
            status="rejected",
            reason=seller_eval.reason,
        )

    state = SettlementState(
        task_id=task_id,
        escrow_amount=spec["bill_credit_amount"],
        currency="USD",
        client_agent_id=buyer_identity_id,
        status=TaskStatus.DRAFT,
        settlement_mode=settings.settlement_mode,
        voucher_id=voucher.voucher_id,
        progress_rule_spec=progress_spec,
    )
    store = PostgresSettlementStore(db)
    await store.save(state)
    order.status = "settlement_created"

    state = await store.get(task_id)
    assert state

    await assert_lock_does_not_close_payment_cycle(
        db,
        task_id=task_id,
        buyer_id=buyer_identity_id,
        worker_id=seller_identity_id,
    )

    if canonical_task_status(state.status) == TaskStatus.DRAFT:
        state = await apply_settlement_transition(
            db=db,
            store=store,
            state=state,
            target_status=TaskStatus.PENDING,
            reason="trade pipeline: pending before lock",
        )

    state.worker_agent_id = seller_identity_id
    state = await apply_settlement_transition(
        db=db,
        store=store,
        state=state,
        target_status=TaskStatus.ACCEPTED,
        reason="trade pipeline: worker locked",
    )
    order.status = "settlement_locked"

    handoffs = await auto_confirm_handoff_both_parties(
        db,
        task_id=task_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        trace_id=trace_id,
    )
    order.status = "handoff_confirmed"

    execution = await kickoff_seller_execution(
        db,
        task_id=task_id,
        seller_identity_id=seller_identity_id,
        decomposed_spec=spec,
    )

    state = await store.get(task_id)
    if state and canonical_task_status(state.status) == TaskStatus.ACCEPTED:
        state = await apply_settlement_transition(
            db=db,
            store=store,
            state=state,
            target_status=TaskStatus.IN_PROGRESS,
            reason="trade pipeline: execution kickoff",
            route_path=PIPELINE_ROUTE_PATH,
            actor_id=PIPELINE_ACTOR_ID,
        )

    buyer_ready = await evaluate_automation_readiness(
        db, task_id=task_id, role="buyer", karma_identity_id=buyer_identity_id
    )
    seller_ready = await evaluate_automation_readiness(
        db, task_id=task_id, role="seller", karma_identity_id=seller_identity_id
    )

    order.status = "execution_started"
    order.updated_at = datetime.utcnow()
    await db.flush()

    emit_openclaw_event(
        "trade.order.completed",
        {
            "order_id": order_id,
            "task_id": task_id,
            "voucher_id": voucher.voucher_id,
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "pipeline_version": PIPELINE_VERSION,
        },
        trace_id=trace_id,
    )

    body = _build_terminal_response(
        order=order,
        spec=spec,
        voucher=voucher,
        buyer_policy=buyer_policy,
        status=order.status,
    )
    body["handoff_attestations"] = handoffs
    body["execution"] = execution
    body["readiness"] = {
        "buyer": buyer_ready.get("ready_for_task_automation"),
        "seller": seller_ready.get("ready_for_task_automation"),
        "buyer_blockers": buyer_ready.get("blockers"),
        "seller_blockers": seller_ready.get("blockers"),
    }
    body["pipeline_version"] = PIPELINE_VERSION
    body["trace_id"] = trace_id
    return body


def _build_terminal_response(
    *,
    order: TradeOrderModel,
    spec: dict[str, Any],
    voucher: VoucherModel,
    buyer_policy: Any,
    status: str,
    reason: str | None = None,
) -> dict[str, Any]:
    payment_code = finalize_payload_hash(
        build_payment_code_payload(
            voucher_id=voucher.voucher_id,
            buyer_identity_id=voucher.buyer_identity_id,
            seller_identity_id=voucher.seller_identity_id,
            amount=float(voucher.amount),
            bill_credit_amount=float(voucher.bill_credit_amount),
            currency=voucher.currency,
            task_type=voucher.task_type,
            task_precision=voucher.task_precision,
            expires_at=voucher.expiry_time,
            payment_mode="preauth",
            chain_anchor_hash=voucher.chain_anchor_hash,
            responsibility_boundary_id=buyer_policy.responsibility_boundary_id,
        )
    )
    out: dict[str, Any] = {
        "order_id": order.order_id,
        "task_id": order.task_id,
        "status": status,
        "voucher_id": voucher.voucher_id,
        "payment_code": payment_code,
        "decomposed": spec,
        "pipeline_version": PIPELINE_VERSION,
    }
    if reason:
        out["reason"] = reason
    return out
