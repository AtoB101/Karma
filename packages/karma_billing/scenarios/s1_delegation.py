"""S1 — Single Delegation Scenario.

The most common billing flow: a buyer delegates a single task to a seller,
who executes it step-by-step and submits an invoice upon completion.

Receipt flow (10 receipt types):
    S1_INTENT_CREATED → S1_INTENT_SIGNED → S1_DELEGATION_ACCEPTED
    → S1_TASK_STARTED → S1_STEP_EXECUTED (×N) → S1_TASK_COMPLETED
    → S1_INVOICE_GENERATED → S1_PAYMENT_AUTHORIZED → S1_PAYMENT_SETTLED
    → S1_RECEIPT_FINAL
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

S1_RECEIPT_TYPES = frozenset({
    ReceiptType.S1_INTENT_CREATED,
    ReceiptType.S1_INTENT_SIGNED,
    ReceiptType.S1_DELEGATION_ACCEPTED,
    ReceiptType.S1_TASK_STARTED,
    ReceiptType.S1_STEP_EXECUTED,
    ReceiptType.S1_TASK_COMPLETED,
    ReceiptType.S1_INVOICE_GENERATED,
    ReceiptType.S1_PAYMENT_AUTHORIZED,
    ReceiptType.S1_PAYMENT_SETTLED,
    ReceiptType.S1_RECEIPT_FINAL,
})

S1_STATE_PATH = [
    BillingState.INITIATED,
    BillingState.INTENT_RECEIVED,        # S1_INTENT_CREATED
    BillingState.INTENT_VALIDATED,       # S1_INTENT_SIGNED
    BillingState.DELEGATION_ACCEPTED,    # S1_DELEGATION_ACCEPTED
    BillingState.TASK_STARTED,           # S1_TASK_STARTED
    BillingState.STEP_IN_PROGRESS,       # S1_STEP_EXECUTED
    BillingState.STEP_COMPLETED,         # (step finished)
    BillingState.TASK_COMPLETED,         # S1_TASK_COMPLETED
    BillingState.INVOICE_GENERATED,      # S1_INVOICE_GENERATED
    BillingState.PAYMENT_AUTHORIZED,     # S1_PAYMENT_AUTHORIZED
    BillingState.PAYMENT_PENDING,        # (awaiting settlement)
    BillingState.PAYMENT_SETTLING,       # S1_PAYMENT_SETTLED
    BillingState.SETTLED,                # S1_RECEIPT_FINAL (terminal)
]

# Explicit transition pairs for this scenario
S1_ALLOWED_TRANSITIONS = [
    (BillingState.INITIATED, BillingState.INTENT_RECEIVED),
    (BillingState.INTENT_RECEIVED, BillingState.INTENT_VALIDATED),
    (BillingState.INTENT_VALIDATED, BillingState.DELEGATION_ACCEPTED),
    (BillingState.DELEGATION_ACCEPTED, BillingState.TASK_STARTED),
    (BillingState.TASK_STARTED, BillingState.STEP_IN_PROGRESS),
    (BillingState.STEP_IN_PROGRESS, BillingState.STEP_COMPLETED),
    (BillingState.STEP_COMPLETED, BillingState.STEP_IN_PROGRESS),  # loop for multiple steps
    (BillingState.STEP_IN_PROGRESS, BillingState.TASK_COMPLETED),
    (BillingState.STEP_COMPLETED, BillingState.TASK_COMPLETED),
    (BillingState.TASK_COMPLETED, BillingState.INVOICE_GENERATED),
    (BillingState.INVOICE_GENERATED, BillingState.PAYMENT_AUTHORIZED),
    (BillingState.PAYMENT_AUTHORIZED, BillingState.PAYMENT_PENDING),
    (BillingState.PAYMENT_PENDING, BillingState.PAYMENT_SETTLING),
    (BillingState.PAYMENT_SETTLING, BillingState.SETTLED),
]

S1_ANCHORING_POLICY = {
    "anchoring_threshold": 3,  # Anchor every 3 receipts
    "mandatory_anchor_states": [
        BillingState.INTENT_VALIDATED.value,
        BillingState.TASK_COMPLETED.value,
        BillingState.INVOICE_GENERATED.value,
        BillingState.SETTLED.value,
    ],
}

S1_RECEIPT_TO_STATE_MAP = {
    ReceiptType.S1_INTENT_CREATED: BillingState.INTENT_RECEIVED,
    ReceiptType.S1_INTENT_SIGNED: BillingState.INTENT_VALIDATED,
    ReceiptType.S1_DELEGATION_ACCEPTED: BillingState.DELEGATION_ACCEPTED,
    ReceiptType.S1_TASK_STARTED: BillingState.TASK_STARTED,
    ReceiptType.S1_STEP_EXECUTED: BillingState.STEP_IN_PROGRESS,
    ReceiptType.S1_TASK_COMPLETED: BillingState.TASK_COMPLETED,
    ReceiptType.S1_INVOICE_GENERATED: BillingState.INVOICE_GENERATED,
    ReceiptType.S1_PAYMENT_AUTHORIZED: BillingState.PAYMENT_AUTHORIZED,
    ReceiptType.S1_PAYMENT_SETTLED: BillingState.PAYMENT_SETTLING,
    ReceiptType.S1_RECEIPT_FINAL: BillingState.SETTLED,
}


def register() -> None:
    """Register S1 delegated billing scenario with the global registry."""
    config = ScenarioConfig(
        scenario_type=ScenarioType.S1_DELEGATION,
        receipt_types=S1_RECEIPT_TYPES,
        state_path=S1_STATE_PATH,
        allowed_transitions=S1_ALLOWED_TRANSITIONS,
        anchoring_policy_overrides=S1_ANCHORING_POLICY,
    )
    get_registry().register(ScenarioType.S1_DELEGATION, config)
