"""Universal Receipt schema and enums for the Karma Hybrid Billing Architecture.

All receipt types across 10 scenarios, billing lifecycle states, and the canonical
UniversalReceipt structure that serves as the single source of truth for every billing event.
"""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Scenario Types ────────────────────────────────────────────────────────────


class ScenarioType(str, Enum):
    """Top-level billing scenarios recognised by the Karma protocol."""

    S1_DELEGATION = "S1_DELEGATION"
    S2_BIDDING = "S2_BIDDING"
    S3_PIPELINE = "S3_PIPELINE"
    S4_MULTI_DELEGATION = "S4_MULTI_DELEGATION"
    S5_DATA = "S5_DATA"
    S6_CONDITIONAL = "S6_CONDITIONAL"
    S7_RECURRING = "S7_RECURRING"
    S8_DISPUTE = "S8_DISPUTE"
    S9_INTENT = "S9_INTENT"
    S10_CROSS_CHAIN = "S10_CROSS_CHAIN"


# ── Receipt Status ────────────────────────────────────────────────────────────


class ReceiptStatus(str, Enum):
    """Lifecycle of a single UniversalReceipt."""

    GENERATED = "GENERATED"
    ANCHORING = "ANCHORING"
    ANCHORED = "ANCHORED"
    VERIFIED = "VERIFIED"


# ── Receipt Types (40+) ───────────────────────────────────────────────────────


class ReceiptType(str, Enum):
    """Every receipt kind recognised by the billing layer, grouped by scenario.

    Each constant is structured as ``SCENARIO_KIND`` for easy filtering.
    """

    # ── S1: Single Delegation ──
    S1_INTENT_CREATED = "S1_INTENT_CREATED"
    S1_INTENT_SIGNED = "S1_INTENT_SIGNED"
    S1_DELEGATION_ACCEPTED = "S1_DELEGATION_ACCEPTED"
    S1_TASK_STARTED = "S1_TASK_STARTED"
    S1_STEP_EXECUTED = "S1_STEP_EXECUTED"
    S1_TASK_COMPLETED = "S1_TASK_COMPLETED"
    S1_INVOICE_GENERATED = "S1_INVOICE_GENERATED"
    S1_PAYMENT_AUTHORIZED = "S1_PAYMENT_AUTHORIZED"
    S1_PAYMENT_SETTLED = "S1_PAYMENT_SETTLED"
    S1_RECEIPT_FINAL = "S1_RECEIPT_FINAL"

    # ── S2: Bidding / Auction ──
    S2_BID_OPENED = "S2_BID_OPENED"
    S2_BID_PLACED = "S2_BID_PLACED"
    S2_BID_EVALUATED = "S2_BID_EVALUATED"
    S2_BID_ACCEPTED = "S2_BID_ACCEPTED"
    S2_TASK_EXECUTED = "S2_TASK_EXECUTED"
    S2_INVOICE_GENERATED = "S2_INVOICE_GENERATED"
    S2_PAYMENT_SETTLED = "S2_PAYMENT_SETTLED"

    # ── S3: Pipeline ──
    S3_PIPELINE_CREATED = "S3_PIPELINE_CREATED"
    S3_STAGE_STARTED = "S3_STAGE_STARTED"
    S3_STAGE_COMPLETED = "S3_STAGE_COMPLETED"
    S3_PIPELINE_COMPLETED = "S3_PIPELINE_COMPLETED"
    S3_INVOICE_AGGREGATED = "S3_INVOICE_AGGREGATED"
    S3_PAYMENT_SETTLED = "S3_PAYMENT_SETTLED"

    # ── S4: Multi-Delegation ──
    S4_SUBTASK_CREATED = "S4_SUBTASK_CREATED"
    S4_SUBTASK_ASSIGNED = "S4_SUBTASK_ASSIGNED"
    S4_SUBTASK_COMPLETED = "S4_SUBTASK_COMPLETED"
    S4_AGGREGATE_INVOICE = "S4_AGGREGATE_INVOICE"
    S4_PAYMENT_SETTLED = "S4_PAYMENT_SETTLED"

    # ── S5: Data Marketplace ──
    S5_DATA_REQUESTED = "S5_DATA_REQUESTED"
    S5_DATA_DELIVERED = "S5_DATA_DELIVERED"
    S5_DATA_VERIFIED = "S5_DATA_VERIFIED"
    S5_ROYALTY_CALCULATED = "S5_ROYALTY_CALCULATED"
    S5_PAYMENT_SETTLED = "S5_PAYMENT_SETTLED"

    # ── S6: Conditional ──
    S6_CONDITION_SET = "S6_CONDITION_SET"
    S6_CONDITION_MET = "S6_CONDITION_MET"
    S6_TASK_EXECUTED = "S6_TASK_EXECUTED"
    S6_ESCROW_RELEASED = "S6_ESCROW_RELEASED"

    # ── S7: Recurring / Subscription ──
    S7_SUBSCRIPTION_CREATED = "S7_SUBSCRIPTION_CREATED"
    S7_PERIOD_STARTED = "S7_PERIOD_STARTED"
    S7_USAGE_REPORTED = "S7_USAGE_REPORTED"
    S7_PERIOD_INVOICE = "S7_PERIOD_INVOICE"
    S7_PAYMENT_SETTLED = "S7_PAYMENT_SETTLED"

    # ── S8: Dispute / Resolution ──
    S8_DISPUTE_FILED = "S8_DISPUTE_FILED"
    S8_EVIDENCE_SUBMITTED = "S8_EVIDENCE_SUBMITTED"
    S8_ARBITRATION_STARTED = "S8_ARBITRATION_STARTED"
    S8_RESOLUTION_PROPOSED = "S8_RESOLUTION_PROPOSED"
    S8_RESOLUTION_ACCEPTED = "S8_RESOLUTION_ACCEPTED"
    S8_REFUND_ISSUED = "S8_REFUND_ISSUED"

    # ── S9: Intent-Based ──
    S9_INTENT_EXPRESSED = "S9_INTENT_EXPRESSED"
    S9_SOLVER_MATCHED = "S9_SOLVER_MATCHED"
    S9_SOLUTION_EXECUTED = "S9_SOLUTION_EXECUTED"
    S9_PAYMENT_SETTLED = "S9_PAYMENT_SETTLED"

    # ── S10: Cross-Chain ──
    S10_SOURCE_LOCKED = "S10_SOURCE_LOCKED"
    S10_BRIDGE_PROOF = "S10_BRIDGE_PROOF"
    S10_DESTINATION_MINTED = "S10_DESTINATION_MINTED"
    S10_PAYMENT_SETTLED = "S10_PAYMENT_SETTLED"


