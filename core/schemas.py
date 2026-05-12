"""
Karma Trust Protocol — Public Schemas
======================================
These are the canonical data structures for integrating with the
Karma Trusted Agent Runtime.

All fields are documented. These schemas are stable and versioned.
Integrators should build against these types.

IMPORTANT: Verification logic, scoring weights, and decision rules
are NOT part of this public module. They live in the private runtime.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Full lifecycle of a task in the Karma settlement system."""
    CREATED     = "created"      # Contract signed, escrow not yet locked
    LOCKED      = "locked"       # Escrow locked, worker accepted
    RUNNING     = "running"      # Agent is executing
    PROGRESS_SUBMITTED = "progress_submitted"  # Seller submitted progress receipt
    PROGRESS_CONFIRMED = "progress_confirmed"  # Progress receipt confirmed
    SUBMITTED   = "submitted"    # Agent submitted evidence bundle
    BUYER_REGRET = "buyer_regret"  # Buyer ended task with progress liability
    VERIFYING   = "verifying"    # Verification engine running
    VERIFIED    = "verified"     # Passed verification
    RELEASED    = "released"     # Escrow released to worker ✅
    FAILED      = "failed"       # Execution failure
    DISPUTED    = "disputed"     # Dispute raised
    ARBITRATION = "arbitration"  # Under human/AI arbitration
    BUYER_WINS  = "buyer_wins"   # Refund to client
    SELLER_WINS = "seller_wins"  # Full release to worker
    PARTIAL     = "partial"      # Split settlement
    REFUNDED    = "refunded"     # Full refund to client


class ToolStatus(str, Enum):
    """Result status of a single tool execution step."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class AgentRole(str, Enum):
    """Role of an agent in the Karma network."""
    CLIENT      = "client"
    WORKER      = "worker"
    ARBITRATOR  = "arbitrator"
    VALIDATOR   = "validator"


class VerificationDecision(str, Enum):
    """
    Output of the Verification Engine.
    Exact logic for each decision is private.
    """
    RELEASE = "release"  # Release escrow to worker
    HOLD    = "hold"     # Flag for manual review
    REFUND  = "refund"   # Return escrow to client
    DISPUTE = "dispute"  # Route to arbitration


class VoucherStatus(str, Enum):
    """Lifecycle of an authorization voucher."""
    CREATED = "created"
    ACCEPTED = "accepted"
    USED = "used"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ProgressConfirmationStatus(str, Enum):
    """Confirmation status for a submitted progress receipt."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class SubIdentityType(str, Enum):
    BUYER = "buyer"
    SELLER = "seller"
    AGENT = "agent"
    PROJECT = "project"
    TEMPORARY_TASK = "temporary_task"


class SubIdentityStatus(str, Enum):
    ACTIVE = "active"
    DELETED = "deleted"


# ---------------------------------------------------------------------------
# Task Contract
# ---------------------------------------------------------------------------

class TaskContract(BaseModel):
    """
    Immutable agreement between client and worker before execution begins.
    This is hashed and embedded into every evidence bundle.
    """
    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique task identifier (UUID v4)",
    )
    client_agent_id: str = Field(description="Agent ID of the task requester")
    worker_agent_id: Optional[str] = Field(
        default=None, description="Agent ID of the assigned worker"
    )
    title: str = Field(description="Short human-readable task title")
    description: str = Field(description="Full task specification")
    expected_output_schema: dict[str, Any] = Field(
        description="JSON schema defining expected output format"
    )
    expected_step_count: int = Field(
        ge=1, description="Approximate number of tool steps required"
    )
    escrow_amount: float = Field(ge=0.0, description="Amount held in escrow")
    currency: str = Field(default="USD")
    deadline_at: datetime = Field(description="Hard deadline for task completion")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    contract_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 of canonical JSON — set by runtime on creation",
    )


# ---------------------------------------------------------------------------
# Execution Receipt
# ---------------------------------------------------------------------------

