"""Server-side kickoff after order is accepted — handoff attest + initial progress."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ProgressConfirmationStatus, ProgressReceipt, TaskStatus, ToolStatus
from db.models.orm import ProgressReceiptModel, ReceiptModel, TaskContractModel
from db.stores.settlement_store import PostgresSettlementStore
from services.openclaw_handoff_attestation import confirm_handoff_attestation
from services.signing import signing_service
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
        # 以前这里写死一个假签名 "0xtrade_pipeline_progress"：开发环境靠占位白名单
        # 糊过去，生产环境一旦真验签就露馅。现在由服务端按规范载荷真签一次。
        seller_signature="",
        validation_method="trade_pipeline_v1",
        confirmation_status=ProgressConfirmationStatus.PENDING,
    )
    progress = progress.model_copy(
        update={"seller_signature": signing_service.sign_progress(progress)}
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
        # 回执的 step_index 是 **1 基**的：core/schemas.py::ExecutionReceipt 写死
        # ``Field(ge=1)``，收据路由也要求「这一单的第一条必须是 1」。这里以前写 0 ——
        # 等于往库里塞一条**读都读不出来**的行：PostgresReceiptStore._from_row 会把
        # 它喂给 pydantic，当场 ValidationError（input_value=0），于是任何
        # list_by_task / get_latest_by_task 都炸成裸 500。放款那几道闸
        # （收付前的成功回执校验、auto-confirm 的 preflight）都读这张表，
        # 所以这一条脏行会把**卖方收钱那条路整条打挂**（2026-10-14 testnet 实测：
        # POST /v1/settlement/{task}/buyer-accept → 500）。
        # 取「这一单现有最大 step_index + 1」，没有就 1：既守住 1 基，
        # 也不会跟卖家已经提交过的真回执撞 uq_task_step(task_id, step_index)。
        latest_step = (
            await db.execute(
                select(ReceiptModel.step_index)
                .where(ReceiptModel.task_id == task_id)
                .order_by(ReceiptModel.step_index.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        db.add(
            ReceiptModel(
                task_id=task_id,
                agent_id=seller_identity_id,
                step_index=int(latest_step or 0) + 1,
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