# ── Billing State ─────────────────────────────────────────────────────────────


class BillingState(str, Enum):
    """17-state lifecycle for a billing task.

    Every task transitions through a subset of these states.
    Illegal transitions are rejected by ImmutableBillingStateMachine.
    """

    INITIATED = "INITIATED"
    INTENT_RECEIVED = "INTENT_RECEIVED"
    INTENT_VALIDATED = "INTENT_VALIDATED"
    DELEGATION_ACCEPTED = "DELEGATION_ACCEPTED"
    TASK_STARTED = "TASK_STARTED"
    STEP_IN_PROGRESS = "STEP_IN_PROGRESS"
    STEP_COMPLETED = "STEP_COMPLETED"
    TASK_COMPLETED = "TASK_COMPLETED"
    BID_EVALUATING = "BID_EVALUATING"
    BID_ACCEPTED = "BID_ACCEPTED"
    PIPELINE_STAGING = "PIPELINE_STAGING"
    INVOICE_GENERATED = "INVOICE_GENERATED"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_SETTLING = "PAYMENT_SETTLING"
    REFUND_PENDING = "REFUND_PENDING"
    SETTLED = "SETTLED"


# ── Helper Functions ──────────────────────────────────────────────────────────


def compute_payload_hash(data: dict[str, Any]) -> str:
    """Compute deterministic payload hash using canonical JSON (sort_keys).

    用于 payload_hash 字段：通过 SHA256(canonical_json_bytes) 生成确定性哈希，
    确保相同逻辑内容总是产生相同哈希值。
    """
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_leaf_hash(
    receipt_id: str,
    task_id: str,
    step_index: int,
    payload_hash: str,
    timestamp: str,
) -> bytes:
    """Compute Merkle-tree leaf hash for a receipt.

    Formula: SHA256(receipt_id | task_id | step_index | payload_hash | timestamp)

    Returns raw bytes suitable for inclusion in an IncrementalMerkleAccumulator.
    """
    parts = [
        receipt_id,
        task_id,
        str(step_index),
        payload_hash,
        timestamp,
    ]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).digest()


# ── UniversalReceipt ──────────────────────────────────────────────────────────


