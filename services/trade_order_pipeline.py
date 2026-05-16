"""Full preauth trade order: decompose → voucher → accept → settlement → execute."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import SettlementState, TaskContract, TaskStatus, VoucherStatus
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
from services.signing import sha256_of
from services.trade_auto_execution import (
    auto_confirm_handoff_both_parties,
    kickoff_seller_execution,
    trace_id_from_task,
)
from services.voucher_events import record_voucher_event
from services.voucher_lifecycle import accept_voucher_row, reject_voucher_row
from services.voucher_preauth import evaluate_seller_preauth


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


async def _active_runtime_key_permissions(db: AsyncSession, identity_id: str) -> list[str]:
    from sqlalchemy import select
    from db.models.orm import RuntimeKeyModel

    now = datetime.utcnow()
    result = await db.execute(
        select(RuntimeKeyModel).where(
            RuntimeKeyModel.karma_identity_id == identity_id,
            RuntimeKeyModel.status == "active",
            RuntimeKeyModel.expire_at > now,
        )
    )
    keys = list(result.scalars().all())
    return sorted({p for k in keys for p in (k.permissions or [])})


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
) -> dict[str, Any]:
    await _assert_pipeline_preauth(db, buyer_identity_id, role="buyer")
    await _assert_pipeline_preauth(db, seller_identity_id, role="seller")

    buyer_policy = await get_automation_policy(db, buyer_identity_id)
    seller_policy = await get_automation_policy(db, seller_identity_id)
    assert buyer_policy and seller_policy

    spec = decompose_buyer_requirement(
        requirement_text=requirement_text,
        seller_identity_id=seller_identity_id,
        buyer_identity_id=buyer_identity_id,
        amount=amount,
        task_precision=task_precision,
        task_type=task_type,
    )
    task_id = spec["task_id"]
    order_id = str(uuid.uuid4())
    trace_id = trace_id_from_task(task_id)

    order = TradeOrderModel(
        order_id=order_id,
        task_id=task_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        requirement_text=requirement_text,
        decomposed_spec=spec,
        status="decomposed",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(order)
    await db.flush()

    await ensure_agent_for_identity(db, buyer_identity_id, role="buyer")
    await ensure_agent_for_identity(db, seller_identity_id, role="seller")

    cap = await db.get(CapacityModel, buyer_identity_id)
    if not cap or cap.available_credits < spec["bill_credit_amount"]:
        order.status = "failed"
        order.status_detail = "insufficient buyer capacity"
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
        chain_anchor_hash=(chain_anchor_hash or "").strip() or None,
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
        payload={"task_id": task_id, "order_id": order_id, "payment_mode": "preauth"},
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
        payment_code = finalize_payload_hash(
            build_payment_code_payload(
                voucher_id=voucher.voucher_id,
                buyer_identity_id=buyer_identity_id,
                seller_identity_id=seller_identity_id,
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
        return {
            "order_id": order_id,
            "task_id": task_id,
            "status": "rejected",
            "reason": seller_eval.reason,
            "voucher_id": voucher.voucher_id,
            "payment_code": payment_code,
            "decomposed": spec,
        }

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
    state.status = TaskStatus.PENDING
    await store.save(state)
    state.worker_agent_id = seller_identity_id
    state.status = TaskStatus.ACCEPTED
    await store.save(state)
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

    buyer_ready = await evaluate_automation_readiness(
        db, task_id=task_id, role="buyer", karma_identity_id=buyer_identity_id
    )
    seller_ready = await evaluate_automation_readiness(
        db, task_id=task_id, role="seller", karma_identity_id=seller_identity_id
    )

    order.status = "execution_started"
    order.updated_at = datetime.utcnow()
    await db.flush()

    payment_code = finalize_payload_hash(
        build_payment_code_payload(
            voucher_id=voucher.voucher_id,
            buyer_identity_id=buyer_identity_id,
            seller_identity_id=seller_identity_id,
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

    emit_openclaw_event(
        "trade.order.completed",
        {
            "order_id": order_id,
            "task_id": task_id,
            "voucher_id": voucher.voucher_id,
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
        },
        trace_id=trace_id,
    )

    return {
        "order_id": order_id,
        "task_id": task_id,
        "status": order.status,
        "voucher_id": voucher.voucher_id,
        "payment_code": payment_code,
        "decomposed": spec,
        "handoff_attestations": handoffs,
        "execution": execution,
        "readiness": {
            "buyer": buyer_ready.get("ready_for_task_automation"),
            "seller": seller_ready.get("ready_for_task_automation"),
            "buyer_blockers": buyer_ready.get("blockers"),
            "seller_blockers": seller_ready.get("blockers"),
        },
    }
