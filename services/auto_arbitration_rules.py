"""P2 — Automatic arbitration rule inputs (timeout, receipt integrity)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import TaskStatus
from db.models.orm import EvidenceBundleModel, ReceiptModel


@dataclass
class AutoArbitrationContext:
    """Structured inputs for auto_arbitrate endpoint."""

    delivery_overdue: bool
    has_success_receipt: bool
    bundle_receipt_ids_ok: bool | None
    notes: list[str]


async def build_auto_arbitration_context(
    db: AsyncSession,
    *,
    task_id: str,
    state_status: TaskStatus,
    delivery_deadline_at: datetime | None,
) -> AutoArbitrationContext:
    notes: list[str] = []
    now = datetime.utcnow()

    delivery_overdue = bool(
        delivery_deadline_at and now > delivery_deadline_at and state_status != TaskStatus.DELIVERED
    )
    if delivery_overdue:
        notes.append("delivery_deadline passed without delivered status")

    r = await db.execute(select(ReceiptModel).where(ReceiptModel.task_id == task_id))
    receipts = list(r.scalars().all())
    has_success_receipt = any(row.status == "success" for row in receipts)
    if not has_success_receipt:
        notes.append("no execution receipt with status success")

    bundle_receipt_ids_ok: bool | None = None
    b = await db.execute(select(EvidenceBundleModel).where(EvidenceBundleModel.task_id == task_id))
    bundle_row = b.scalar_one_or_none()
    if bundle_row is not None and receipts:
        ordered = sorted(receipts, key=lambda row: row.step_index)
        actual_ids = [row.receipt_id for row in ordered]
        bundle_receipt_ids_ok = list(bundle_row.receipt_ids or []) == actual_ids
        if not bundle_receipt_ids_ok:
            notes.append("evidence bundle receipt_ids order or membership mismatch vs stored receipts")
    elif bundle_row is not None and not receipts:
        bundle_receipt_ids_ok = False
        notes.append("evidence bundle present but no execution receipts stored")

    return AutoArbitrationContext(
        delivery_overdue=delivery_overdue,
        has_success_receipt=has_success_receipt,
        bundle_receipt_ids_ok=bundle_receipt_ids_ok,
        notes=notes,
    )


def adjust_auto_split_for_rules(
    ctx: AutoArbitrationContext,
    *,
    confirmed_percent: float,
    escrow_amount: float,
) -> tuple[float, float, str]:
    """
    Returns (settled_amount, refunded_amount, notes_suffix).
    Baseline follows confirmed progress; rules may push toward buyer when proofs are missing.
    """
    if ctx.delivery_overdue and confirmed_percent <= 0.0:
        return 0.0, round(escrow_amount, 2), "rule: overdue delivery with no confirmed progress"

    if not ctx.has_success_receipt and confirmed_percent <= 0.0:
        return 0.0, round(escrow_amount, 2), "rule: no successful execution receipt and no confirmed progress"

    if ctx.bundle_receipt_ids_ok is False and confirmed_percent < 50.0:
        settled = round(escrow_amount * max(confirmed_percent, 0.0) / 100.0, 2)
        refunded = round(escrow_amount - settled, 2)
        return settled, refunded, "rule: evidence bundle integrity failed — conservative partial split"

    if confirmed_percent <= 0.0:
        return 0.0, round(escrow_amount, 2), "auto arbitration: no confirmed progress, buyer wins"
    if confirmed_percent >= 90.0:
        return round(escrow_amount, 2), 0.0, "auto arbitration: near-complete confirmed progress, seller wins"
    settled = round(escrow_amount * confirmed_percent / 100.0, 2)
    refunded = round(escrow_amount - settled, 2)
    return settled, refunded, f"auto arbitration: partial split by confirmed progress {confirmed_percent:.2f}%"
