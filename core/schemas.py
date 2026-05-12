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


class ArbitrationCaseStatus(str, Enum):
    OPEN = "open"
    VOTING = "voting"
    DECIDED = "decided"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


class ArbitrationVoteDecision(str, Enum):
    BUYER_WINS = "buyer_wins"
    SELLER_WINS = "seller_wins"
    PARTIAL = "partial"


class ArbitrationEventType(str, Enum):
    CASE_CREATED = "case_created"
    ARBITRATORS_ASSIGNED = "arbitrators_assigned"
    MATERIAL_SUBMITTED = "material_submitted"
    VOTE_CAST = "vote_cast"
    CASE_DECIDED = "case_decided"
    CASE_EXECUTED = "case_executed"


class ResponsibilityEdgeType(str, Enum):
    VOUCHER_ACCEPT = "voucher_accept"
    TASK_DELEGATION = "task_delegation"
    MANUAL_LINK = "manual_link"


class ResponsibilitySignalType(str, Enum):
    DIRECT_LOOP = "direct_loop"
    MUTUAL_EXCHANGE = "mutual_exchange"
    CYCLE_AUTHORIZATION = "cycle_authorization"


class ResponsibilitySignalSeverity(str, Enum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"


class ResponsibilityScoreBand(str, Enum):
    LOW = "low"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class ResponsibilityScanRunStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class ResponsibilityScanMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


class ResponsibilityScanExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"


class TemporalConsistencyIssueType(str, Enum):
    EDGE_TYPE_OUT_OF_ORDER = "edge_type_out_of_order"
    DUPLICATE_DIRECTION_BURST = "duplicate_direction_burst"
    MISSING_ANCHOR_EDGE = "missing_anchor_edge"


class ExplainableRiskReportTarget(str, Enum):
    IDENTITY = "identity"
    TASK = "task"


class ReportSignatureStatus(str, Enum):
    UNSIGNED = "unsigned"
    PROVIDED = "provided"
    VERIFIED = "verified"
    INVALID = "invalid"


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


class ArbitrationPoolMemberStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ArbitrationPoolMember(BaseModel):
    arbitrator_identity_id: str
    stake_amount: float = Field(ge=0.0)
    status: ArbitrationPoolMemberStatus = ArbitrationPoolMemberStatus.ACTIVE
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ArbitrationCase(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    settlement_id: Optional[str] = None
    opened_by: str
    reason: Optional[str] = None
    status: ArbitrationCaseStatus = ArbitrationCaseStatus.OPEN
    required_arbitrators: int = Field(default=3, ge=1, le=21)
    decided_outcome: Optional[ArbitrationVoteDecision] = None
    final_partial_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None


class ArbitrationAssignment(BaseModel):
    assignment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    arbitrator_identity_id: str
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "assigned"


class ArbitrationMaterialPackage(BaseModel):
    material_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    task_id: str
    submitted_by: str
    bundle_id: Optional[str] = None
    progress_receipt_ids: list[str] = Field(default_factory=list)
    evidence_hashes: list[str] = Field(default_factory=list)
    package_hash: str
    storage_uri: Optional[str] = None
    format_version: str = "arbitration-material-v1"
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


class ArbitrationVote(BaseModel):
    vote_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    arbitrator_identity_id: str
    decision: ArbitrationVoteDecision
    partial_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    rationale: Optional[str] = None
    voted_at: datetime = Field(default_factory=datetime.utcnow)


class ArbitrationCaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    event_type: ArbitrationEventType
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ArbitrationOpsAlertSeverity(str, Enum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"


class ArbitrationOpsAlertType(str, Enum):
    OPEN_CASE_BACKLOG = "open_case_backlog"
    VOTING_CASE_BACKLOG = "voting_case_backlog"
    DECISION_TIMEOUT_RISK = "decision_timeout_risk"
    DECISION_PARTIAL_SPIKE = "decision_partial_spike"


class ArbitrationOpsAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: ArbitrationOpsAlertSeverity
    alert_type: ArbitrationOpsAlertType
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ArbitrationArbitratorActivitySummary(BaseModel):
    arbitrator_identity_id: str
    assigned_count: int = 0
    vote_count: int = 0
    last_assigned_at: Optional[datetime] = None
    last_voted_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None


class ArbitrationOverdueStage(str, Enum):
    OPEN = "open"
    VOTING = "voting"
    DECIDED_PENDING_EXECUTION = "decided_pending_execution"


class ArbitrationCaseOverdueItem(BaseModel):
    case_id: str
    task_id: str
    status: ArbitrationCaseStatus
    opened_by: str
    decided_outcome: Optional[ArbitrationVoteDecision] = None
    overdue_stage: ArbitrationOverdueStage
    age_hours: float = 0.0
    threshold_hours: int
    created_at: datetime
    updated_at: datetime


class ArbitrationCaseOpsReport(BaseModel):
    window_hours: int
    total_cases: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    decision_counts: dict[str, int] = Field(default_factory=dict)
    recent_events: list[ArbitrationCaseEvent] = Field(default_factory=list)
    alerts: list[ArbitrationOpsAlert] = Field(default_factory=list)
    arbitrator_activity: list[ArbitrationArbitratorActivitySummary] = Field(default_factory=list)
    overdue_cases: list[ArbitrationCaseOverdueItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class SecurityOpsAlertSeverity(str, Enum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityOpsAlertType(str, Enum):
    AUTH_FAILURE_SPIKE = "auth_failure_spike"
    RATE_LIMIT_SPIKE = "rate_limit_spike"
    PRIVATE_RUNTIME_ERROR_RATE = "private_runtime_error_rate"
    AUTH_FAILURE_BASELINE_DRIFT = "auth_failure_baseline_drift"
    RATE_LIMIT_BASELINE_DRIFT = "rate_limit_baseline_drift"
    PRIVATE_RUNTIME_ERROR_BASELINE_DRIFT = "private_runtime_error_baseline_drift"


class SecurityOpsAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: SecurityOpsAlertSeverity
    alert_type: SecurityOpsAlertType
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class SecurityOpsDimensionCount(BaseModel):
    key: str
    count: int = 0
    last_seen_at: Optional[datetime] = None


class SecurityOpsEscalationLevel(str, Enum):
    NONE = "none"
    WATCH = "watch"
    PAGE = "page"


class SecurityOpsEscalationDecision(BaseModel):
    level: SecurityOpsEscalationLevel = SecurityOpsEscalationLevel.NONE
    reason: str = "no escalation"
    trigger_alert_types: list[SecurityOpsAlertType] = Field(default_factory=list)


class SecurityOpsSummary(BaseModel):
    failed_auth_count: int = 0
    rate_limited_count: int = 0
    private_runtime_error_count: int = 0
    verify_request_count: int = 0
    private_runtime_error_rate: float = 0.0
    failed_auth_by_path: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    failed_auth_by_actor: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    failed_auth_by_route_group: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    rate_limited_by_path: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    rate_limited_by_actor: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    rate_limited_by_route_group: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    private_runtime_error_by_path: list[SecurityOpsDimensionCount] = Field(default_factory=list)
    private_runtime_error_by_route_group: list[SecurityOpsDimensionCount] = Field(default_factory=list)


class SecurityOpsBaselineReference(BaseModel):
    sample_count: int = 0
    baseline_window_minutes: int = 0
    failed_auth_avg: float = 0.0
    rate_limited_avg: float = 0.0
    private_runtime_error_rate_avg: float = 0.0


class SecurityThresholdPolicyStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CANDIDATE = "candidate"
    ARCHIVED = "archived"


class SecurityThresholdPolicy(BaseModel):
    policy_id: str
    version: int
    status: SecurityThresholdPolicyStatus
    rollout_percent: int = 100
    config: dict[str, Any] = Field(default_factory=dict)
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    activated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    parent_policy_id: Optional[str] = None


class SecurityThresholdPolicyResolveResult(BaseModel):
    policy: Optional[SecurityThresholdPolicy] = None
    matched_candidate: bool = False
    actor_id: Optional[str] = None
    reason: str = "no_policy"


class SecurityOpsAlertReport(BaseModel):
    window_minutes: int
    summary: SecurityOpsSummary
    alerts: list[SecurityOpsAlert] = Field(default_factory=list)
    suppressed_alert_count: int = 0
    baseline: SecurityOpsBaselineReference = Field(default_factory=SecurityOpsBaselineReference)
    policy_id: Optional[str] = None
    policy_version: Optional[int] = None
    policy_status: Optional[SecurityThresholdPolicyStatus] = None
    matched_candidate: bool = False
    escalation: SecurityOpsEscalationDecision = Field(default_factory=SecurityOpsEscalationDecision)
    recommended_actions: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class MCPVerificationTemplate(BaseModel):
    template_version: str = "mcp-v2"
    mcp_server_id: str
    tool_name: str
    input_schema_hash: str
    output_schema_hash: str
    prompt_hash: Optional[str] = None
    constraints_hash: Optional[str] = None
    runtime_receipt_hash: Optional[str] = None


class ResponsibilityEdge(BaseModel):
    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    edge_hash: str
    source_identity_id: str
    target_identity_id: str
    edge_type: ResponsibilityEdgeType = ResponsibilityEdgeType.MANUAL_LINK
    task_id: Optional[str] = None
    voucher_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityRiskSignal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    signal_type: ResponsibilitySignalType
    severity: ResponsibilitySignalSeverity
    identity_id: str
    edge_hash: str
    related_edge_hashes: list[str] = Field(default_factory=list)
    task_id: Optional[str] = None
    detail: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityEdgeIngestResult(BaseModel):
    edge: ResponsibilityEdge
    signals: list[ResponsibilityRiskSignal] = Field(default_factory=list)


class TaskPathHashSummary(BaseModel):
    task_id: str
    edge_hashes: list[str] = Field(default_factory=list)
    path_hash: Optional[str] = None


class ResponsibilityScoreSummary(BaseModel):
    identity_id: str
    window_hours: int
    model_version: str = "public-risk-v1"
    weighted_points: float = 0.0
    normalized_score: float = 0.0
    signal_count: int = 0
    signal_type_counts: dict[str, int] = Field(default_factory=dict)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    risk_band: ResponsibilityScoreBand = ResponsibilityScoreBand.LOW
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityPublicRiskModel(BaseModel):
    model_version: str = "public-risk-v1"
    time_window_rule: str = "include signals in now-window_hours to now"
    severity_weights: dict[str, float]
    signal_type_weights: dict[str, float]
    recency_floor: float
    public_band_reference: dict[str, float]


class ResponsibilityPathFeaturesSummary(BaseModel):
    identity_id: str
    window_hours: int
    max_hops: int
    traversed_edge_count: int = 0
    reachable_identity_count: int = 0
    cycle_paths_detected: int = 0
    path_hashes_sample: list[str] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityScanFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scan_id: str
    identity_id: str
    normalized_score: float
    risk_band: ResponsibilityScoreBand
    signal_count: int
    cycle_paths_detected: int
    detail: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityScanEventType(str, Enum):
    CREATED = "created"
    CLAIMED = "claimed"
    HEARTBEAT = "heartbeat"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"
    STALE_RECOVERED = "stale_recovered"
    DEAD_LETTERED = "dead_lettered"
    REQUEUED = "requeued"


class ResponsibilityScanRunEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scan_id: str
    event_type: ResponsibilityScanEventType
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityBatchScanRun(BaseModel):
    scan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: ResponsibilityScanRunStatus = ResponsibilityScanRunStatus.PENDING
    execution_mode: ResponsibilityScanExecutionMode = ResponsibilityScanExecutionMode.SYNC
    scan_mode: ResponsibilityScanMode = ResponsibilityScanMode.FULL
    base_scan_id: Optional[str] = None
    incremental_since_at: Optional[datetime] = None
    requested_identity_ids: Optional[list[str]] = None
    window_hours: int = 24
    max_hops: int = 4
    min_score_threshold: float = 8.0
    retry_max_attempts: int = 3
    retry_backoff_seconds: int = 30
    current_attempt: int = 0
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    lease_expires_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    last_error: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    dead_lettered_at: Optional[datetime] = None
    dead_letter_reason: Optional[str] = None
    total_identities: int = 0
    flagged_identities: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ResponsibilityBatchScanResult(BaseModel):
    run: ResponsibilityBatchScanRun
    findings: list[ResponsibilityScanFinding] = Field(default_factory=list)


class ResponsibilityScanQueueStats(BaseModel):
    total_runs: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    claimable_pending: int = 0
    claimable_failed: int = 0
    dead_letter_count: int = 0
    stale_claimed: int = 0
    stale_running: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityRecoverStaleRunsResult(BaseModel):
    limit: int
    scanned_count: int
    recovered_count: int
    recovered_scan_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityWorkerPullExecuteOutcome(str, Enum):
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"


class ResponsibilityWorkerPullExecuteResult(BaseModel):
    runner_identity_id: str
    outcome: ResponsibilityWorkerPullExecuteOutcome
    claimed_scan_id: Optional[str] = None
    run: Optional[ResponsibilityBatchScanRun] = None
    message: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityQueueMaintenanceTickResult(BaseModel):
    runner_identity_id: str
    recover_limit: int
    max_claim_execute: int
    recovered_count: int = 0
    recovered_scan_ids: list[str] = Field(default_factory=list)
    claimed_count: int = 0
    executed_count: int = 0
    failed_count: int = 0
    executed_scan_ids: list[str] = Field(default_factory=list)
    failed_scan_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityDeadLetterSweepResult(BaseModel):
    limit: int
    scanned_count: int
    dead_lettered_count: int
    dead_lettered_scan_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityDeadLetterRequeueBatchResult(BaseModel):
    limit: int
    scanned_count: int
    requeued_count: int
    requeued_scan_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityDeadLetterPurgeResult(BaseModel):
    limit: int
    older_than_hours: int
    scanned_count: int
    purged_count: int
    purged_scan_ids: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityScanFailureReasonSummary(BaseModel):
    reason: str
    count: int
    last_seen_at: Optional[datetime] = None


class ResponsibilityScanRunnerActivitySummary(BaseModel):
    runner_identity_id: str
    claimed_count: int = 0
    heartbeat_count: int = 0
    execution_started_count: int = 0
    execution_completed_count: int = 0
    execution_failed_count: int = 0
    last_event_at: Optional[datetime] = None


class ResponsibilityScanOpsAlertSeverity(str, Enum):
    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"


class ResponsibilityScanOpsAlertType(str, Enum):
    QUEUE_STALE_LEASE = "queue_stale_lease"
    QUEUE_DEAD_LETTER_PRESSURE = "queue_dead_letter_pressure"
    QUEUE_FAILURE_RATIO = "queue_failure_ratio"
    RUNNER_FAILURE_SPIKE = "runner_failure_spike"


class ResponsibilityScanOpsAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: ResponsibilityScanOpsAlertSeverity
    alert_type: ResponsibilityScanOpsAlertType
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResponsibilityScanOpsReport(BaseModel):
    window_hours: int
    total_runs: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    claimable_pending: int = 0
    claimable_failed: int = 0
    dead_letter_count: int = 0
    stale_claimed: int = 0
    stale_running: int = 0
    top_failure_reasons: list[ResponsibilityScanFailureReasonSummary] = Field(default_factory=list)
    recent_events: list[ResponsibilityScanRunEvent] = Field(default_factory=list)
    runner_activity: list[ResponsibilityScanRunnerActivitySummary] = Field(default_factory=list)
    alerts: list[ResponsibilityScanOpsAlert] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class TemporalConsistencyIssue(BaseModel):
    issue_type: TemporalConsistencyIssueType
    severity: ResponsibilitySignalSeverity
    detail: str
    edge_hashes: list[str] = Field(default_factory=list)


class TaskTemporalConsistencyReport(BaseModel):
    task_id: str
    total_edges: int = 0
    is_consistent: bool = True
    issues: list[TemporalConsistencyIssue] = Field(default_factory=list)
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class ReportSignaturePlaceholder(BaseModel):
    signature_scheme: str = "ed25519-public-placeholder"
    signer_identity_id: Optional[str] = None
    signature_payload_hash: str
    signature: Optional[str] = None
    status: ReportSignatureStatus = ReportSignatureStatus.UNSIGNED
    verification_note: str = "public signature verification placeholder only"


class ExplainableRiskReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target: ExplainableRiskReportTarget
    identity_id: Optional[str] = None
    task_id: Optional[str] = None
    window_hours: int = 24
    max_hops: int = 4
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    content_hash: str
    score_summary: Optional[ResponsibilityScoreSummary] = None
    path_features: Optional[ResponsibilityPathFeaturesSummary] = None
    task_path_summary: Optional[TaskPathHashSummary] = None
    temporal_consistency: Optional[TaskTemporalConsistencyReport] = None
    top_signals: list[ResponsibilityRiskSignal] = Field(default_factory=list)
    findings_excerpt: list[ResponsibilityScanFinding] = Field(default_factory=list)
    signature: Optional[ReportSignaturePlaceholder] = None


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