class UniversalReceipt(BaseModel):
    """The canonical invoice/receipt record for every billing event.

    This is the single source of truth — every action (delegation, step
    execution, payment, dispute, …) produces exactly one UniversalReceipt
    which flows through the three-route sync pipeline:

    1.  PostgreSQL INSERT (async, persistent)
    2.  Redis Pub/Sub (real-time notification)
    3.  IncrementalMerkleAccumulator (cryptographic anchoring)
    """

    receipt_id: str = Field(..., description="Unique receipt identifier (UUIDv7)")
    task_id: str = Field(..., description="Parent billing task id")
    scenario: ScenarioType = Field(..., description="Which scenario this belongs to")
    step_index: int = Field(ge=0, description="Zero-based step index within the task")

    # DIDs
    generator_did: str = Field(..., description="DID of the Agent that generated this receipt")
    buyer_did: str = Field(..., description="DID of the buyer/requester")
    seller_did: str = Field(..., description="DID of the seller/provider")

    # Receipt metadata
    receipt_type: ReceiptType = Field(..., description="What kind of event this receipt records")
    input_hash: str = Field(..., description="SHA256 hash of task input at this step")
    output_hash: str = Field(..., description="SHA256 hash of task output at this step")
    payload_hash: str = Field(
        default="",
        description="SHA256 of canonical JSON of scenario-specific payload data",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this receipt was created",
    )
    execution_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Execution duration of this step in milliseconds",
    )

    # Chain linking
    parent_receipt_id: Optional[str] = Field(
        default=None,
        description="Immediate parent receipt id for causal chain",
    )
    previous_payload_hash: Optional[str] = Field(
        default=None,
        description="payload_hash of the previous receipt in the chain",
    )

    # Scenario-specific extensibility
    scenario_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Free-form scenario-specific payload (must be JSON-serialisable)",
    )

    # Anchoring status
    status: ReceiptStatus = Field(
        default=ReceiptStatus.GENERATED,
        description="Current anchoring / verification status",
    )
    signature: str = Field(default="", description="Digital signature over this receipt")
    signature_algorithm: str = Field(
        default="ECDSA-secp256k1",
        description="Algorithm used for signature",
    )

    # On-chain anchor
    anchor_tx: Optional[str] = Field(
        default=None,
        description="Transaction hash of on-chain anchor",
    )
    anchor_leaf_index: Optional[int] = Field(
        default=None,
        description="Index of this receipt's leaf in the Merkle tree",
    )
    anchor_root: Optional[str] = Field(
        default=None,
        description="Merkle root at the time of anchoring",
    )

    @model_validator(mode="after")
    def _auto_compute_payload_hash(self) -> "UniversalReceipt":
        """If payload_hash is empty and scenario_data is provided, auto-compute it."""
        if self.payload_hash == "" and self.scenario_data is not None:
            object.__setattr__(self, "payload_hash", compute_payload_hash(self.scenario_data))
        return self

    def compute_leaf(self) -> bytes:
        """Compute the Merkle leaf hash for this receipt."""
        return compute_leaf_hash(
            receipt_id=self.receipt_id,
            task_id=self.task_id,
            step_index=self.step_index,
            payload_hash=self.payload_hash or compute_payload_hash(self.scenario_data or {}),
            timestamp=self.created_at.isoformat(),
        )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


# ── BillingSnapshot ───────────────────────────────────────────────────────────


class BillingSnapshot(BaseModel):
    """Point-in-time summary of a billing task's state.

    Designed for real-time dashboards and WebSocket push events.
    """

    task_id: str
    scenario: ScenarioType
    billing_state: BillingState
    current_step: int = 0
    total_steps_estimated: int = 0
    cost_accrued_usdc: float = 0.0
    total_budget_usdc: float = 0.0
    progress_percent: float = 0.0
    anchored_receipts: int = 0
    latest_merkle_root: Optional[str] = None
    last_anchor_tx: Optional[str] = None


# ── StateTransitionRecord ─────────────────────────────────────────────────────


class StateTransitionRecord(BaseModel):
    """Immutable record of a single state transition.

    Each transition is INSERT-only.  No UPDATE/DELETE is ever performed on
    historical records — enforced by database triggers and application logic.
    """

    record_id: str = Field(..., description="Unique transition record id (UUID)")
    task_id: str
    from_state: BillingState
    to_state: BillingState
    triggered_by_receipt_id: str
    triggered_by_did: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