class ExecutionReceipt(BaseModel):
    """
    Signed record of a single tool call during agent execution.
    Generated automatically by the KarmaHookLayer.

    Receipts are the atomic unit of verifiable proof.
    """
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = Field(description="Parent task this receipt belongs to")
    agent_id: str = Field(description="Agent that executed this step")
    step_index: int = Field(ge=1, description="Sequential step number (1-based)")
    tool_name: str = Field(description="Name of the tool that was called")
    input_hash: str = Field(description="SHA-256 of the tool input payload")
    output_hash: str = Field(description="SHA-256 of the tool output payload")
    started_at: datetime
    ended_at: datetime
    duration_ms: int = Field(ge=0, description="Wall-clock execution time in ms")
    status: ToolStatus
    error_message: Optional[str] = Field(
        default=None, description="Error detail if status is FAILURE or TIMEOUT"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    signature: Optional[str] = Field(
        default=None,
        description="Ed25519 signature over canonical receipt fields",
    )


# ---------------------------------------------------------------------------
# Progress Receipt
# ---------------------------------------------------------------------------

class ProgressReceipt(BaseModel):
    """Progress evidence used for regret liability and partial settlement."""
    progress_receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    seller_identity_id: str
    progress_percent: float = Field(ge=0.0, le=100.0)
    claimed_value_percent: float = Field(ge=0.0, le=100.0)
    evidence_hash: str
    runtime_log_hash: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    seller_signature: str
    validation_method: str
    confirmation_status: ProgressConfirmationStatus = ProgressConfirmationStatus.PENDING
    confirmed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Evidence Bundle
# ---------------------------------------------------------------------------

class EvidenceBundle(BaseModel):
    """
    Aggregated proof package submitted after task completion.
    Contains all receipt hashes and is signed by the worker agent.

    Submitted to the Verification Engine for settlement decision.
    """
    bundle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    task_contract_hash: str = Field(description="SHA-256 of the original TaskContract")
    receipt_ids: list[str] = Field(description="Ordered list of ExecutionReceipt IDs")
    receipt_hashes: list[str] = Field(description="SHA-256 hash of each receipt (same order)")
    final_result_hash: str = Field(description="SHA-256 of the final task output")
    total_steps: int
    successful_steps: int
    failed_steps: int
    total_duration_ms: int
    agent_signature: Optional[str] = Field(
        default=None,
        description="Ed25519 signature by the worker agent over bundle payload",
    )
    storage_path: Optional[str] = Field(
        default=None, description="Object store path (MinIO/S3) for full bundle"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    settlement_status: TaskStatus = Field(default=TaskStatus.SUBMITTED)


# ---------------------------------------------------------------------------
# Verification Result
# ---------------------------------------------------------------------------

class VerificationCheck(BaseModel):
    """Result of a single named verification rule."""
    name: str
    passed: bool
    detail: Optional[str] = None


class VerificationResult(BaseModel):
    """
    Output of the Verification Engine.
    Decision logic is private — only the result is exposed here.
    """
    verification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    bundle_id: str
    decision: VerificationDecision
    confidence: float = Field(ge=0.0, le=1.0, description="0.0–1.0 confidence in decision")
    checks: list[VerificationCheck] = Field(
        description="List of individual checks run (names only, no weights)"
    )
    notes: Optional[str] = None
    verified_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Settlement State
# ---------------------------------------------------------------------------

class SettlementState(BaseModel):
    """Current settlement lifecycle state for a task."""
    settlement_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    escrow_amount: float
    currency: str = "USD"
    status: TaskStatus = TaskStatus.CREATED
    client_agent_id: str
    worker_agent_id: Optional[str] = None
    released_amount: Optional[float] = None
    refunded_amount: Optional[float] = None
    dispute_reason: Optional[str] = None
    arbitration_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    released_at: Optional[datetime] = None

    # On-chain fields — populated when settlement_mode != "offchain"
    settlement_mode: str = Field(default="offchain", description="offchain | testnet | hybrid")
    chain_id: Optional[int] = None
    contract_address: Optional[str] = None
    tx_hash: Optional[str] = Field(default=None, description="On-chain settlement transaction hash")
    evidence_bundle_hash: Optional[str] = Field(default=None, description="keccak256 of evidence bundle submitted on-chain")
    onchain_status: Optional[str] = Field(default=None, description="pending | confirmed | failed")
    quote_id: Optional[str] = Field(default=None, description="EIP-712 quoteId used in settlement tx")


# ---------------------------------------------------------------------------
# Capacity & Voucher
# ---------------------------------------------------------------------------

class CapacityState(BaseModel):
    """USDC-anchored bill credit capacity for one identity."""
    identity_id: str
    total_locked_usdc: float = 0.0
    total_bill_credits: float = 0.0
    available_credits: float = 0.0
    reserved_credits: float = 0.0
    in_progress_credits: float = 0.0
    confirmed_progress_credits: float = 0.0
    disputed_credits: float = 0.0
    pending_settlement_credits: float = 0.0
    burned_credits: float = 0.0
    released_credits: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def active_credits(self) -> float:
        return (
            self.available_credits
            + self.reserved_credits
            + self.in_progress_credits
            + self.confirmed_progress_credits
            + self.disputed_credits
            + self.pending_settlement_credits
        )


class AuthorizationVoucher(BaseModel):
    """One-time buyer authorization for a seller-bound task."""
    voucher_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    buyer_identity_id: str
    seller_identity_id: str
    amount: float = Field(gt=0.0)
    currency: str = Field(default="USDC")
    bill_credit_amount: float = Field(gt=0.0)
    task_type: str
    task_description_hash: str
    progress_rule_hash: str
    evidence_requirement_hash: str
    expiry_time: datetime
    nonce: str
    buyer_signature: str
    status: VoucherStatus = VoucherStatus.CREATED
    buyer_sub_identity_id: Optional[str] = None
    seller_sub_identity_id: Optional[str] = None
    accepted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class VoucherVerificationResult(BaseModel):
    voucher_id: str
    is_authentic: bool
    is_expired: bool
    is_used: bool
    amount_matches: bool
    seller_matches: bool
    has_sufficient_capacity: bool
    can_start: bool
    status: VoucherStatus


# ---------------------------------------------------------------------------
# Identity Profile & Sub Identity
# ---------------------------------------------------------------------------

class IdentityProfile(BaseModel):
    identity_id: str
    display_id: str
    legal_identity_status: str = "unbound"
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SubIdentity(BaseModel):
    sub_identity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_identity_id: str
    sub_identity_type: SubIdentityType
    alias: str
    status: SubIdentityStatus = SubIdentityStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Agent Identity
# ---------------------------------------------------------------------------

class AgentIdentity(BaseModel):
    """A registered agent in the Karma network."""
    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: AgentRole
    public_key: str = Field(description="Ed25519 public key, base64-encoded")
    endpoint_url: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


# ---------------------------------------------------------------------------
# Reputation Snapshot (public view)
# ---------------------------------------------------------------------------

class ReputationSnapshot(BaseModel):
    """
    Public-facing reputation record for an agent.
    Score algorithm is private. Only derived stats are exposed.
    """
    agent_id: str
    role: AgentRole
    score: float = Field(description="Composite reputation score (higher is better)")
    total_tasks: int
    successful_tasks: int
    disputed_tasks: int
    success_rate: float = Field(ge=0.0, le=1.0)
    last_updated: datetime
