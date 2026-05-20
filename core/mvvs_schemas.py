"""
MVVS V1 — Karma Minimum Viable Verification Standard Schemas
==============================================================
These are AGGREGATION / ENRICHMENT schemas that sit *on top* of the
existing chain schemas. They do NOT modify core.schemas or the trade pipeline.

Purpose:
  - Provide a unified view of all 28 MVVS universal fields
  - Define scene-specific minimum verification payloads
  - Bridge between the existing chain and the MVVS standard

Usage:
  from core.mvvs_schemas import TradeRecord, ApiCallEvidence, ...
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.schemas import RejectionReason, TaskStatus


# ---------------------------------------------------------------------------
# Service Type enum (MVVS scene classification)
# ---------------------------------------------------------------------------

class ServiceType(str, Enum):
    """MVVS V1 — Registered service types for task decomposition."""
    API_CALL = "api.call"
    MCP_TOOL = "mcp.tool"
    DATA_SERVICE = "data.service"
    AI_TEXT = "ai.text"
    AI_IMAGE = "ai.image"
    AI_VIDEO = "ai.video"
    AI_CODE = "ai.code"
    AI_REPORT = "ai.report"
    CHAIN_READ = "chain.read"
    CHAIN_WRITE = "chain.write"
    AGENT_SUBTASK = "agent.subtask"
    GENERIC = "generic"


class PaymentMode(str, Enum):
    MANUAL = "manual"
    PREAUTH = "preauth"


class DeliveryRuleType(str, Enum):
    """MVVS V1 — Supported delivery rule strategies."""
    AUTO_SETTLE = "auto_settle"
    BUYER_CONFIRM = "buyer_confirm"
    TIME_AUTO_CONFIRM = "time_auto_confirm"
    MANUAL_ONLY = "manual_only"


class RiskLevel(str, Enum):
    """MVVS V1 — Risk tier for testnet rollout."""
    L1 = "L1"  # Low risk, auto-settle (API, MCP)
    L2 = "L2"  # Medium risk, confirm period (data, AI content)
    L3 = "L3"  # High risk, dispute mechanism (A2A, chain ops)
    L4 = "L4"  # Extreme risk, not open (OTC, etc.)


# ---------------------------------------------------------------------------
# TradeRecord — MVVS Universal 28-field aggregate
# ---------------------------------------------------------------------------

class TradeRecord(BaseModel):
    """
    MVVS V1 Universal Trade Record.

    Aggregates ALL 28 MVVS fields from across the existing schemas
    (TaskContract + Voucher + SettlementState + ExecutionReceipt)
    into a single unified view. This is a READ-THROUGH schema —
    it does not replace any existing schema, it provides a standard
    projection for verification, dashboards, and audits.
    """
    # --- Identity & Addressing (fields 1-6) ---
    task_id: str = Field(description="Unique task identifier (UUID v4)")
    order_id: Optional[str] = Field(default=None, description="Trade order ID (generated at launch)")
    buyer_wallet: Optional[str] = Field(default=None, description="Buyer wallet address (EIP-55)")
    buyer_agent_id: str = Field(description="Agent ID of the task requester")
    seller_wallet: Optional[str] = Field(default=None, description="Seller wallet address (EIP-55)")
    seller_agent_id: Optional[str] = Field(default=None, description="Agent ID of the assigned worker")

    # --- Task Specification (fields 7-11) ---
    service_type: ServiceType = Field(default=ServiceType.GENERIC, description="MVVS service type classification")
    task_description_hash: Optional[str] = Field(default=None, description="SHA-256 of task description")
    input_hash: Optional[str] = Field(default=None, description="SHA-256 of task input payload")
    price: float = Field(ge=0.0, description="Task price (escrow amount)")
    currency: str = Field(default="USDC")

    # --- Chain & Payment (fields 12-13) ---
    chain_id: Optional[int] = Field(default=None, description="Chain ID (e.g. 11155111 for Sepolia)")
    payment_mode: PaymentMode = Field(default=PaymentMode.MANUAL)

    # --- Delivery Rules (fields 14-17) ---
    delivery_rule_id: Optional[str] = Field(default=None, description="Registered delivery rule identifier")
    delivery_deadline: Optional[datetime] = Field(default=None, description="Hard deadline for delivery")
    auto_confirm_rule: Optional[DeliveryRuleType] = Field(default=None, description="Auto-confirm strategy")
    dispute_window: Optional[int] = Field(default=None, description="Dispute window in hours", ge=0)

    # --- Signatures (fields 18-19) ---
    seller_accept_signature: Optional[str] = Field(default=None, description="Seller's Ed25519 or EIP-712 acceptance signature")
    buyer_authorization_signature: Optional[str] = Field(default=None, description="Buyer's authorization signature")

    # --- Execution Timeline (fields 20-23) ---
    execution_start_time: Optional[datetime] = Field(default=None, description="Execution start timestamp (UTC)")
    execution_end_time: Optional[datetime] = Field(default=None, description="Execution end timestamp (UTC)")
    execution_status: Optional[str] = Field(default=None, description="success | failure | timeout | skipped")
    output_hash: Optional[str] = Field(default=None, description="SHA-256 of task output payload")

    # --- Evidence & Settlement (fields 24-27) ---
    evidence_bundle_hash: Optional[str] = Field(default=None, description="SHA-256 of evidence bundle")
    settlement_status: TaskStatus = Field(default=TaskStatus.DRAFT)
    dispute_status: Optional[str] = Field(default=None, description="open | voting | decided | executed | cancelled")
    final_result: Optional[str] = Field(default=None, description="settled | refunded | partially_settled | cancelled")

    # --- Responsibility (field 28) ---
    final_responsible_party: Optional[str] = Field(default=None, description="Identity ID of the ultimately responsible party")

    # --- MVVS Audit ---
    mvvs_version: str = Field(default="v1.0", description="MVVS standard version this record conforms to")
    risk_level: RiskLevel = Field(default=RiskLevel.L1, description="MVVS risk tier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Scene-Specific Evidence Schemas
# ---------------------------------------------------------------------------

class ApiCallEvidence(BaseModel):
    """
    MVVS V1 Scene 1: API / MCP Tool Call Evidence.

    Minimum fields required for auto-verification of structured API calls.
    Maps to existing ApiExecutionReceiptExtension + McpExecutionReceiptExtension.
    """
    # Identity
    request_id: str = Field(description="Unique request identifier")
    api_provider_id: Optional[str] = Field(default=None, description="API provider identity")
    caller_agent_id: str = Field(description="Agent that made the call")

    # Request / Response
    endpoint_hash: Optional[str] = Field(default=None, description="SHA-256 of endpoint URL")
    request_hash: str = Field(description="SHA-256 of request payload")
    response_hash: str = Field(description="SHA-256 of response body")
    http_status: int = Field(ge=100, le=599, description="HTTP status code")
    response_schema_hash: Optional[str] = Field(default=None, description="SHA-256 of expected response JSON schema")

    # Timing
    response_time_ms: int = Field(ge=0, le=3_600_000, description="Round-trip latency in ms")

    # Error & Billing
    error_code: Optional[str] = Field(default=None, max_length=128)
    provider_signature: Optional[str] = Field(default=None, description="Provider's Ed25519 signature over response")
    caller_signature: Optional[str] = Field(default=None, description="Caller's Ed25519 signature over request")
    unit_price: Optional[float] = Field(default=None, ge=0.0, description="Price per call unit")
    billing_count: Optional[int] = Field(default=None, ge=0, description="Number of billable units consumed")
    timeout_limit_ms: Optional[int] = Field(default=None, ge=0, description="Service-level timeout in ms")

    # MVVS auto-verify gate — computed, not stored
    def auto_pass_checks(self) -> dict[str, bool]:
        """Evaluate MVVS V1 Scene 1 auto-pass conditions."""
        return {
            "http_status_ok": self.http_status == 200,
            "response_hash_exists": bool(self.response_hash),
            "schema_match": (
                True if self.response_schema_hash is None
                else bool(self.response_hash)  # schema specified → response must exist
            ),
            "not_timed_out": (
                self.timeout_limit_ms is None
                or self.response_time_ms <= self.timeout_limit_ms
            ),
            "provider_signed": (
                True if self.provider_signature is None
                else len(self.provider_signature) >= 32
            ),
            "billing_consistent": (
                self.billing_count is None
                or self.billing_count > 0
            ),
        }

    def auto_fail_checks(self) -> dict[str, bool]:
        """Evaluate MVVS V1 Scene 1 auto-fail conditions."""
        return {
            "client_error": 400 <= self.http_status < 500,
            "server_error": self.http_status >= 500,
            "empty_response": not self.response_hash,
            "schema_break": self.response_schema_hash is not None and not self.response_hash,
            "invalid_signature": self.provider_signature is not None and len(self.provider_signature) < 32,
            "billing_mismatch": self.billing_count == 0,
            "empty_result_billed": self.billing_count is not None and self.billing_count > 0 and not self.response_hash,
        }

    def auto_verdict(self) -> str:
        """MVVS V1 auto-verdict for API/MCP calls."""
        fail = self.auto_fail_checks()
        if any(fail.values()):
            return "fail"
        pass_checks = self.auto_pass_checks()
        if all(pass_checks.values()):
            return "pass"
        return "review"


class DataServiceEvidence(BaseModel):
    """
    MVVS V1 Scene 2: Data Service Delivery Evidence.
    """
    data_source_description_hash: Optional[str] = Field(default=None)
    data_file_hash: Optional[str] = Field(default=None, description="SHA-256 of delivered data file")
    data_schema_hash: Optional[str] = Field(default=None, description="SHA-256 of expected schema")
    row_count: Optional[int] = Field(default=None, ge=0)
    column_count: Optional[int] = Field(default=None, ge=0)
    sample_preview_hash: Optional[str] = Field(default=None)
    generation_time: Optional[datetime] = Field(default=None)
    delivery_uri: Optional[str] = Field(default=None)
    seller_signature: Optional[str] = Field(default=None)
    buyer_acceptance_status: Optional[str] = Field(default="pending")
    minimum_quality_rule: Optional[str] = Field(default=None)  # JSON rule spec
    dispute_window_hours: int = Field(default=48, ge=0)
    rejection_reason: Optional[RejectionReason] = Field(default=None)
    rejection_detail: Optional[str] = Field(default=None, max_length=2000)
    revision_count: int = Field(default=0, ge=0)
    max_revisions: int = Field(default=1, ge=0)


class AiContentEvidence(BaseModel):
    """
    MVVS V1 Scene 3: AI Content Generation Evidence.
    """
    prompt_hash: Optional[str] = Field(default=None)
    buyer_requirement_hash: Optional[str] = Field(default=None)
    output_file_hash: Optional[str] = Field(default=None, description="SHA-256 of output file")
    output_format: Optional[str] = Field(default=None, description="jpg | png | mp4 | py | md | pdf | etc.")
    file_size: Optional[int] = Field(default=None, ge=0)
    # Format-specific dimensions
    word_count: Optional[int] = Field(default=None, ge=0)
    duration_seconds: Optional[int] = Field(default=None, ge=0)
    resolution: Optional[str] = Field(default=None, description="e.g. 1920x1080")
    code_lines: Optional[int] = Field(default=None, ge=0)
    page_count: Optional[int] = Field(default=None, ge=0)
    # Delivery
    delivery_uri: Optional[str] = Field(default=None)
    generation_tool_info_hash: Optional[str] = Field(default=None)
    model_version_hash: Optional[str] = Field(default=None)
    seller_signature: Optional[str] = Field(default=None)
    revision_count: int = Field(default=0, ge=0)
    max_revisions: int = Field(default=2, ge=0)
    buyer_acceptance_status: Optional[str] = Field(default="pending")
    rejection_reason: Optional[RejectionReason] = Field(default=None)
    rejection_detail: Optional[str] = Field(default=None, max_length=2000)


class ChainOpEvidence(BaseModel):
    """
    MVVS V1 Scene 4: On-Chain Operation Evidence.
    """
    chain_id: int
    tx_hash: Optional[str] = Field(default=None, description="Transaction hash")
    from_address: Optional[str] = Field(default=None)
    to_address: Optional[str] = Field(default=None)
    contract_address: Optional[str] = Field(default=None)
    method_name: Optional[str] = Field(default=None)
    calldata_hash: Optional[str] = Field(default=None)
    value: Optional[str] = Field(default=None, description="Native token value in wei")
    token_address: Optional[str] = Field(default=None)
    transaction_status: Optional[str] = Field(default=None, description="success | failed | pending")
    block_number: Optional[int] = Field(default=None, ge=0)
    confirmations: Optional[int] = Field(default=None, ge=0)
    event_logs_hash: Optional[str] = Field(default=None)
    expected_event_signature: Optional[str] = Field(default=None)
    actual_event_signature: Optional[str] = Field(default=None)
    user_signature: Optional[str] = Field(default=None)
    agent_request_hash: Optional[str] = Field(default=None)
    # Safety
    risk_address_check_result: Optional[str] = Field(default=None, description="clean | flagged | sanctioned")
    sanctions_check_result: Optional[str] = Field(default=None, description="clean | match")


class AgentSubtaskEvidence(BaseModel):
    """
    MVVS V1 Scene 5: Agent-to-Agent Subcontracting Evidence.
    """
    parent_task_id: Optional[str] = Field(default=None)
    subtask_id: str
    upstream_agent_id: str
    downstream_agent_id: str
    subtask_input_hash: Optional[str] = Field(default=None)
    subtask_output_hash: Optional[str] = Field(default=None)
    subtask_price: float = Field(ge=0.0)
    subtask_deadline: Optional[datetime] = Field(default=None)
    subtask_delivery_rule: Optional[str] = Field(default=None)
    responsibility_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    upstream_signature: Optional[str] = Field(default=None)
    downstream_signature: Optional[str] = Field(default=None)
    subtask_status: Optional[str] = Field(default=None)
    subtask_evidence_hash: Optional[str] = Field(default=None)
    final_output_binding_hash: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# MVVS Settlement Condition Validator
# ---------------------------------------------------------------------------

class MinimumSettlementConditions(BaseModel):
    """
    MVVS V1 — Minimum conditions that MUST be met before settlement.

    This is a READ-THROUGH validator, not a schema. It checks
    whether the provided TradeRecord satisfies all mandatory conditions.
    Returns a structured pass/fail with reasons.
    """
    buyer_authorization_signature_valid: bool = False
    seller_accept_signature_valid: bool = False
    input_hash_exists: bool = False
    delivery_rule_exists: bool = False
    execution_completed: bool = False
    output_hash_exists: bool = False
    evidence_bundle_hash_exists: bool = False
    no_unresolved_dispute: bool = True
    no_risk_rule_block: bool = True
    amount_within_authorization: bool = True
    settlement_address_matches_task: bool = True
    current_status_allows_settlement: bool = False

    def all_conditions_met(self) -> bool:
        """Returns True only if ALL 12 conditions are satisfied."""
        return all([
            self.buyer_authorization_signature_valid,
            self.seller_accept_signature_valid,
            self.input_hash_exists,
            self.delivery_rule_exists,
            self.execution_completed,
            self.output_hash_exists,
            self.evidence_bundle_hash_exists,
            self.no_unresolved_dispute,
            self.no_risk_rule_block,
            self.amount_within_authorization,
            self.settlement_address_matches_task,
            self.current_status_allows_settlement,
        ])

    def failed_conditions(self) -> list[str]:
        """Return list of condition names that are NOT met."""
        conditions = {
            "buyer_authorization_signature_valid": self.buyer_authorization_signature_valid,
            "seller_accept_signature_valid": self.seller_accept_signature_valid,
            "input_hash_exists": self.input_hash_exists,
            "delivery_rule_exists": self.delivery_rule_exists,
            "execution_completed": self.execution_completed,
            "output_hash_exists": self.output_hash_exists,
            "evidence_bundle_hash_exists": self.evidence_bundle_hash_exists,
            "no_unresolved_dispute": self.no_unresolved_dispute,
            "no_risk_rule_block": self.no_risk_rule_block,
            "amount_within_authorization": self.amount_within_authorization,
            "settlement_address_matches_task": self.settlement_address_matches_task,
            "current_status_allows_settlement": self.current_status_allows_settlement,
        }
        return [name for name, met in conditions.items() if not met]
