"""Operational boundary: Karma ops may brake and alert, never move user funds.

User keys stay with users. The company key (TESTNET_PRIVATE_KEY / freezeOperator)
is only allowed to pause, freeze, mark risk, and expire unpaid intents.
Lock / bind / settle / refund / dispute must be user-signed on-chain.
"""
from __future__ import annotations

from config.settings import settings

OPS_ALLOWED_ACTIONS = frozenset(
    {
        "safety_mode",
        "operational_pause",
        "emergency_freeze",
        "risk_mark",
        "expire_payment_intents",
        "alert",
    }
)

FUNDS_MOVING_ACTIONS = frozenset(
    {
        "lock",
        "bind",
        "settle",
        "finalizeSettle",
        "refund",
        "unlock",
        "dispute",
        "offchain_mark_settled",
        "offchain_mark_refunded",
    }
)


class OpsFundsBoundaryError(RuntimeError):
    """Raised when an ops/hot wallet tries to move or pretend to move user funds."""


def ops_may_submit_funds_transactions() -> bool:
    """Dev/testnet scripts may broadcast funds txs; production must keep this false."""
    return bool(settings.chain_allow_ops_submit_funds)


def offchain_payout_marks_allowed() -> bool:
    """MiniApp local demos may mark settled/refunded off-chain; production must not."""
    return bool(settings.ops_allow_offchain_payout_marks)


def assert_ops_may_submit_funds(action: str) -> None:
    if action not in FUNDS_MOVING_ACTIONS:
        return
    if ops_may_submit_funds_transactions():
        return
    raise OpsFundsBoundaryError(
        f"ops key cannot submit {action}: funds transactions must be signed by the "
        "user wallet (CHAIN_ALLOW_OPS_SUBMIT_FUNDS=false)"
    )


def assert_offchain_payout_marks_allowed(action: str) -> None:
    if offchain_payout_marks_allowed():
        return
    raise OpsFundsBoundaryError(
        f"off-chain {action} is disabled: ops must not mark user funds as moved "
        "(OPS_ALLOW_OFFCHAIN_PAYOUT_MARKS=false); parties submit the on-chain tx"
    )
