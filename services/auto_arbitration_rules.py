"""P2 — Automatic arbitration rule inputs (timeout, receipt / bundle integrity)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import TaskStatus
from core.evidence.bundle_builder import execution_receipt_bundle_digest
from db.models.orm import EvidenceBundleModel, ReceiptModel
from db.stores.receipt_store import PostgresReceiptStore

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _hashes_well_formed(hashes: list | None) -> bool:
    if not hashes:
        return False
    for h in hashes:
        if not isinstance(h, str) or not _HEX64.fullmatch(h.strip().lower()):
            return False
    return True


@dataclass
class AutoArbitrationContext:
    """Structured inputs for auto_arbitrate endpoint."""

    delivery_overdue: bool
    has_success_receipt: bool
    bundle_receipt_ids_ok: bool | None
    bundle_step_counts_ok: bool | None
    bundle_receipt_hashes_match: bool | None
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
    bundle_step_counts_ok: bool | None = None
    bundle_receipt_hashes_match: bool | None = None

    b = await db.execute(select(EvidenceBundleModel).where(EvidenceBundleModel.task_id == task_id))
    bundle_row = b.scalar_one_or_none()
    if bundle_row is not None and receipts:
        ordered = sorted(receipts, key=lambda row: row.step_index)
        actual_ids = [row.receipt_id for row in ordered]
        bundle_receipt_ids_ok = list(bundle_row.receipt_ids or []) == actual_ids
        if not bundle_receipt_ids_ok:
            notes.append("evidence bundle receipt_ids order or membership mismatch vs stored receipts")

        n = len(ordered)
        ts = int(bundle_row.total_steps)
        ss = int(bundle_row.successful_steps)
        fs = int(bundle_row.failed_steps)
        bundle_step_counts_ok = ts == n and ss + fs <= n and ss >= 0 and fs >= 0
        if not bundle_step_counts_ok:
            notes.append("evidence bundle total_steps / success+fail counts inconsistent with stored receipts")

        if not _hashes_well_formed(bundle_row.receipt_hashes):
            bundle_receipt_hashes_match = False
            notes.append("evidence bundle receipt_hashes are not all 64-char lowercase hex")
        else:
            computed: list[str] = []
            for row in ordered:
                er = PostgresReceiptStore._from_row(row)
                computed.append(execution_receipt_bundle_digest(er))
            declared = [str(h).strip().lower() for h in (bundle_row.receipt_hashes or [])]
            bundle_receipt_hashes_match = declared == computed
            if not bundle_receipt_hashes_match:
                notes.append("evidence bundle receipt_hashes do not match recomputed digests of stored receipts")

    elif bundle_row is not None and not receipts:
        bundle_receipt_ids_ok = False
        bundle_step_counts_ok = False
        bundle_receipt_hashes_match = False
        notes.append("evidence bundle present but no execution receipts stored")

    return AutoArbitrationContext(
        delivery_overdue=delivery_overdue,
        has_success_receipt=has_success_receipt,
        bundle_receipt_ids_ok=bundle_receipt_ids_ok,
        bundle_step_counts_ok=bundle_step_counts_ok,
        bundle_receipt_hashes_match=bundle_receipt_hashes_match,
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
    if ctx.bundle_step_counts_ok is False:
        return 0.0, round(escrow_amount, 2), "rule: evidence bundle format error (step metadata vs receipts)"

    integrity_bad = ctx.bundle_receipt_ids_ok is False or ctx.bundle_receipt_hashes_match is False
    if integrity_bad and confirmed_percent <= 0.0:
        return 0.0, round(escrow_amount, 2), "rule: evidence bundle integrity failed with no confirmed progress — buyer wins"

    if ctx.delivery_overdue and confirmed_percent <= 0.0:
        return 0.0, round(escrow_amount, 2), "rule: overdue delivery with no confirmed progress"

    if not ctx.has_success_receipt and confirmed_percent <= 0.0:
        return 0.0, round(escrow_amount, 2), "rule: no successful execution receipt and no confirmed progress"

    if integrity_bad and confirmed_percent < 50.0:
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
