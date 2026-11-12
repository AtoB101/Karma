"""Capacity ledger helpers enforcing 1:1 anchored constraints."""
from __future__ import annotations

from core.schemas import CapacityState

EPSILON = 1e-9


def active_credits(state: CapacityState) -> float:
    return (
        state.available_credits
        + state.reserved_credits
        + state.in_progress_credits
        + state.confirmed_progress_credits
        + state.disputed_credits
        + state.pending_settlement_credits
    )


def responsibility_credits(state: CapacityState) -> float:
    """Bill credits in active responsibility buckets (non-available)."""
    return (
        state.reserved_credits
        + state.in_progress_credits
        + state.confirmed_progress_credits
        + state.disputed_credits
        + state.pending_settlement_credits
    )


def assert_can_release_locked_funds(state: CapacityState, amount: float) -> None:
    """Phase 1: cannot release anchored USDC while any bill credit holds responsibility."""
    if amount <= 0:
        raise ValueError("release amount must be > 0")
    if state.available_credits + 1e-9 < amount:
        raise ValueError("insufficient available credits")
    if responsibility_credits(state) > EPSILON:
        raise ValueError(
            "cannot release locked funds while bill credits hold active responsibility "
            "(reserved, in_progress, confirmed, disputed, or pending_settlement)"
        )


def assert_capacity_invariants(state: CapacityState) -> None:
    active = active_credits(state)
    if abs(state.total_bill_credits - active) > EPSILON:
        raise ValueError("capacity invariant violated: total_bill_credits != active credit sum")
    if state.total_locked_usdc + EPSILON < active:
        raise ValueError("capacity invariant violated: locked usdc below active credits")

