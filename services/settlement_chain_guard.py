"""Fail-closed guard: off-chain terminal settlement requires on-chain finality (testnet/hybrid).

When ``SETTLEMENT_MODE`` is ``testnet`` or ``hybrid``, KarmaBilateral is the authoritative
escrow. Recording a terminal off-chain status (SETTLED/REFUNDED) without the corresponding
on-chain finality (``settle`` → ``finalizeSettle``, or ``refundOnTimeout``) would leave the
off-chain ledger claiming funds moved while USDC is still locked on-chain — a false
settlement that is exactly the class of bug this guard prevents.

The guard fails closed: terminal fund-moving transitions are rejected until the settlement
carries terminal on-chain evidence (``onchain_status`` + ``tx_hash``). In ``offchain`` mode
it is a no-op, preserving existing behavior.
"""
from __future__ import annotations

from fastapi import HTTPException

from config.settings import settings
from core.schemas import SettlementState, TaskStatus

_ONCHAIN_MODES = ("testnet", "hybrid")

# onchain_status values indicating on-chain funds have reached a terminal state.
_TERMINAL_ONCHAIN_STATUSES = {"settled", "refunded", "released"}

# TaskStatus values that move funds to a terminal economic party.
_FUND_TERMINAL_STATUSES = {TaskStatus.SETTLED, TaskStatus.REFUNDED}


def assert_settlement_chain_finality(state: SettlementState, target_status: TaskStatus) -> None:
    """Reject terminal off-chain settlement without on-chain finality in testnet/hybrid."""
    if settings.settlement_mode not in _ONCHAIN_MODES:
        return
    if target_status not in _FUND_TERMINAL_STATUSES:
        return

    onchain_status = (getattr(state, "onchain_status", None) or "").strip().lower()
    tx_hash = (getattr(state, "tx_hash", None) or "").strip()
    if onchain_status in _TERMINAL_ONCHAIN_STATUSES and tx_hash:
        return

    raise HTTPException(
        status_code=409,
        detail={
            "error": "onchain_settlement_finality_required",
            "detail": (
                "SETTLEMENT_MODE is %s but this settlement has no terminal on-chain "
                "finality (onchain_status=%r, tx_hash=%r). Complete the KarmaBilateral "
                "settle → finalizeSettle (or refundOnTimeout) flow and record the result "
                "before marking the settlement %s."
                % (settings.settlement_mode, onchain_status, tx_hash, target_status.value)
            ),
            "settlement_mode": settings.settlement_mode,
            "target_status": target_status.value,
        },
    )
