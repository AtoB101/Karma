"""Payment codes — timed buyer authorization payloads (phase 1)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import AuthorizationVoucher, VoucherStatus
from db.models.orm import VoucherModel
from db.session import get_db
from services.agent_automation_policy import get_automation_policy
from services.payment_code import build_payment_code_payload, finalize_payload_hash
from services.voucher_events import record_voucher_event
from services.voucher_preauth import evaluate_buyer_preauth_for_create, evaluation_to_dict
from services.voucher_lifecycle import accept_voucher_row, reject_voucher_row
from services.openclaw_webhook import emit_openclaw_event
from api.routes.vouchers import CreateVoucherRequest, _to_schema
from services.ledger_party_access import require_ledger_identity
from services.path_param_safety import validate_public_url_segment
from services.runtime_safety import assert_runtime_operation_allowed, audit_capacity_anchor_and_maybe_trip
router = APIRouter()


class CreatePaymentCodeRequest(BaseModel):
    """Buyer creates a timed payment code (wraps voucher creation)."""

    buyer_identity_id: str
    seller_identity_id: str
    amount: float = Field(gt=0.0)
    currency: str = "USDC"
    bill_credit_amount: float = Field(gt=0.0)
    task_type: str
    task_precision: float | None = Field(default=None, ge=0.0)
    task_description_hash: str
    progress_rule_hash: str
    evidence_requirement_hash: str
    buyer_signature: str
    nonce: str | None = None
    buyer_wallet_address: str | None = None
    buyer_sub_identity_id: str | None = None
    seller_sub_identity_id: str | None = None
    progress_rule_spec: dict | None = None
    payment_mode: Literal["manual", "preauth"] = "manual"
    chain_anchor_hash: str | None = None
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400 * 7)


class SellerActionRequest(BaseModel):
    seller_identity_id: str


class RejectPaymentCodeRequest(BaseModel):
    seller_identity_id: str
    reason: str = Field(min_length=1, max_length=2000)


@router.post("", status_code=201)
async def create_payment_code(
    body: CreatePaymentCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    require_ledger_identity(request, body.buyer_identity_id)

    buyer_policy = await get_automation_policy(db, body.buyer_identity_id)
    if body.payment_mode == "preauth":
        if not buyer_policy or not buyer_policy.preauth_enabled:
            raise HTTPException(400, "buyer preauth_enabled required for payment_mode=preauth")
        buyer_eval = await evaluate_buyer_preauth_for_create(
            buyer_policy,
            seller_identity_id=body.seller_identity_id,
            amount=body.amount,
            task_type=body.task_type,
            task_precision=body.task_precision,
        )
        if not buyer_eval.accept:
            raise HTTPException(400, detail={"error": "buyer_preauth_failed", **evaluation_to_dict(buyer_eval)})

    ttl = body.ttl_seconds
    if ttl is None and buyer_policy:
        ttl = int(getattr(buyer_policy, "payment_code_ttl_seconds", 3600) or 3600)
    if ttl is None:
        ttl = 3600
    expiry = datetime.utcnow() + timedelta(seconds=ttl)
    nonce = (body.nonce or "").strip() or secrets.token_hex(16)

    desc_hash = body.task_description_hash
    if not desc_hash or desc_hash == "auto":
        desc_hash = hashlib.sha256(
            f"{body.task_type}:{body.task_precision}:{body.amount}".encode()
        ).hexdigest()

    voucher_req = CreateVoucherRequest(
        buyer_identity_id=body.buyer_identity_id,
        seller_identity_id=body.seller_identity_id,
        amount=body.amount,
        currency=body.currency,
        bill_credit_amount=body.bill_credit_amount,
        task_type=body.task_type,
        task_description_hash=desc_hash,
        progress_rule_hash=body.progress_rule_hash or hashlib.sha256(b"progress").hexdigest(),
        evidence_requirement_hash=body.evidence_requirement_hash or hashlib.sha256(b"evidence").hexdigest(),
        expiry_time=expiry,
        nonce=nonce,
        buyer_signature=body.buyer_signature,
        buyer_sub_identity_id=body.buyer_sub_identity_id,
        seller_sub_identity_id=body.seller_sub_identity_id,
        progress_rule_spec=body.progress_rule_spec,
        buyer_wallet_address=body.buyer_wallet_address,
    )

    from api.routes.vouchers import create_voucher

    voucher: AuthorizationVoucher = await create_voucher(voucher_req, request, db)

    row = await db.get(VoucherModel, voucher.voucher_id)
    if row:
        row.task_precision = body.task_precision
        row.payment_mode = body.payment_mode
        row.chain_anchor_hash = (body.chain_anchor_hash or "").strip() or None
        await db.flush()

    boundary_id = None
    if buyer_policy:
        boundary_id = getattr(buyer_policy, "responsibility_boundary_id", None)

    payload = finalize_payload_hash(
        build_payment_code_payload(
            voucher_id=voucher.voucher_id,
            buyer_identity_id=body.buyer_identity_id,
            seller_identity_id=body.seller_identity_id,
            amount=body.amount,
            bill_credit_amount=body.bill_credit_amount,
            currency=body.currency,
            task_type=body.task_type,
            task_precision=body.task_precision,
            expires_at=expiry,
            payment_mode=body.payment_mode,
            chain_anchor_hash=row.chain_anchor_hash if row else body.chain_anchor_hash,
            responsibility_boundary_id=boundary_id,
        )
    )

    await record_voucher_event(
        db,
        voucher_id=voucher.voucher_id,
        event_type="payment_code.created",
        actor_identity_id=body.buyer_identity_id,
        target_identity_id=body.seller_identity_id,
        payload={"payment_code": payload},
    )

    auto_result = None
    if row and body.payment_mode == "preauth":
        from services.voucher_preauth import evaluate_seller_preauth

        seller_eval = await evaluate_seller_preauth(db, seller_identity_id=body.seller_identity_id, voucher=row)
        if seller_eval.accept:
            await accept_voucher_row(db, row, seller_identity_id=body.seller_identity_id, actor="preauth_auto")
            auto_result = {"action": "accepted", **evaluation_to_dict(seller_eval)}
            voucher = _to_schema(row)
        else:
            await reject_voucher_row(
                db,
                row,
                seller_identity_id=body.seller_identity_id,
                reason=seller_eval.reason,
                actor=seller_eval.code,
            )
            auto_result = {"action": "rejected", **evaluation_to_dict(seller_eval)}
            voucher = _to_schema(row)

    await db.commit()
    return {
        "voucher": voucher,
        "payment_code": payload,
        "auto_result": auto_result,
    }


@router.get("/{voucher_id}")
async def get_payment_code_payload(voucher_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("voucher_id", voucher_id)
    row = await db.get(VoucherModel, voucher_id)
    if not row:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    buyer_policy = await get_automation_policy(db, row.buyer_identity_id)
    boundary_id = getattr(buyer_policy, "responsibility_boundary_id", None) if buyer_policy else None
    payload = finalize_payload_hash(
        build_payment_code_payload(
            voucher_id=row.voucher_id,
            buyer_identity_id=row.buyer_identity_id,
            seller_identity_id=row.seller_identity_id,
            amount=float(row.amount),
            bill_credit_amount=float(row.bill_credit_amount),
            currency=row.currency,
            task_type=row.task_type,
            task_precision=getattr(row, "task_precision", None),
            expires_at=row.expiry_time,
            payment_mode=getattr(row, "payment_mode", "manual") or "manual",
            chain_anchor_hash=getattr(row, "chain_anchor_hash", None),
            responsibility_boundary_id=boundary_id,
        )
    )
    return {"payment_code": payload, "voucher_status": row.status}


@router.post("/{voucher_id}/accept")
async def accept_payment_code(
    voucher_id: str,
    body: SellerActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Traditional mode — seller manually accepts after reading payment code."""
    validate_public_url_segment("voucher_id", voucher_id)
    require_ledger_identity(request, body.seller_identity_id)
    row = await db.get(VoucherModel, voucher_id)
    if not row:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    await accept_voucher_row(db, row, seller_identity_id=body.seller_identity_id, actor="console_manual")
    await db.commit()
    return _to_schema(row)


@router.post("/{voucher_id}/reject")
async def reject_payment_code(
    voucher_id: str,
    body: RejectPaymentCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("voucher_id", voucher_id)
    require_ledger_identity(request, body.seller_identity_id)
    row = await db.get(VoucherModel, voucher_id)
    if not row:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    await reject_voucher_row(db, row, seller_identity_id=body.seller_identity_id, reason=body.reason, actor="console_manual")
    await db.commit()
    return _to_schema(row)
