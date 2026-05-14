"""Receipt chronology helpers (naive DB vs aware client timestamps)."""
from __future__ import annotations

from datetime import datetime, timezone

from services.receipt_guard import execution_receipt_starts_before_prior_ended


def test_chronology_mixed_naive_prior_and_aware_new_start() -> None:
    prior_ended = datetime(2026, 5, 14, 12, 0, 0)  # naive (typical ORM round-trip)
    new_ok = datetime(2026, 5, 14, 12, 0, 2, tzinfo=timezone.utc)
    assert not execution_receipt_starts_before_prior_ended(
        started_at=new_ok, prior_ended_at=prior_ended
    )


def test_chronology_detects_out_of_order_mixed_tz() -> None:
    prior_ended = datetime(2026, 5, 14, 12, 0, 0)
    new_bad = datetime(2026, 5, 14, 11, 59, 59, tzinfo=timezone.utc)
    assert execution_receipt_starts_before_prior_ended(
        started_at=new_bad, prior_ended_at=prior_ended
    )
