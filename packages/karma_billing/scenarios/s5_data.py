"""S5 — Data Marketplace Scenario (Skeleton).

Buyer requests data → seller delivers → verified → royalty calculated → paid.

Receipt types:
    S5_DATA_REQUESTED → S5_DATA_DELIVERED → S5_DATA_VERIFIED
    → S5_ROYALTY_CALCULATED → S5_PAYMENT_SETTLED
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

S5_RECEIPT_TYPES = frozenset({
    ReceiptType.S5_DATA_REQUESTED,
    ReceiptType.S5_DATA_DELIVERED,
    ReceiptType.S5_DATA_VERIFIED,
    ReceiptType.S5_ROYALTY_CALCULATED,
    ReceiptType.S5_PAYMENT_SETTLED,
})

S5_STATE_PATH = [
    BillingState.INITIATED,
    BillingState.INTENT_RECEIVED,
    BillingState.INTENT_VALIDATED,
    BillingState.DELEGATION_ACCEPTED,
    BillingState.TASK_STARTED,
    BillingState.TASK_COMPLETED,
    BillingState.INVOICE_GENERATED,
    BillingState.PAYMENT_AUTHORIZED,
    BillingState.PAYMENT_SETTLING,
    BillingState.SETTLED,
]

S5_ALLOWED_TRANSITIONS = [
    (BillingState.INITIATED, BillingState.INTENT_RECEIVED),
    (BillingState.INTENT_RECEIVED, BillingState.INTENT_VALIDATED),
    (BillingState.INTENT_VALIDATED, BillingState.DELEGATION_ACCEPTED),
    (BillingState.DELEGATION_ACCEPTED, BillingState.TASK_STARTED),
    (BillingState.TASK_STARTED, BillingState.TASK_COMPLETED),
    (BillingState.TASK_COMPLETED, BillingState.INVOICE_GENERATED),
    (BillingState.INVOICE_GENERATED, BillingState.PAYMENT_AUTHORIZED),
    (BillingState.PAYMENT_AUTHORIZED, BillingState.PAYMENT_SETTLING),
    (BillingState.PAYMENT_SETTLING, BillingState.SETTLED),
]

S5_RECEIPT_TO_STATE_MAP = {
    ReceiptType.S5_DATA_REQUESTED: BillingState.INTENT_VALIDATED,
    ReceiptType.S5_DATA_DELIVERED: BillingState.TASK_COMPLETED,
    ReceiptType.S5_DATA_VERIFIED: BillingState.TASK_COMPLETED,
    ReceiptType.S5_ROYALTY_CALCULATED: BillingState.INVOICE_GENERATED,
    ReceiptType.S5_PAYMENT_SETTLED: BillingState.SETTLED,
}


def register() -> None:
    """Register S5 data marketplace scenario as a skeleton."""
    config = ScenarioConfig(
        scenario_type=ScenarioType.S5_DATA,
        receipt_types=S5_RECEIPT_TYPES,
        state_path=S5_STATE_PATH,
        allowed_transitions=S5_ALLOWED_TRANSITIONS,
        anchoring_policy_overrides={
            "anchoring_threshold": 5,
            "mandatory_anchor_states": [
                BillingState.INVOICE_GENERATED.value,
                BillingState.SETTLED.value,
            ],
        },
    )
    get_registry().register(ScenarioType.S5_DATA, config)
