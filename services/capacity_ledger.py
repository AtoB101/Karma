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


def assert_capacity_invariants(state: CapacityState) -> None:
    active = active_credits(state)
    if abs(state.total_bill_credits - active) > EPSILON:
        raise ValueError("capacity invariant violated: total_bill_credits != active credit sum")
    if state.total_locked_usdc + EPSILON < active:
        raise ValueError("capacity invariant violated: locked usdc below active credits")

