"""
PRIVATE schema mirror for runtime services.
This keeps private runtime imports stable without exposing private logic.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    CREATED = "created"
    LOCKED = "locked"
    RUNNING = "running"
    SUBMITTED = "submitted"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    RELEASED = "released"
    FAILED = "failed"
    DISPUTED = "disputed"
    ARBITRATION = "arbitration"
    BUYER_WINS = "buyer_wins"
    SELLER_WINS = "seller_wins"
    PARTIAL = "partial"
    REFUNDED = "refunded"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class AgentRole(str, Enum):
    CLIENT = "client"
    WORKER = "worker"
    ARBITRATOR = "arbitrator"
    VALIDATOR = "validator"


class VerificationDecision(str, Enum):
    RELEASE = "release"
    HOLD = "hold"
    REFUND = "refund"
    DISPUTE = "dispute"


class TaskContract(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_agent_id: str
    worker_agent_id: Optional[str] = None
    title: str
    description: str
    expected_output_schema: dict[str, Any]
    expected_step_count: int = Field(ge=1)
    escrow_amount: float = Field(ge=0.0)
    currency: str = "USD"
    deadline_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    contract_hash: Optional[str] = None


class ExecutionReceipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    agent_id: str
    step_index: int = Field(ge=1)
    tool_name: str
    input_hash: str
    output_hash: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int = Field(ge=0)
    status: ToolStatus
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    signature: Optional[str] = None


class EvidenceBundle(BaseModel):
    bundle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    task_contract_hash: str
    receipt_ids: list[str]
    receipt_hashes: list[str]
    final_result_hash: str
    total_steps: int
    successful_steps: int
    failed_steps: int
    total_duration_ms: int
    agent_signature: Optional[str] = None
    storage_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    settlement_status: TaskStatus = TaskStatus.SUBMITTED


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    detail: Optional[str] = None


class VerificationResult(BaseModel):
    verification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    bundle_id: str
    decision: VerificationDecision
    confidence: float = Field(ge=0.0, le=1.0)
    checks: list[VerificationCheck]
    notes: Optional[str] = None
    verified_at: datetime = Field(default_factory=datetime.utcnow)


class SettlementState(BaseModel):
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
    settlement_mode: str = "offchain"
    chain_id: Optional[int] = None
    contract_address: Optional[str] = None
    tx_hash: Optional[str] = None
    evidence_bundle_hash: Optional[str] = None
    onchain_status: Optional[str] = None
    quote_id: Optional[str] = None


class ReputationSnapshot(BaseModel):
    agent_id: str
    role: AgentRole
    score: float
    total_tasks: int
    successful_tasks: int
    disputed_tasks: int
    success_rate: float = Field(ge=0.0, le=1.0)
    last_updated: datetime

