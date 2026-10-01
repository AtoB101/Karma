"""Karma Billing — Hybrid Architecture Invoice & Receipt Layer.

Provides immutable billing state machine, universal receipt schema,
real-time sync pipeline, and WebSocket event hub for the Karma Trust Protocol.

NOT WIRED INTO THE PRODUCTION SETTLEMENT PATH (verified 2026-10-01).
-------------------------------------------------------------------
The path that actually moves funds is the on-chain ``KarmaBilateral`` escrow
(``lock -> bind -> settle -> finalizeSettle``) plus
``core.settlement.engine.VALID_TRANSITIONS`` for the off-chain task status.

Nothing under ``packages/karma_billing`` is imported by ``api/``, ``services/``,
``db/``, ``worker/`` or ``apps/``. The only importers are ``tests/``,
``packages/karma_security.auditor`` and the ``scripts/demo_*`` /
``scripts/*fullstack_test.py`` demos. Two consequences worth knowing:

* ``BILLING_STATE_TRANSITIONS`` is a *second*, unrelated state machine (17
  states, terminal = ``SETTLED`` only, no failure/cancel exits). It is not a
  mirror of the settlement lifecycle and shares no state names with it.
* ``docs/PILOT_E2E_PATH.md`` lists the Solana Merkle bridge half of this package
  as **Deferred** / out of pilot scope.

Wiring it into the settlement path would be a product decision (billing
receipts <-> escrow), not a follow-up cleanup.
"""

from packages.karma_billing.schema import (
    ScenarioType,
    ReceiptStatus,
    ReceiptType,
    BillingState,
    UniversalReceipt,
    BillingSnapshot,
    StateTransitionRecord,
    compute_payload_hash,
    compute_leaf_hash,
)

__all__ = [
    "ScenarioType",
    "ReceiptStatus",
    "ReceiptType",
    "BillingState",
    "UniversalReceipt",
    "BillingSnapshot",
    "StateTransitionRecord",
    "compute_payload_hash",
    "compute_leaf_hash",
]
