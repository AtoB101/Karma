"""
Karma — Database Models (SQLAlchemy async)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentModel(Base):
    __tablename__ = "agents"

    agent_id:      Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    name:          Mapped[str]      = mapped_column(String(256), nullable=False)
    role:          Mapped[str]      = mapped_column(String(32), nullable=False)
    public_key:    Mapped[str]      = mapped_column(Text, nullable=False)
    endpoint_url:  Mapped[str|None] = mapped_column(String(512))
    capabilities:  Mapped[list]     = mapped_column(JSON, default=list)
    is_active:     Mapped[bool]     = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Task Contract
# ---------------------------------------------------------------------------

class TaskContractModel(Base):
    __tablename__ = "task_contracts"

    task_id:                Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    client_agent_id:        Mapped[str]      = mapped_column(String(64), ForeignKey("agents.agent_id"), nullable=False)
    worker_agent_id:        Mapped[str|None] = mapped_column(String(64), ForeignKey("agents.agent_id"))
    title:                  Mapped[str]      = mapped_column(String(512), nullable=False)
    description:            Mapped[str]      = mapped_column(Text, nullable=False)
    expected_output_schema: Mapped[dict]     = mapped_column(JSON, nullable=False)
    expected_step_count:    Mapped[int]      = mapped_column(Integer, nullable=False)
    escrow_amount:          Mapped[float]    = mapped_column(Float, nullable=False)
    currency:               Mapped[str]      = mapped_column(String(8), default="USD")
    deadline_at:            Mapped[datetime] = mapped_column(DateTime, nullable=False)
    contract_hash:          Mapped[str|None] = mapped_column(String(64))
    created_at:             Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    receipts:   Mapped[list[ReceiptModel]]    = relationship("ReceiptModel",    back_populates="contract", lazy="selectin")
    progress_receipts: Mapped[list[ProgressReceiptModel]] = relationship(
        "ProgressReceiptModel",
        back_populates="contract",
        lazy="selectin",
    )
    settlement: Mapped[SettlementModel|None]  = relationship("SettlementModel", back_populates="contract", uselist=False, lazy="selectin")


# ---------------------------------------------------------------------------
# Execution Receipt
# ---------------------------------------------------------------------------

class ReceiptModel(Base):
    __tablename__ = "execution_receipts"

    receipt_id:    Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id:       Mapped[str]      = mapped_column(String(64), ForeignKey("task_contracts.task_id"), nullable=False)
    agent_id:      Mapped[str]      = mapped_column(String(64), nullable=False)
    step_index:    Mapped[int]      = mapped_column(Integer, nullable=False)
    tool_name:     Mapped[str]      = mapped_column(String(256), nullable=False)
    input_hash:    Mapped[str]      = mapped_column(String(64), nullable=False)
    output_hash:   Mapped[str]      = mapped_column(String(64), nullable=False)
    started_at:    Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at:      Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_ms:   Mapped[int]      = mapped_column(Integer, nullable=False)
    status:        Mapped[str]      = mapped_column(String(16), nullable=False)
    error_message: Mapped[str|None] = mapped_column(Text)
    metadata_:     Mapped[dict]     = mapped_column("metadata", JSON, default=dict)
    signature:     Mapped[str|None] = mapped_column(Text)

    contract: Mapped[TaskContractModel] = relationship("TaskContractModel", back_populates="receipts")

    __table_args__ = (
        UniqueConstraint("task_id", "step_index", name="uq_task_step"),
    )


# ---------------------------------------------------------------------------
# Progress Receipt
# ---------------------------------------------------------------------------

class ProgressReceiptModel(Base):
    __tablename__ = "progress_receipts"

    progress_receipt_id: Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id:             Mapped[str]      = mapped_column(String(64), ForeignKey("task_contracts.task_id"), nullable=False)
    seller_identity_id:  Mapped[str]      = mapped_column(String(64), nullable=False)
    progress_percent:    Mapped[float]    = mapped_column(Float, nullable=False)
    claimed_value_percent: Mapped[float]  = mapped_column(Float, nullable=False)
    evidence_hash:       Mapped[str]      = mapped_column(String(128), nullable=False)
    runtime_log_hash:    Mapped[str]      = mapped_column(String(128), nullable=False)
    timestamp:           Mapped[datetime] = mapped_column(DateTime, nullable=False)
    seller_signature:    Mapped[str]      = mapped_column(Text, nullable=False)
    validation_method:   Mapped[str]      = mapped_column(String(64), nullable=False)
    confirmation_status: Mapped[str]      = mapped_column(String(16), nullable=False, default="pending")
    confirmed_at:        Mapped[datetime|None] = mapped_column(DateTime)

    contract: Mapped[TaskContractModel] = relationship("TaskContractModel", back_populates="progress_receipts")

# ---------------------------------------------------------------------------
# Evidence Bundle
# ---------------------------------------------------------------------------

class EvidenceBundleModel(Base):
    __tablename__ = "evidence_bundles"

    bundle_id:           Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id:             Mapped[str]      = mapped_column(String(64), ForeignKey("task_contracts.task_id"), nullable=False, unique=True)
    task_contract_hash:  Mapped[str]      = mapped_column(String(64), nullable=False)
    receipt_ids:         Mapped[list]     = mapped_column(JSON, nullable=False)
    receipt_hashes:      Mapped[list]     = mapped_column(JSON, nullable=False)
    final_result_hash:   Mapped[str]      = mapped_column(String(64), nullable=False)
    total_steps:         Mapped[int]      = mapped_column(Integer, nullable=False)
    successful_steps:    Mapped[int]      = mapped_column(Integer, nullable=False)
    failed_steps:        Mapped[int]      = mapped_column(Integer, nullable=False)
    total_duration_ms:   Mapped[int]      = mapped_column(Integer, nullable=False)
    agent_signature:     Mapped[str|None] = mapped_column(Text)
    storage_path:        Mapped[str|None] = mapped_column(String(512))
    settlement_status:   Mapped[str]      = mapped_column(String(32), default="submitted")
    created_at:          Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

class SettlementModel(Base):
    __tablename__ = "settlements"

    settlement_id:     Mapped[str]        = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id:           Mapped[str]        = mapped_column(String(64), ForeignKey("task_contracts.task_id"), nullable=False, unique=True)
    escrow_amount:     Mapped[float]      = mapped_column(Float, nullable=False)
    currency:          Mapped[str]        = mapped_column(String(8), default="USD")
    status:            Mapped[str]        = mapped_column(String(32), nullable=False)
    client_agent_id:   Mapped[str]        = mapped_column(String(64), nullable=False)
    worker_agent_id:   Mapped[str|None]   = mapped_column(String(64))
    released_amount:   Mapped[float|None] = mapped_column(Float)
    refunded_amount:   Mapped[float|None] = mapped_column(Float)
    dispute_reason:    Mapped[str|None]   = mapped_column(Text)
    arbitration_notes: Mapped[str|None]   = mapped_column(Text)
    created_at:        Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    released_at:       Mapped[datetime|None] = mapped_column(DateTime)

    # On-chain fields (populated when settlement_mode != offchain)
    settlement_mode:      Mapped[str]       = mapped_column(String(16), default="offchain")
    chain_id:             Mapped[int|None]  = mapped_column(Integer)
    contract_address:     Mapped[str|None]  = mapped_column(String(42))
    tx_hash:              Mapped[str|None]  = mapped_column(String(66))
    evidence_bundle_hash: Mapped[str|None]  = mapped_column(String(66))
    onchain_status:       Mapped[str|None]  = mapped_column(String(32))
    quote_id:             Mapped[str|None]  = mapped_column(String(66))

    contract: Mapped[TaskContractModel] = relationship("TaskContractModel", back_populates="settlement")


# ---------------------------------------------------------------------------
# Capacity & Voucher
# ---------------------------------------------------------------------------

class CapacityModel(Base):
    __tablename__ = "capacity"

    identity_id:                  Mapped[str]      = mapped_column(String(64), primary_key=True)
    total_locked_usdc:            Mapped[float]    = mapped_column(Float, default=0.0)
    total_bill_credits:           Mapped[float]    = mapped_column(Float, default=0.0)
    available_credits:            Mapped[float]    = mapped_column(Float, default=0.0)
    reserved_credits:             Mapped[float]    = mapped_column(Float, default=0.0)
    in_progress_credits:          Mapped[float]    = mapped_column(Float, default=0.0)
    confirmed_progress_credits:   Mapped[float]    = mapped_column(Float, default=0.0)
    disputed_credits:             Mapped[float]    = mapped_column(Float, default=0.0)
    pending_settlement_credits:   Mapped[float]    = mapped_column(Float, default=0.0)
    burned_credits:               Mapped[float]    = mapped_column(Float, default=0.0)
    released_credits:             Mapped[float]    = mapped_column(Float, default=0.0)
    updated_at:                   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VoucherModel(Base):
    __tablename__ = "vouchers"

    voucher_id:                 Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    buyer_identity_id:          Mapped[str]      = mapped_column(String(64), nullable=False)
    seller_identity_id:         Mapped[str]      = mapped_column(String(64), nullable=False)
    amount:                     Mapped[float]    = mapped_column(Float, nullable=False)
    currency:                   Mapped[str]      = mapped_column(String(8), default="USDC")
    bill_credit_amount:         Mapped[float]    = mapped_column(Float, nullable=False)
    task_type:                  Mapped[str]      = mapped_column(String(64), nullable=False)
    task_description_hash:      Mapped[str]      = mapped_column(String(128), nullable=False)
    progress_rule_hash:         Mapped[str]      = mapped_column(String(128), nullable=False)
    evidence_requirement_hash:  Mapped[str]      = mapped_column(String(128), nullable=False)
    expiry_time:                Mapped[datetime] = mapped_column(DateTime, nullable=False)
    nonce:                      Mapped[str]      = mapped_column(String(128), nullable=False)
    buyer_signature:            Mapped[str]      = mapped_column(Text, nullable=False)
    status:                     Mapped[str]      = mapped_column(String(16), nullable=False, default="created")
    buyer_sub_identity_id:      Mapped[str|None] = mapped_column(String(64))
    seller_sub_identity_id:     Mapped[str|None] = mapped_column(String(64))
    accepted_at:                Mapped[datetime|None] = mapped_column(DateTime)
    created_at:                 Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("buyer_identity_id", "nonce", name="uq_voucher_buyer_nonce"),
    )


# ---------------------------------------------------------------------------
# Identity Profile & Sub Identity
# ---------------------------------------------------------------------------

class IdentityProfileModel(Base):
    __tablename__ = "identity_profiles"

    identity_id:            Mapped[str]      = mapped_column(String(64), primary_key=True)
    display_id:             Mapped[str]      = mapped_column(String(64), nullable=False, unique=True)
    legal_identity_status:  Mapped[str]      = mapped_column(String(32), nullable=False, default="unbound")
    status:                 Mapped[str]      = mapped_column(String(32), nullable=False, default="active")
    created_at:             Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubIdentityModel(Base):
    __tablename__ = "sub_identities"

    sub_identity_id:      Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    parent_identity_id:   Mapped[str]      = mapped_column(String(64), nullable=False)
    sub_identity_type:    Mapped[str]      = mapped_column(String(32), nullable=False)
    alias:                Mapped[str]      = mapped_column(String(64), nullable=False)
    status:               Mapped[str]      = mapped_column(String(16), nullable=False, default="active")
    created_at:           Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at:           Mapped[datetime|None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("parent_identity_id", "alias", name="uq_sub_identity_alias_per_parent"),
    )


# ---------------------------------------------------------------------------
# Arbitration (P2 skeleton)
# ---------------------------------------------------------------------------

class ArbitrationPoolMemberModel(Base):
    __tablename__ = "arbitration_pool_members"

    arbitrator_identity_id: Mapped[str]      = mapped_column(String(64), primary_key=True)
    stake_amount:           Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    status:                 Mapped[str]      = mapped_column(String(16), nullable=False, default="active")
    joined_at:              Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArbitrationCaseModel(Base):
    __tablename__ = "arbitration_cases"

    case_id:                Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id:                Mapped[str]      = mapped_column(String(64), ForeignKey("task_contracts.task_id"), nullable=False, unique=True)
    settlement_id:          Mapped[str|None] = mapped_column(String(64))
    opened_by:              Mapped[str]      = mapped_column(String(64), nullable=False)
    reason:                 Mapped[str|None] = mapped_column(Text)
    status:                 Mapped[str]      = mapped_column(String(16), nullable=False, default="open")
    required_arbitrators:   Mapped[int]      = mapped_column(Integer, nullable=False, default=3)
    decided_outcome:        Mapped[str|None] = mapped_column(String(16))
    final_partial_percent:  Mapped[float|None] = mapped_column(Float)
    created_at:             Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_at:            Mapped[datetime|None] = mapped_column(DateTime)


class ArbitrationAssignmentModel(Base):
    __tablename__ = "arbitration_assignments"

    assignment_id:            Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    case_id:                  Mapped[str]      = mapped_column(String(64), ForeignKey("arbitration_cases.case_id"), nullable=False)
    arbitrator_identity_id:   Mapped[str]      = mapped_column(String(64), nullable=False)
    assigned_at:              Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status:                   Mapped[str]      = mapped_column(String(16), nullable=False, default="assigned")

    __table_args__ = (
        UniqueConstraint("case_id", "arbitrator_identity_id", name="uq_arbitration_assignment"),
    )


class ArbitrationMaterialPackageModel(Base):
    __tablename__ = "arbitration_material_packages"

    material_id:            Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    case_id:                Mapped[str]      = mapped_column(String(64), ForeignKey("arbitration_cases.case_id"), nullable=False)
    task_id:                Mapped[str]      = mapped_column(String(64), nullable=False)
    submitted_by:           Mapped[str]      = mapped_column(String(64), nullable=False)
    bundle_id:              Mapped[str|None] = mapped_column(String(64))
    progress_receipt_ids:   Mapped[list]     = mapped_column(JSON, nullable=False)
    evidence_hashes:        Mapped[list]     = mapped_column(JSON, nullable=False)
    package_hash:           Mapped[str]      = mapped_column(String(128), nullable=False)
    storage_uri:            Mapped[str|None] = mapped_column(String(512))
    format_version:         Mapped[str]      = mapped_column(String(32), nullable=False, default="arbitration-material-v1")
    submitted_at:           Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("case_id", "package_hash", name="uq_arbitration_material_hash_per_case"),
    )


class ArbitrationVoteModel(Base):
    __tablename__ = "arbitration_votes"

    vote_id:                Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    case_id:                Mapped[str]      = mapped_column(String(64), ForeignKey("arbitration_cases.case_id"), nullable=False)
    arbitrator_identity_id: Mapped[str]      = mapped_column(String(64), nullable=False)
    decision:               Mapped[str]      = mapped_column(String(16), nullable=False)
    partial_percent:        Mapped[float|None] = mapped_column(Float)
    rationale:              Mapped[str|None] = mapped_column(Text)
    voted_at:               Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("case_id", "arbitrator_identity_id", name="uq_arbitration_vote"),
    )


# ---------------------------------------------------------------------------
# Responsibility Graph (P2 skeleton)
# ---------------------------------------------------------------------------

class ResponsibilityEdgeModel(Base):
    __tablename__ = "responsibility_edges"

    edge_id:               Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    edge_hash:             Mapped[str]      = mapped_column(String(64), nullable=False, unique=True)
    source_identity_id:    Mapped[str]      = mapped_column(String(64), nullable=False)
    target_identity_id:    Mapped[str]      = mapped_column(String(64), nullable=False)
    edge_type:             Mapped[str]      = mapped_column(String(32), nullable=False)
    task_id:               Mapped[str|None] = mapped_column(String(64))
    voucher_id:            Mapped[str|None] = mapped_column(String(64))
    metadata_:             Mapped[dict]     = mapped_column("metadata", JSON, default=dict)
    created_at:            Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("voucher_id", name="uq_responsibility_edge_voucher"),
    )


class ResponsibilitySignalModel(Base):
    __tablename__ = "responsibility_signals"

    signal_id:             Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    signal_type:           Mapped[str]      = mapped_column(String(32), nullable=False)
    severity:              Mapped[str]      = mapped_column(String(16), nullable=False)
    identity_id:           Mapped[str]      = mapped_column(String(64), nullable=False)
    edge_hash:             Mapped[str]      = mapped_column(String(64), nullable=False)
    related_edge_hashes:   Mapped[list]     = mapped_column(JSON, nullable=False, default=list)
    task_id:               Mapped[str|None] = mapped_column(String(64))
    detail:                Mapped[str]      = mapped_column(Text, nullable=False)
    created_at:            Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResponsibilityScanRunModel(Base):
    __tablename__ = "responsibility_scan_runs"

    scan_id:               Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    status:                Mapped[str]      = mapped_column(String(16), nullable=False, default="pending")
    execution_mode:        Mapped[str]      = mapped_column(String(16), nullable=False, default="sync")
    scan_mode:             Mapped[str]      = mapped_column(String(16), nullable=False, default="full")
    base_scan_id:          Mapped[str|None] = mapped_column(String(64))
    incremental_since_at:  Mapped[datetime|None] = mapped_column(DateTime)
    requested_identity_ids: Mapped[list|None] = mapped_column(JSON)
    window_hours:          Mapped[int]      = mapped_column(Integer, nullable=False, default=24)
    max_hops:              Mapped[int]      = mapped_column(Integer, nullable=False, default=4)
    min_score_threshold:   Mapped[float]    = mapped_column(Float, nullable=False, default=8.0)
    retry_max_attempts:    Mapped[int]      = mapped_column(Integer, nullable=False, default=3)
    retry_backoff_seconds: Mapped[int]      = mapped_column(Integer, nullable=False, default=30)
    current_attempt:       Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    claimed_by:            Mapped[str|None] = mapped_column(String(64))
    claimed_at:            Mapped[datetime|None] = mapped_column(DateTime)
    lease_expires_at:      Mapped[datetime|None] = mapped_column(DateTime)
    last_heartbeat_at:     Mapped[datetime|None] = mapped_column(DateTime)
    started_at:            Mapped[datetime|None] = mapped_column(DateTime)
    next_retry_at:         Mapped[datetime|None] = mapped_column(DateTime)
    last_error:            Mapped[str|None] = mapped_column(Text)
    cancelled_at:          Mapped[datetime|None] = mapped_column(DateTime)
    cancel_reason:         Mapped[str|None] = mapped_column(Text)
    dead_lettered_at:      Mapped[datetime|None] = mapped_column(DateTime)
    dead_letter_reason:    Mapped[str|None] = mapped_column(Text)
    total_identities:      Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    flagged_identities:    Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    created_at:            Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at:          Mapped[datetime|None] = mapped_column(DateTime)


class ResponsibilityScanFindingModel(Base):
    __tablename__ = "responsibility_scan_findings"

    finding_id:            Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    scan_id:               Mapped[str]      = mapped_column(String(64), ForeignKey("responsibility_scan_runs.scan_id"), nullable=False)
    identity_id:           Mapped[str]      = mapped_column(String(64), nullable=False)
    normalized_score:      Mapped[float]    = mapped_column(Float, nullable=False)
    risk_band:             Mapped[str]      = mapped_column(String(16), nullable=False)
    signal_count:          Mapped[int]      = mapped_column(Integer, nullable=False)
    cycle_paths_detected:  Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    detail:                Mapped[str]      = mapped_column(Text, nullable=False)
    created_at:            Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResponsibilityScanEventModel(Base):
    __tablename__ = "responsibility_scan_events"

    event_id:              Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    scan_id:               Mapped[str]      = mapped_column(String(64), ForeignKey("responsibility_scan_runs.scan_id"), nullable=False)
    event_type:            Mapped[str]      = mapped_column(String(32), nullable=False)
    detail:                Mapped[str]      = mapped_column(Text, nullable=False)
    metadata_:             Mapped[dict]     = mapped_column("metadata", JSON, default=dict)
    created_at:            Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Verification Result
# ---------------------------------------------------------------------------

class VerificationResultModel(Base):
    __tablename__ = "verification_results"

    verification_id: Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id:         Mapped[str]      = mapped_column(String(64), ForeignKey("task_contracts.task_id"), nullable=False)
    bundle_id:       Mapped[str]      = mapped_column(String(64), nullable=False)
    decision:        Mapped[str]      = mapped_column(String(16), nullable=False)
    confidence:      Mapped[float]    = mapped_column(Float, nullable=False)
    checks:          Mapped[list]     = mapped_column(JSON, nullable=False)
    notes:           Mapped[str|None] = mapped_column(Text)
    verified_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Reputation
# ---------------------------------------------------------------------------

class ReputationModel(Base):
    __tablename__ = "reputation"

    agent_id:           Mapped[str]   = mapped_column(String(64), ForeignKey("agents.agent_id"), primary_key=True)
    role:               Mapped[str]   = mapped_column(String(32), nullable=False)
    score:              Mapped[float] = mapped_column(Float, default=100.0)
    total_tasks:        Mapped[int]   = mapped_column(Integer, default=0)
    successful_tasks:   Mapped[int]   = mapped_column(Integer, default=0)
    disputed_tasks:     Mapped[int]   = mapped_column(Integer, default=0)
    arbitration_wins:   Mapped[int]   = mapped_column(Integer, default=0)
    arbitration_losses: Mapped[int]   = mapped_column(Integer, default=0)
    # Private fields stored here but only read by private runtime
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    wash_trade_flags:      Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)
