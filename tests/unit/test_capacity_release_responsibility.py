"""Phase 1 — cannot release USDC while responsibility buckets hold credits."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from core.schemas import CapacityState
from services.capacity_ledger import assert_can_release_locked_funds, responsibility_credits


def test_responsibility_credits_sum():
    state = CapacityState(
        identity_id="id-1",
        total_locked_usdc=100.0,
        total_bill_credits=100.0,
        available_credits=40.0,
        reserved_credits=60.0,
    )
    assert responsibility_credits(state) == 60.0


def test_release_blocked_when_reserved():
    state = CapacityState(
        identity_id="id-1",
        total_locked_usdc=100.0,
        total_bill_credits=100.0,
        available_credits=40.0,
        reserved_credits=60.0,
    )
    with pytest.raises(ValueError, match="active responsibility"):
        assert_can_release_locked_funds(state, 10.0)


def test_release_allowed_when_only_available():
    state = CapacityState(
        identity_id="id-1",
        total_locked_usdc=50.0,
        total_bill_credits=50.0,
        available_credits=50.0,
    )
    assert_can_release_locked_funds(state, 10.0)
