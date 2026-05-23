"""S8 — Dispute Resolution Scenario (Skeleton).

A party files a dispute → evidence submitted → arbitration → resolution.

Receipt types:
    S8_DISPUTE_FILED → S8_EVIDENCE_SUBMITTED → S8_ARBITRATION_STARTED
    → S8_RESOLUTION_PROPOSED → S8_RESOLUTION_ACCEPTED → S8_REFUND_ISSUED
"""

from packages.karma_billing.schema import (
    ScenarioType,
    ReceiptType,
    BillingState,
)
from packages.karma_billing.scenarios.registry import (
    ScenarioConfig,
    get_registry,
)

S8_RECEIPT_TYPES = frozenset({
    ReceiptType.S8_DISPUTE_FILED,
    ReceiptType.S8_EVIDENCE_SUBMITTED,
    ReceiptType.S8_ARBITRATION_STARTED,
    ReceiptType.S8_RESOLUTION_PROPOSED,
    ReceiptType.S8_RESOLUTION_ACCEPTED,
    ReceiptType.S8_REFUND_ISSUED,
})

S8_STATE_PATH = [
    BillingState.INITIATED,
    BillingState.INTENT_RECEIVED,
    BillingState.INTENT_VALIDATED,
    BillingState.DELEGATION_ACCEPTED,
    BillingState.TASK_STARTED,
    BillingState.TASK_COMPLETED,
    BillingState.INVOICE_GENERATED,
    BillingState.PAYMENT_AUTHORIZED,
    BillingState.PAYMENT_SETTLING,
    BillingState.REFUND_PENDING,
    BillingState.SETTLED,
]

S8_ALLOWED_TRANSITIONS = [
    # Normal flow (dispute filed mid-flow)
    (BillingState.INITIATED, BillingState.INTENT_RECEIVED),
    (BillingState.INTENT_RECEIVED, BillingState.INTENT_VALIDATED),
    (BillingState.INTENT_VALIDATED, BillingState.DELEGATION_ACCEPTED),
    (BillingState.DELEGATION_ACCEPTED, BillingState.TASK_STARTED),
    (BillingState.TASK_STARTED, BillingState.TASK_COMPLETED),
    (BillingState.TASK_COMPLETED, BillingState.INVOICE_GENERATED),
    (BillingState.INVOICE_GENERATED, BillingState.PAYMENT_AUTHORIZED),
    (BillingState.PAYMENT_AUTHORIZED, BillingState.PAYMENT_SETTLING),
    # Dispute / refund path
    (BillingState.PAYMENT_SETTLING, BillingState.REFUND_PENDING),
    (BillingState.REFUND_PENDING, BillingState.SETTLED),
    # Normal settlement
    (BillingState.PAYMENT_SETTLING, BillingState.SETTLED),
]

S8_RECEIPT_TO_STATE_MAP = {
    ReceiptType.S8_DISPUTE_FILED: BillingState.PAYMENT_SETTLING,
    ReceiptType.S8_EVIDENCE_SUBMITTED: BillingState.PAYMENT_SETTLING,
    ReceiptType.S8_ARBITRATION_STARTED: BillingState.PAYMENT_SETTLING,
    ReceiptType.S8_RESOLUTION_PROPOSED: BillingState.REFUND_PENDING,
    ReceiptType.S8_RESOLUTION_ACCEPTED: BillingState.REFUND_PENDING,
    ReceiptType.S8_REFUND_ISSUED: BillingState.SETTLED,
}


def register() -> None:
    """Register S8 dispute scenario as a skeleton."""
    config = ScenarioConfig(
        scenario_type=ScenarioType.S8_DISPUTE,
        receipt_types=S8_RECEIPT_TYPES,
        state_path=S8_STATE_PATH,
        allowed_transitions=S8_ALLOWED_TRANSITIONS,
        anchoring_policy_overrides={
            "anchoring_threshold": 2,  # Disputes anchor more frequently
            "mandatory_anchor_states": [
                BillingState.REFUND_PENDING.value,
                BillingState.SETTLED.value,
            ],
        },
    )
    get_registry().register(ScenarioType.S8_DISPUTE, config)
