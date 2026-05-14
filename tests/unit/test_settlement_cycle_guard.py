"""Pure graph logic for settlement payment-cycle blocking (KSA2-034)."""
from __future__ import annotations

from services.settlement_cycle_guard import worker_reaches_buyer_on_edges


def test_worker_reaches_buyer_detects_chain() -> None:
    edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]
    assert worker_reaches_buyer_on_edges(edges, "A", "E")
    assert not worker_reaches_buyer_on_edges(edges, "E", "A")


def test_worker_reaches_buyer_false_when_disconnected() -> None:
    edges = [("A", "B"), ("C", "D")]
    assert not worker_reaches_buyer_on_edges(edges, "B", "A")
