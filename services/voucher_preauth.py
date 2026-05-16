"""Pre-authorization matching and auto accept/reject for incoming vouchers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from db.models.orm import AgentAutomationPolicyModel, VoucherModel
from services.agent_automation_policy import get_automation_policy


@dataclass
class PreauthEvaluation:
    accept: bool
    reason: str
    code: str


def _precision_in_range(
    value: float | None,
    *,
    min_v: float | None,
    max_v: float | None,
) -> bool:
    if value is None:
        return min_v is None and max_v is None
    if min_v is not None and value + 1e-9 < min_v:
        return False
    if max_v is not None and value > max_v + 1e-9:
        return False
    return True


async def evaluate_seller_preauth(
    db,
    *,
    seller_identity_id: str,
    voucher: VoucherModel,
) -> PreauthEvaluation:
    policy = await get_automation_policy(db, seller_identity_id)
    if not policy or not policy.preauth_enabled or not policy.auto_accept_incoming:
        return PreauthEvaluation(False, "seller preauth auto-accept not enabled", "preauth_disabled")

    if not policy.responsibility_acknowledged:
        return PreauthEvaluation(False, "seller responsibility boundary not acknowledged", "no_responsibility_ack")

    if voucher.expiry_time <= datetime.utcnow():
        return PreauthEvaluation(False, "payment code expired", "expired")

    allowed_types = list(policy.allowed_task_types or [])
    if allowed_types and voucher.task_type not in allowed_types:
        return PreauthEvaluation(False, f"task_type {voucher.task_type!r} not allowed", "task_type_mismatch")

    precision = getattr(voucher, "task_precision", None)
    if not _precision_in_range(
        precision,
        min_v=policy.task_precision_min,
        max_v=policy.task_precision_max,
    ):
        return PreauthEvaluation(False, "task_precision out of seller preauth range", "precision_mismatch")

    if voucher.amount > policy.single_limit + 1e-9:
        return PreauthEvaluation(False, "amount exceeds seller single_limit", "amount_over_limit")

    if voucher.bill_credit_amount > policy.single_limit + 1e-9:
        return PreauthEvaluation(False, "bill_credit exceeds seller single_limit", "bill_credit_over_limit")

    trusted = list(policy.trusted_counterparty_ids or [])
    if trusted and voucher.buyer_identity_id not in trusted:
        return PreauthEvaluation(False, "buyer not in seller trusted list", "buyer_not_trusted")

    boundary = (policy.responsibility_boundary_id or "").strip()
    if boundary and voucher.payment_mode == "preauth":
        buyer_policy = await get_automation_policy(db, voucher.buyer_identity_id)
        buyer_boundary = (buyer_policy.responsibility_boundary_id or "").strip() if buyer_policy else ""
        if buyer_boundary and buyer_boundary != boundary:
            return PreauthEvaluation(False, "responsibility_boundary_id mismatch", "boundary_mismatch")

    return PreauthEvaluation(True, "preauth rules satisfied", "accepted")


async def evaluate_buyer_preauth_for_create(
    policy: AgentAutomationPolicyModel | None,
    *,
    seller_identity_id: str,
    amount: float,
    task_type: str,
    task_precision: float | None,
) -> PreauthEvaluation:
    if not policy or not policy.preauth_enabled:
        return PreauthEvaluation(True, "manual mode or buyer preauth off", "skipped")

    if not policy.responsibility_acknowledged:
        return PreauthEvaluation(False, "buyer responsibility boundary not acknowledged", "no_responsibility_ack")

    allowed_types = list(policy.allowed_task_types or [])
    if allowed_types and task_type not in allowed_types:
        return PreauthEvaluation(False, f"task_type {task_type!r} not allowed for buyer", "task_type_mismatch")

    if not _precision_in_range(
        task_precision,
        min_v=policy.task_precision_min,
        max_v=policy.task_precision_max,
    ):
        return PreauthEvaluation(False, "task_precision out of buyer preauth range", "precision_mismatch")

    if amount > policy.single_limit + 1e-9:
        return PreauthEvaluation(False, "amount exceeds buyer single_limit", "amount_over_limit")

    trusted = list(policy.trusted_counterparty_ids or [])
    if trusted and seller_identity_id not in trusted:
        return PreauthEvaluation(False, "seller not in buyer trusted list", "seller_not_trusted")

    return PreauthEvaluation(True, "buyer preauth ok", "ok")


def evaluation_to_dict(ev: PreauthEvaluation) -> dict[str, Any]:
    return {"accept": ev.accept, "reason": ev.reason, "code": ev.code}
