"""S2 — Bidding / Auction Scenario (Skeleton).

Buyer opens a bid → multiple sellers place bids → best bid wins → task executed.

Receipt types:
    S2_BID_OPENED → S2_BID_PLACED (×N) → S2_BID_EVALUATED
    → S2_BID_ACCEPTED → S2_TASK_EXECUTED → S2_INVOICE_GENERATED
    → S2_PAYMENT_SETTLED
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

S2_RECEIPT_TYPES = frozenset({
    ReceiptType.S2_BID_OPENED,
    ReceiptType.S2_BID_PLACED,
    ReceiptType.S2_BID_EVALUATED,
    ReceiptType.S2_BID_ACCEPTED,
    ReceiptType.S2_TASK_EXECUTED,
    ReceiptType.S2_INVOICE_GENERATED,
    ReceiptType.S2_PAYMENT_SETTLED,
})

S2_STATE_PATH = [
    BillingState.INITIATED,
    BillingState.INTENT_RECEIVED,
    BillingState.INTENT_VALIDATED,
    BillingState.BID_EVALUATING,
    BillingState.BID_ACCEPTED,
    BillingState.TASK_STARTED,
    BillingState.STEP_IN_PROGRESS,
    BillingState.STEP_COMPLETED,
    BillingState.TASK_COMPLETED,
    BillingState.INVOICE_GENERATED,
    BillingState.PAYMENT_AUTHORIZED,
    BillingState.PAYMENT_SETTLING,
    BillingState.SETTLED,
]

S2_ALLOWED_TRANSITIONS = [
    (BillingState.INITIATED, BillingState.INTENT_RECEIVED),
    (BillingState.INTENT_RECEIVED, BillingState.INTENT_VALIDATED),
    (BillingState.INTENT_VALIDATED, BillingState.BID_EVALUATING),
    (BillingState.BID_EVALUATING, BillingState.BID_ACCEPTED),
    (BillingState.BID_EVALUATING, BillingState.INVOICE_GENERATED),  # no-accept path
    (BillingState.BID_ACCEPTED, BillingState.TASK_STARTED),
    (BillingState.TASK_STARTED, BillingState.STEP_IN_PROGRESS),
    (BillingState.STEP_IN_PROGRESS, BillingState.STEP_COMPLETED),
    (BillingState.STEP_COMPLETED, BillingState.TASK_COMPLETED),
    (BillingState.TASK_COMPLETED, BillingState.INVOICE_GENERATED),
    (BillingState.INVOICE_GENERATED, BillingState.PAYMENT_AUTHORIZED),
    (BillingState.PAYMENT_AUTHORIZED, BillingState.PAYMENT_SETTLING),
    (BillingState.PAYMENT_SETTLING, BillingState.SETTLED),
]

S2_RECEIPT_TO_STATE_MAP = {
    ReceiptType.S2_BID_OPENED: BillingState.BID_EVALUATING,
    ReceiptType.S2_BID_PLACED: BillingState.BID_EVALUATING,
    ReceiptType.S2_BID_EVALUATED: BillingState.BID_EVALUATING,
    ReceiptType.S2_BID_ACCEPTED: BillingState.BID_ACCEPTED,
    ReceiptType.S2_TASK_EXECUTED: BillingState.TASK_COMPLETED,
    ReceiptType.S2_INVOICE_GENERATED: BillingState.INVOICE_GENERATED,
    ReceiptType.S2_PAYMENT_SETTLED: BillingState.SETTLED,
}


def register() -> None:
    """Register S2 bidding scenario as a skeleton."""
    config = ScenarioConfig(
        scenario_type=ScenarioType.S2_BIDDING,
        receipt_types=S2_RECEIPT_TYPES,
        state_path=S2_STATE_PATH,
        allowed_transitions=S2_ALLOWED_TRANSITIONS,
        anchoring_policy_overrides={
            "anchoring_threshold": 5,
            "mandatory_anchor_states": [
                BillingState.BID_ACCEPTED.value,
                BillingState.INVOICE_GENERATED.value,
                BillingState.SETTLED.value,
            ],
        },
    )
    get_registry().register(ScenarioType.S2_BIDDING, config)
