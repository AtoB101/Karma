"""Unit tests for P2 auto-arbitration rule split adjustments."""
from __future__ import annotations

from services.auto_arbitration_rules import AutoArbitrationContext, adjust_auto_split_for_rules


def test_step_format_error_full_refund():
    ctx = AutoArbitrationContext(
        delivery_overdue=False,
        has_success_receipt=True,
        bundle_receipt_ids_ok=True,
        bundle_step_counts_ok=False,
        bundle_receipt_hashes_match=True,
        notes=["bad steps"],
    )
    s, r, n = adjust_auto_split_for_rules(ctx, confirmed_percent=80.0, escrow_amount=100.0)
    assert s == 0.0 and r == 100.0
    assert "format error" in n


def test_hash_mismatch_no_confirmed_buyer_wins():
    ctx = AutoArbitrationContext(
        delivery_overdue=False,
        has_success_receipt=True,
        bundle_receipt_ids_ok=True,
        bundle_step_counts_ok=True,
        bundle_receipt_hashes_match=False,
        notes=["hashes"],
    )
    s, r, n = adjust_auto_split_for_rules(ctx, confirmed_percent=0.0, escrow_amount=50.0)
    assert s == 0.0 and r == 50.0
    assert "integrity failed" in n


def test_hash_mismatch_with_confirmed_conservative():
    ctx = AutoArbitrationContext(
        delivery_overdue=False,
        has_success_receipt=True,
        bundle_receipt_ids_ok=True,
        bundle_step_counts_ok=True,
        bundle_receipt_hashes_match=False,
        notes=["hashes"],
    )
    s, r, n = adjust_auto_split_for_rules(ctx, confirmed_percent=30.0, escrow_amount=100.0)
    assert s == 30.0 and r == 70.0
    assert "conservative" in n


def test_ids_mismatch_uses_same_integrity_branch():
    ctx = AutoArbitrationContext(
        delivery_overdue=False,
        has_success_receipt=True,
        bundle_receipt_ids_ok=False,
        bundle_step_counts_ok=True,
        bundle_receipt_hashes_match=True,
        notes=[],
    )
    s, r, _ = adjust_auto_split_for_rules(ctx, confirmed_percent=40.0, escrow_amount=200.0)
    assert s == 80.0 and r == 120.0
