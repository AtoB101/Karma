"""Karma API — Authorization vouchers."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, model_validator
from sqlalchemy.exc import IntegrityError

from core.schemas import (
    AuthorizationVoucher,
    CapacityState,
    SubIdentityStatus,
    VoucherStatus,
    VoucherVerificationResult,
)
from db.models.orm import CapacityModel, SubIdentityModel, VoucherModel
from db.session import get_db
from services.capacity_ledger import assert_capacity_invariants
from services.runtime_safety import (
    assert_runtime_operation_allowed,
    audit_capacity_anchor_and_maybe_trip,
)
from services.voucher_buyer_commitment import assert_buyer_commitment_for_voucher
from config.settings import settings
from services.ledger_party_access import require_ledger_identity
from services.path_param_safety import validate_public_url_segment
from services.text_safety import validate_json_strings_safe, validate_safe_storage_text

router = APIRouter()


class CreateVoucherRequest(BaseModel):
    buyer_identity_id: str
    seller_identity_id: str
    amount: float
    currency: str = "USDC"
    bill_credit_amount: float
    task_type: str
    task_description_hash: str
    progress_rule_hash: str
    evidence_requirement_hash: str
    expiry_time: datetime
    nonce: str
    buyer_signature: str
    buyer_sub_identity_id: str | None = None
    seller_sub_identity_id: str | None = None
    progress_rule_spec: dict | None = None
    buyer_wallet_address: str | None = None

    @model_validator(mode="after")
    def _reject_unsafe_embedded_text(self) -> "CreateVoucherRequest":
        validate_safe_storage_text(self.currency, field="currency")
        validate_safe_storage_text(self.task_type, field="task_type")
        validate_safe_storage_text(self.task_description_hash, field="task_description_hash")
        validate_safe_storage_text(self.progress_rule_hash, field="progress_rule_hash")
        validate_safe_storage_text(self.evidence_requirement_hash, field="evidence_requirement_hash")
        validate_safe_storage_text(self.nonce, field="nonce")
        validate_safe_storage_text(self.buyer_signature, field="buyer_signature")
        if self.buyer_wallet_address:
            validate_safe_storage_text(self.buyer_wallet_address, field="buyer_wallet_address")
        if self.progress_rule_spec is not None:
            validate_json_strings_safe(self.progress_rule_spec, field="progress_rule_spec")
        return self


class VerifyVoucherRequest(BaseModel):
    seller_identity_id: str
    expected_amount: float | None = None


class AcceptVoucherRequest(BaseModel):
    seller_identity_id: str


@router.post("", response_model=AuthorizationVoucher, status_code=201)
async def create_voucher(body: CreateVoucherRequest, request: Request, db: AsyncSession = Depends(get_db)):
    assert_runtime_operation_allowed("new_authorization")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    if body.buyer_sub_identity_id:
        validate_public_url_segment("buyer_sub_identity_id", body.buyer_sub_identity_id)
    if body.seller_sub_identity_id:
        validate_public_url_segment("seller_sub_identity_id", body.seller_sub_identity_id)
    validate_public_url_segment("nonce", body.nonce)
    validate_public_url_segment("task_type", body.task_type)
    require_ledger_identity(request, body.buyer_identity_id)
    if body.amount <= 0 or body.bill_credit_amount <= 0:
        raise HTTPException(400, "amount and bill_credit_amount must be > 0")
    if body.expiry_time <= datetime.utcnow():
        raise HTTPException(400, "expiry_time must be in the future")

    cap = await db.get(CapacityModel, body.buyer_identity_id)
    if not cap or cap.available_credits < body.bill_credit_amount:
        raise HTTPException(409, "insufficient buyer available credits")

    await _validate_sub_identity_binding(
        db=db,
        parent_identity_id=body.buyer_identity_id,
        sub_identity_id=body.buyer_sub_identity_id,
        role="buyer",
    )
    await _validate_sub_identity_binding(
        db=db,
        parent_identity_id=body.seller_identity_id,
        sub_identity_id=body.seller_sub_identity_id,
        role="seller",
    )

    assert_buyer_commitment_for_voucher(
        buyer_signature=body.buyer_signature,
        buyer_wallet_address=body.buyer_wallet_address,
        progress_rule_spec=body.progress_rule_spec,
        buyer_identity_id=body.buyer_identity_id,
        seller_identity_id=body.seller_identity_id,
        amount=body.amount,
        bill_credit_amount=body.bill_credit_amount,
        currency=body.currency,
        task_type=body.task_type,
        task_description_hash=body.task_description_hash,
        progress_rule_hash=body.progress_rule_hash,
        evidence_requirement_hash=body.evidence_requirement_hash,
        nonce=body.nonce,
        expiry_time=body.expiry_time,
        cfg=settings,
    )

    payload = body.model_dump()
    payload.pop("buyer_wallet_address", None)
    voucher = AuthorizationVoucher(**payload)
    try:
        db.add(
            VoucherModel(
                voucher_id=voucher.voucher_id,
                buyer_identity_id=voucher.buyer_identity_id,
                seller_identity_id=voucher.seller_identity_id,
                amount=voucher.amount,
                currency=voucher.currency,
                bill_credit_amount=voucher.bill_credit_amount,
                task_type=voucher.task_type,
                task_description_hash=voucher.task_description_hash,
                progress_rule_hash=voucher.progress_rule_hash,
                evidence_requirement_hash=voucher.evidence_requirement_hash,
                expiry_time=voucher.expiry_time,
                nonce=voucher.nonce,
                buyer_signature=voucher.buyer_signature,
                status=voucher.status.value,
                buyer_sub_identity_id=voucher.buyer_sub_identity_id,
                seller_sub_identity_id=voucher.seller_sub_identity_id,
                accepted_at=voucher.accepted_at,
                created_at=voucher.created_at,
                progress_rule_spec=voucher.progress_rule_spec,
            )
        )
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "duplicate voucher nonce for this buyer") from exc

    from services.voucher_events import record_voucher_event
    from services.openclaw_webhook import emit_openclaw_event

    await record_voucher_event(
        db,
        voucher_id=voucher.voucher_id,
        event_type="voucher.created",
        actor_identity_id=voucher.buyer_identity_id,
        target_identity_id=voucher.seller_identity_id,
        payload={
            "amount": float(voucher.amount),
            "task_type": voucher.task_type,
            "bill_credit_amount": float(voucher.bill_credit_amount),
        },
    )
    emit_openclaw_event(
        "voucher.created",
        {
            "voucher_id": voucher.voucher_id,
            "buyer_identity_id": voucher.buyer_identity_id,
            "seller_identity_id": voucher.seller_identity_id,
            "amount": float(voucher.amount),
            "task_type": voucher.task_type,
            "expiry_time": voucher.expiry_time.isoformat(),
        },
    )
    return voucher


@router.get("/{voucher_id}", response_model=AuthorizationVoucher)
async def get_voucher(voucher_id: str, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("voucher_id", voucher_id)
    row = await db.get(VoucherModel, voucher_id)
    if not row:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    return _to_schema(row)


@router.post("/{voucher_id}/verify", response_model=VoucherVerificationResult)
async def verify_voucher(voucher_id: str, body: VerifyVoucherRequest, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("voucher_id", voucher_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    row = await db.get(VoucherModel, voucher_id)
    if not row:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    require_ledger_identity(request, body.seller_identity_id)

    now = datetime.utcnow()
    is_expired = row.expiry_time <= now
    is_used = row.status in {VoucherStatus.USED.value, VoucherStatus.CANCELLED.value}
    seller_matches = row.seller_identity_id == body.seller_identity_id
    amount_matches = body.expected_amount is None or abs(row.amount - body.expected_amount) < 1e-9

    cap = await db.get(CapacityModel, row.buyer_identity_id)
    has_capacity = bool(cap and cap.available_credits >= row.bill_credit_amount)
    accepted = row.status == VoucherStatus.ACCEPTED.value
    reserved_ok = bool(
        cap and accepted and cap.reserved_credits + 1e-9 >= row.bill_credit_amount
    )
    if accepted:
        can_start = (
            (not is_expired)
            and (not is_used)
            and seller_matches
            and amount_matches
            and reserved_ok
        )
    else:
        can_start = (
            (not is_expired)
            and (not is_used)
            and seller_matches
            and amount_matches
            and has_capacity
        )

    return VoucherVerificationResult(
        voucher_id=row.voucher_id,
        is_authentic=True,
        is_expired=is_expired,
        is_used=is_used,
        amount_matches=amount_matches,
        seller_matches=seller_matches,
        has_sufficient_capacity=has_capacity,
        can_start=can_start,
        status=VoucherStatus(row.status),
        voucher_accepted=accepted,
        reserved_covers_voucher_amount=reserved_ok,
    )


@router.get("/{voucher_id}/events")
async def list_voucher_events_route(
    voucher_id: str,
    identity_id: str,
    db: AsyncSession = Depends(get_db),
):
    validate_public_url_segment("voucher_id", voucher_id)
    from services.voucher_events import list_voucher_events

    return {
        "voucher_id": voucher_id,
        "events": await list_voucher_events(db, voucher_id, for_identity_id=identity_id),
    }


@router.post("/{voucher_id}/accept", response_model=AuthorizationVoucher)
async def accept_voucher(voucher_id: str, body: AcceptVoucherRequest, request: Request, db: AsyncSession = Depends(get_db)):
    validate_public_url_segment("voucher_id", voucher_id)
    validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    assert_runtime_operation_allowed("new_authorization")
    await audit_capacity_anchor_and_maybe_trip(db=db)
    require_ledger_identity(request, body.seller_identity_id)
    row = await db.get(VoucherModel, voucher_id)
    if not row:
        raise HTTPException(404, f"Voucher {voucher_id} not found")
    from services.voucher_lifecycle import accept_voucher_row

    row = await accept_voucher_row(db, row, seller_identity_id=body.seller_identity_id, actor="api")
    return _to_schema(row)


def _to_schema(row: VoucherModel) -> AuthorizationVoucher:
    return AuthorizationVoucher(
        voucher_id=row.voucher_id,
        buyer_identity_id=row.buyer_identity_id,
        seller_identity_id=row.seller_identity_id,
        amount=row.amount,
        currency=row.currency,
        bill_credit_amount=row.bill_credit_amount,
        task_type=row.task_type,
        task_description_hash=row.task_description_hash,
        progress_rule_hash=row.progress_rule_hash,
        evidence_requirement_hash=row.evidence_requirement_hash,
        expiry_time=row.expiry_time,
        nonce=row.nonce,
        buyer_signature=row.buyer_signature,
        status=VoucherStatus(row.status),
        buyer_sub_identity_id=row.buyer_sub_identity_id,
        seller_sub_identity_id=row.seller_sub_identity_id,
        accepted_at=row.accepted_at,
        created_at=row.created_at,
        progress_rule_spec=row.progress_rule_spec,
        task_precision=getattr(row, "task_precision", None),
        payment_mode=getattr(row, "payment_mode", "manual") or "manual",
        chain_anchor_hash=getattr(row, "chain_anchor_hash", None),
        rejection_reason=getattr(row, "rejection_reason", None),
        rejected_at=getattr(row, "rejected_at", None),
        rejected_by_identity_id=getattr(row, "rejected_by_identity_id", None),
    )


def _validate_capacity(cap: CapacityModel) -> None:
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


async def _validate_sub_identity_binding(
    *,
    db: AsyncSession,
    parent_identity_id: str,
    sub_identity_id: str | None,
    role: str,
) -> None:
    if sub_identity_id is None:
        return
    row = await db.get(SubIdentityModel, sub_identity_id)
    if not row:
        raise HTTPException(404, f"{role} sub-identity not found: {sub_identity_id}")
    if row.parent_identity_id != parent_identity_id:
        raise HTTPException(409, f"{role} sub-identity parent mismatch")
    if row.status != SubIdentityStatus.ACTIVE.value:
        raise HTTPException(409, f"{role} sub-identity is not active")

