"""Server-side kickoff after order is accepted — handoff attest + initial progress."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ProgressConfirmationStatus, ProgressReceipt, TaskStatus, ToolStatus
from db.models.orm import ProgressReceiptModel, ReceiptModel, TaskContractModel
from db.stores.settlement_store import PostgresSettlementStore
from services.openclaw_handoff_attestation import confirm_handoff_attestation
from services.openclaw_webhook import emit_openclaw_event
from services.voucher_events import record_voucher_event


async def auto_confirm_handoff_both_parties(
    db: AsyncSession,
    *,
    task_id: str,
    buyer_identity_id: str,
    seller_identity_id: str,
    trace_id: str,
) -> dict[str, Any]:
    buyer = await confirm_handoff_attestation(
        db,
        task_id=task_id,
        karma_identity_id=buyer_identity_id,
        role="buyer",
        trace_id=trace_id,
        attested_by_actor="trade_pipeline",
    )
    seller = await confirm_handoff_attestation(
        db,
        task_id=task_id,
        karma_identity_id=seller_identity_id,
        role="seller",
        trace_id=trace_id,
        attested_by_actor="trade_pipeline",
    )
    return {"buyer": buyer, "seller": seller}


async def kickoff_seller_execution(
    db: AsyncSession,
    *,
    task_id: str,
    seller_identity_id: str,
    decomposed_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Record initial progress + placeholder execution receipt (pipeline agent step 0).
    """
    store = PostgresSettlementStore(db)
    settlement = await store.get(task_id)
    if not settlement:
        raise ValueError(f"settlement missing for task {task_id}")

    ts = datetime.utcnow()
    progress = ProgressReceipt(
        task_id=task_id,
        seller_identity_id=seller_identity_id,
        progress_percent=5.0,
        claimed_value_percent=0.0,
        evidence_hash=hashlib_placeholder(f"progress-start:{task_id}"),
        runtime_log_hash=hashlib_placeholder(f"runtime-start:{task_id}"),
        timestamp=ts,
        seller_signature="0xtrade_pipeline_progress",
        validation_method="trade_pipeline_v1",
        confirmation_status=ProgressConfirmationStatus.PENDING,
    )
    db.add(
        ProgressReceiptModel(
            progress_receipt_id=progress.progress_receipt_id,
            task_id=progress.task_id,
            seller_identity_id=progress.seller_identity_id,
            progress_percent=progress.progress_percent,
            claimed_value_percent=progress.claimed_value_percent,
            evidence_hash=progress.evidence_hash,
            runtime_log_hash=progress.runtime_log_hash,
            timestamp=progress.timestamp,
            seller_signature=progress.seller_signature,
            validation_method=progress.validation_method,
            confirmation_status=progress.confirmation_status.value,
        )
    )

    contract = await db.get(TaskContractModel, task_id)
    if contract:
        step0 = (decomposed_spec.get("agent_steps") or [{}])[0]
        db.add(
            ReceiptModel(
                task_id=task_id,
                agent_id=seller_identity_id,
                step_index=0,
                tool_name=f"trade_pipeline.{step0.get('action', 'start')}",
                input_hash=hashlib_placeholder(f"in:{task_id}:0"),
                output_hash=hashlib_placeholder(f"out:{task_id}:0"),
                started_at=ts,
                ended_at=ts,
                duration_ms=1,
                status=ToolStatus.SUCCESS.value,
                metadata_={"pipeline": True, "step": step0},
            )
        )

    await record_voucher_event(
        db,
        voucher_id=settlement.voucher_id or "",
        event_type="trade.execution_started",
        actor_identity_id=seller_identity_id,
        target_identity_id=settlement.client_agent_id,
        payload={
            "task_id": task_id,
            "progress_receipt_id": progress.progress_receipt_id,
            "agent_steps": decomposed_spec.get("agent_steps"),
        },
    )

    emit_openclaw_event(
        "trade.execution_started",
        {
            "task_id": task_id,
            "seller_identity_id": seller_identity_id,
            "buyer_identity_id": settlement.client_agent_id,
            "progress_percent": 5.0,
        },
        trace_id=trace_id_from_task(task_id),
    )

    await db.flush()
    return {
        "progress_receipt_id": progress.progress_receipt_id,
        "settlement_status": settlement.status.value if hasattr(settlement.status, "value") else settlement.status,
    }


def hashlib_placeholder(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def trace_id_from_task(task_id: str) -> str:
    return f"trace-order-{task_id[:12]}"
