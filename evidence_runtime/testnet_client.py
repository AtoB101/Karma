"""Minimal helpers for KarmaBilateral testnet scripts (JSON-RPC)."""

from __future__ import annotations

from typing import Any


def summarize_bilateral_preflight(
    *,
    buyer_free: int,
    agent_free: int,
    amount: int,
) -> list[str]:
    """Human-readable capacity checks before lock/bind."""
    lines = [
        f"bilateral preflight (amount={amount} wei):",
        f"  buyer freeBalance={buyer_free}",
        f"  agent freeBalance={agent_free}",
    ]
    if buyer_free < amount:
        lines.append("  [fail] buyer freeBalance < amount")
    if agent_free < amount:
        lines.append("  [fail] agent freeBalance < amount")
    if buyer_free >= amount and agent_free >= amount:
        lines.append("  [ok] both parties have enough free bill capacity to lock.")
    return lines


def as_checksum_address(value: str) -> str:
    return value
