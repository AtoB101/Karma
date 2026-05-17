"""Idempotent replay for POST /v1/trade/orders/launch."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import TradeOrderModel
from services.payment_code import build_payment_code_payload, finalize_payload_hash
from services.trade_pipeline_security import PIPELINE_VERSION


async def find_order_by_idempotency_key(
    db: AsyncSession,
    key: str,
) -> TradeOrderModel | None:
    result = await db.execute(
        select(TradeOrderModel).where(TradeOrderModel.launch_idempotency_key == key)
    )
    return result.scalar_one_or_none()


def assert_idempotent_launch_matches(
    row: TradeOrderModel,
    *,
    buyer_identity_id: str,
    seller_identity_id: str,
    requirement_fingerprint: str,
) -> None:
    stored_fp = (row.decomposed_spec or {}).get("requirement_fingerprint")
    if (
        row.buyer_identity_id != buyer_identity_id
        or row.seller_identity_id != seller_identity_id
        or (stored_fp and stored_fp != requirement_fingerprint)
    ):
        raise HTTPException(
            409,
            detail="Idempotency-Key reused with different buyer, seller, or requirement",
        )


async def build_idempotent_replay_response(
    db: AsyncSession,
    row: TradeOrderModel,
    *,
    buyer_policy_responsibility_boundary_id: str | None,
) -> dict[str, Any]:
    from db.models.orm import VoucherModel
    from services.openclaw_automation_readiness import evaluate_automation_readiness
    from services.trade_auto_execution import trace_id_from_task

    spec = row.decomposed_spec or {}
    out: dict[str, Any] = {
        "order_id": row.order_id,
        "task_id": row.task_id,
        "status": row.status,
        "voucher_id": row.voucher_id,
        "decomposed": spec,
        "idempotent_replay": True,
        "pipeline_version": row.pipeline_version or PIPELINE_VERSION,
    }
    if row.status_detail:
        out["status_detail"] = row.status_detail

    if not row.voucher_id:
        return out

    voucher = await db.get(VoucherModel, row.voucher_id)
    if voucher:
        out["payment_code"] = finalize_payload_hash(
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
                payment_mode=voucher.payment_mode or "preauth",
                chain_anchor_hash=voucher.chain_anchor_hash,
                responsibility_boundary_id=buyer_policy_responsibility_boundary_id,
            )
        )

    if row.status == "execution_started" and row.task_id:
        buyer_id = row.buyer_identity_id
        seller_id = row.seller_identity_id
        buyer_ready = await evaluate_automation_readiness(
            db, task_id=row.task_id, role="buyer", karma_identity_id=buyer_id
        )
        seller_ready = await evaluate_automation_readiness(
            db, task_id=row.task_id, role="seller", karma_identity_id=seller_id
        )
        out["readiness"] = {
            "buyer": buyer_ready.get("ready_for_task_automation"),
            "seller": seller_ready.get("ready_for_task_automation"),
            "buyer_blockers": buyer_ready.get("blockers"),
            "seller_blockers": seller_ready.get("blockers"),
        }
        out["trace_id"] = trace_id_from_task(row.task_id)

    if row.status == "rejected":
        out["reason"] = row.status_detail

    return out
