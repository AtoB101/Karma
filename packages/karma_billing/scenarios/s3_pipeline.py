"""S3 — Pipeline Scenario (Skeleton).

Multi-stage pipeline: each stage is a subtask, executed sequentially
or in parallel by different agents.  Invoice is aggregated across stages.

Receipt types:
    S3_PIPELINE_CREATED → S3_STAGE_STARTED → S3_STAGE_COMPLETED (×N)
    → S3_PIPELINE_COMPLETED → S3_INVOICE_AGGREGATED → S3_PAYMENT_SETTLED
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

S3_RECEIPT_TYPES = frozenset({
    ReceiptType.S3_PIPELINE_CREATED,
    ReceiptType.S3_STAGE_STARTED,
    ReceiptType.S3_STAGE_COMPLETED,
    ReceiptType.S3_PIPELINE_COMPLETED,
    ReceiptType.S3_INVOICE_AGGREGATED,
    ReceiptType.S3_PAYMENT_SETTLED,
})

S3_STATE_PATH = [
    BillingState.INITIATED,
    BillingState.INTENT_RECEIVED,
    BillingState.INTENT_VALIDATED,
    BillingState.PIPELINE_STAGING,
    BillingState.STEP_IN_PROGRESS,
    BillingState.STEP_COMPLETED,
    BillingState.TASK_COMPLETED,
    BillingState.INVOICE_GENERATED,
    BillingState.PAYMENT_AUTHORIZED,
    BillingState.PAYMENT_SETTLING,
    BillingState.SETTLED,
]

S3_ALLOWED_TRANSITIONS = [
    (BillingState.INITIATED, BillingState.INTENT_RECEIVED),
    (BillingState.INTENT_RECEIVED, BillingState.INTENT_VALIDATED),
    (BillingState.INTENT_VALIDATED, BillingState.PIPELINE_STAGING),
    (BillingState.PIPELINE_STAGING, BillingState.STEP_IN_PROGRESS),
    (BillingState.PIPELINE_STAGING, BillingState.TASK_COMPLETED),
    (BillingState.STEP_IN_PROGRESS, BillingState.STEP_COMPLETED),
    (BillingState.STEP_COMPLETED, BillingState.STEP_IN_PROGRESS),  # next stage
    (BillingState.STEP_COMPLETED, BillingState.TASK_COMPLETED),
    (BillingState.TASK_COMPLETED, BillingState.INVOICE_GENERATED),
    (BillingState.INVOICE_GENERATED, BillingState.PAYMENT_AUTHORIZED),
    (BillingState.PAYMENT_AUTHORIZED, BillingState.PAYMENT_SETTLING),
    (BillingState.PAYMENT_SETTLING, BillingState.SETTLED),
]

S3_RECEIPT_TO_STATE_MAP = {
    ReceiptType.S3_PIPELINE_CREATED: BillingState.PIPELINE_STAGING,
    ReceiptType.S3_STAGE_STARTED: BillingState.STEP_IN_PROGRESS,
    ReceiptType.S3_STAGE_COMPLETED: BillingState.STEP_COMPLETED,
    ReceiptType.S3_PIPELINE_COMPLETED: BillingState.TASK_COMPLETED,
    ReceiptType.S3_INVOICE_AGGREGATED: BillingState.INVOICE_GENERATED,
    ReceiptType.S3_PAYMENT_SETTLED: BillingState.SETTLED,
}


def register() -> None:
    """Register S3 pipeline scenario as a skeleton."""
    config = ScenarioConfig(
        scenario_type=ScenarioType.S3_PIPELINE,
        receipt_types=S3_RECEIPT_TYPES,
        state_path=S3_STATE_PATH,
        allowed_transitions=S3_ALLOWED_TRANSITIONS,
        anchoring_policy_overrides={
            "anchoring_threshold": 5,
            "mandatory_anchor_states": [
                BillingState.TASK_COMPLETED.value,
                BillingState.INVOICE_GENERATED.value,
                BillingState.SETTLED.value,
            ],
        },
    )
    get_registry().register(ScenarioType.S3_PIPELINE, config)
