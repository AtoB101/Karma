"""
Karma — Database Models (SQLAlchemy async)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    """DateTime that stores tz-aware values as naive UTC.

    The schema uses ``timestamp without time zone`` columns and asyncpg refuses to
    bind an aware datetime to them ("can't subtract offset-naive and offset-aware
    datetimes"). Anything that arrives aware - e.g. an ISO string with a ``Z`` or
    ``+00:00`` offset produced by a browser - is normalised to naive UTC here.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


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
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    # P1 onboarding — identity class, owner bind, readiness (anti-forgery / counterparty verify)
    identity_class:     Mapped[str|None] = mapped_column(String(32), nullable=True)
    owner_identity_id:  Mapped[str|None] = mapped_column(String(128), nullable=True, index=True)
    boundary_hash:      Mapped[str|None] = mapped_column(String(80), nullable=True)
    p1_ready:           Mapped[bool]     = mapped_column(Boolean, default=False)
    onboarding_meta:    Mapped[dict]     = mapped_column(JSON, default=dict)


class IdentityRoleProfile(Base):
    """One identity card -> many role profiles (class + KYC + visibility).

    Each profile is an isolated identity context with its own class
    (individual / merchant / enterprise / verifier / arbitrator), KYC status
    and visibility (enterprise defaults to private so fund flows stay
    confidential). Complements the existing DID IdentityProfileModel and the
    transaction-role SubIdentityModel — this is the identity-role dimension.
    """
    __tablename__ = "identity_role_profiles"

    profile_id:        Mapped[str]         = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_identity_id: Mapped[str]         = mapped_column(String(64), nullable=False, index=True)
    class_:            Mapped[str]         = mapped_column("class", String(32), nullable=False, default="individual")
    kyc_status:        Mapped[str]         = mapped_column(String(32), nullable=False, default="none")
    visibility:        Mapped[str]         = mapped_column(String(16), nullable=False, default="public")
    display_name:      Mapped[str | None]  = mapped_column(String(256))
    kyc_payload:       Mapped[dict]        = mapped_column(JSON, default=dict)
    status:            Mapped[str]         = mapped_column(String(16), nullable=False, default="active")
    # 子身份自己的操作钱包（签名 / 授权）；资金仍然统一走主身份钱包，见 identity_verification。
    bound_wallet_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 子身份的默认权限与边界：生成 SDK 时预填，真正强制落在 runtime key 上。
    spend_policy:      Mapped[dict]        = mapped_column(JSON, default=dict)
    # 治理岗（verifier / arbitrator）的质押承诺额。0 = 白名单开的岗、或者还没质押。
    # 这只是一条**承诺**：真正有没有钱在里面，每次都去 capacity.total_locked_usdc
    # 现算（services/governance_stake.py）—— 押金被划走之后岗位立刻失效，靠的就是现算。
    stake_amount:      Mapped[float]       = mapped_column(Float, default=0.0, nullable=False, server_default="0")
    created_at:        Mapped[datetime]    = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime]    = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IdentityDisclosureModel(Base):
    """P3 — authorized disclosure for private (enterprise) role profiles.

    A private profile's ledger is hidden by default. The owner grants a specific
    authorized party access to either a single transaction (``scope=transaction``,
    ``task_id`` set) or the whole ledger (``scope=ledger``).
    """
    __tablename__ = "identity_disclosures"

    disclosure_id:          Mapped[str]         = mapped_column(String(64), primary_key=True, default=_uuid)
    profile_id:             Mapped[str]         = mapped_column(String(64), nullable=False, index=True)
    authorized_identity_id: Mapped[str]         = mapped_column(String(128), nullable=False, index=True)
    task_id:                Mapped[str | None]  = mapped_column(String(64), nullable=True, index=True)
    scope:                  Mapped[str]         = mapped_column(String(16), nullable=False, default="transaction")
    status:                 Mapped[str]         = mapped_column(String(16), nullable=False, default="active")
    created_at:             Mapped[datetime]    = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime]    = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    deadline_at:            Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    contract_hash:          Mapped[str|None] = mapped_column(String(64))
    created_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

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
    profile_id:    Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    step_index:    Mapped[int]      = mapped_column(Integer, nullable=False)
    tool_name:     Mapped[str]      = mapped_column(String(256), nullable=False)
    input_hash:    Mapped[str]      = mapped_column(String(64), nullable=False)
    output_hash:   Mapped[str]      = mapped_column(String(64), nullable=False)
    started_at:    Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at:      Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
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
    timestamp:           Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    seller_signature:    Mapped[str]      = mapped_column(Text, nullable=False)
    validation_method:   Mapped[str]      = mapped_column(String(64), nullable=False)
    confirmation_status: Mapped[str]      = mapped_column(String(16), nullable=False, default="pending")
    confirmed_at:        Mapped[datetime|None] = mapped_column(UTCDateTime)

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
    created_at:          Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


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
    profile_id:        Mapped[str|None]   = mapped_column(String(64), nullable=True, index=True)
    worker_profile_id: Mapped[str|None]   = mapped_column(String(64), nullable=True)
    released_amount:   Mapped[float|None] = mapped_column(Float)
    refunded_amount:   Mapped[float|None] = mapped_column(Float)
    dispute_reason:    Mapped[str|None]   = mapped_column(Text)
    arbitration_notes: Mapped[str|None]   = mapped_column(Text)
    created_at:        Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    released_at:       Mapped[datetime|None] = mapped_column(UTCDateTime)

    # On-chain fields (populated when settlement_mode != offchain)
    settlement_mode:      Mapped[str]       = mapped_column(String(16), default="offchain")
    chain_id:             Mapped[int|None]  = mapped_column(Integer)
    contract_address:     Mapped[str|None]  = mapped_column(String(42))
    tx_hash:              Mapped[str|None]  = mapped_column(String(66))
    evidence_bundle_hash: Mapped[str|None]  = mapped_column(String(66))
    onchain_status:       Mapped[str|None]  = mapped_column(String(32))
    quote_id:             Mapped[str|None]  = mapped_column(String(66))
    onchain_binding_id:   Mapped[int|None]  = mapped_column(Integer, nullable=True)
    onchain_buyer_bill_id: Mapped[int|None] = mapped_column(Integer, nullable=True)
    onchain_agent_bill_id: Mapped[int|None] = mapped_column(Integer, nullable=True)
    voucher_id:           Mapped[str|None]  = mapped_column(String(64), nullable=True)
    delivery_deadline_at: Mapped[datetime|None] = mapped_column(UTCDateTime, nullable=True)
    progress_rule_spec:   Mapped[dict|None] = mapped_column(JSON, nullable=True)
    # MVVS V1 确认窗口：交付时写入，窗口到期后可走 /auto-confirm 兜底。
    confirm_window_hours: Mapped[int|None] = mapped_column(Integer, nullable=True)
    confirm_deadline_at:  Mapped[datetime|None] = mapped_column(UTCDateTime, nullable=True)
    funding_source:       Mapped[str]        = mapped_column(String(16), nullable=False, default="internal")

    contract: Mapped[TaskContractModel] = relationship("TaskContractModel", back_populates="settlement")


class SettlementTransitionAuditModel(Base):
    __tablename__ = "settlement_transition_audits"

    audit_id:            Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    settlement_id:       Mapped[str | None] = mapped_column(String(64), ForeignKey("settlements.settlement_id"))
    task_id:             Mapped[str] = mapped_column(String(64), nullable=False)
    from_status:         Mapped[str | None] = mapped_column(String(32))
    to_status:           Mapped[str] = mapped_column(String(32), nullable=False)
    transition_allowed:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    guard_stage:         Mapped[str] = mapped_column(String(64), nullable=False, default="route")
    reason:              Mapped[str | None] = mapped_column(Text)
    route_path:          Mapped[str | None] = mapped_column(String(256))
    actor_id:            Mapped[str | None] = mapped_column(String(64))
    metadata_:           Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at:          Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Capacity & Voucher
# ---------------------------------------------------------------------------

class CapacityModel(Base):
    __tablename__ = "capacity"

    identity_id:                  Mapped[str]      = mapped_column(String(64), primary_key=True)
    profile_id:                   Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
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
    updated_at:                   Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProfileCapacityModel(Base):
    """Per-profile quota allocation under a master identity capacity.

    The master ``capacity`` row (keyed by identity_id) is the total locked USDC anchor;
    each role profile gets its own allocation (``allocated_credits``) and usage
    breakdown, so 个人/商家/企业 各自在授权额度内行事、互不混淆、总账对齐。
    """
    __tablename__ = "profile_capacity"

    profile_id:                   Mapped[str]      = mapped_column(String(64), primary_key=True)
    owner_identity_id:            Mapped[str]      = mapped_column(String(128), nullable=False, index=True)
    allocated_credits:            Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    available_credits:            Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    in_progress_credits:          Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    pending_settlement_credits:   Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    disputed_credits:             Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    released_credits:             Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    updated_at:                   Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChainLockModel(Base):
    """One on-chain ``KarmaBilateral.lock()`` receipt, credited 1:1 to an identity.

    This table is the only record of real USDC sitting in the contract, and the
    ``capacity`` ledger is credited from these rows — so available credits can
    never exceed the USDC a wallet actually deposited. ``bill_id`` /
    ``lock_tx_hash`` are unique, which makes replaying a transaction a no-op.
    """
    __tablename__ = "chain_locks"

    bill_id:          Mapped[str]      = mapped_column(String(80), primary_key=True)
    identity_id:      Mapped[str]      = mapped_column(String(64), nullable=False, index=True)
    wallet_address:   Mapped[str]      = mapped_column(String(64), nullable=False, index=True)
    chain_id:         Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    contract_address: Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    token_address:    Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    amount_wei:       Mapped[str]      = mapped_column(String(80), nullable=False, default="0")
    amount_usdc:      Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    lock_tx_hash:     Mapped[str]      = mapped_column(String(80), nullable=False, unique=True)
    block_number:     Mapped[int|None] = mapped_column(Integer, nullable=True)
    state:            Mapped[str]      = mapped_column(String(16), nullable=False, default="locked")
    unlock_tx_hash:   Mapped[str|None] = mapped_column(String(80), nullable=True)
    # Seller stake pool: an idle bill can be reserved by one accepted order.
    stake_state:       Mapped[str]           = mapped_column(String(16), nullable=False, default="idle")
    stake_task_id:     Mapped[str|None]      = mapped_column(String(64), nullable=True, index=True)
    stake_reserved_at: Mapped[datetime|None] = mapped_column(UTCDateTime, nullable=True)
    created_at:       Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:       Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AllowanceCommitModel(Base):
    """One on-chain ``KarmaAllowanceEscrow.commit()`` receipt (v2, non-custodial).

    Nothing is deposited: the wallet keeps its USDC and only grants the escrow an
    ERC-20 allowance, so ``amount_usdc`` is a *responsibility ceiling* rather than
    a balance Karma holds. ``bill_id`` / ``commit_tx_hash`` are unique, which is
    what makes replaying a transaction a no-op.
    """
    __tablename__ = "allowance_commits"

    bill_id:          Mapped[str]        = mapped_column(String(80), primary_key=True)
    identity_id:      Mapped[str]        = mapped_column(String(64), nullable=False, index=True)
    wallet_address:   Mapped[str]        = mapped_column(String(64), nullable=False, index=True)
    chain_id:         Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    contract_address: Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    token_address:    Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    operator:         Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    amount_wei:       Mapped[str]        = mapped_column(String(80), nullable=False, default="0")
    amount_usdc:      Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    spent_usdc:       Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    reserved_usdc:    Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    backed:           Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False)
    # 这条承诺目前有多少已经被记进主身份 capacity 台账（v2 非托管锁仓的镜像）。
    capacity_credited_usdc: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    commit_tx_hash:   Mapped[str]        = mapped_column(String(80), nullable=False, unique=True)
    revoke_tx_hash:   Mapped[str|None]   = mapped_column(String(80), nullable=True)
    block_number:     Mapped[int|None]   = mapped_column(Integer, nullable=True)
    state:            Mapped[str]        = mapped_column(String(16), nullable=False, default="open")
    last_synced_at:   Mapped[datetime|None] = mapped_column(UTCDateTime, nullable=True)
    created_at:       Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:       Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EscrowBindingModel(Base):
    """One bound buyer/seller pair: the order Karma settles wallet-to-wallet.

    ``state`` mirrors the contract (active/finalizing/settled/slashed/cancelled).
    A row here records *intent and proof*; the transfer itself is executed by the
    contract, straight from the payer's wallet to the payee's.
    """
    __tablename__ = "escrow_bindings"

    binding_id:        Mapped[str]        = mapped_column(String(80), primary_key=True)
    buyer_identity_id: Mapped[str]        = mapped_column(String(64), nullable=False, index=True)
    seller_identity_id: Mapped[str|None]  = mapped_column(String(64), nullable=True, index=True)
    buyer_profile_id:  Mapped[str|None]   = mapped_column(String(64), nullable=True, index=True)
    seller_profile_id: Mapped[str|None]   = mapped_column(String(64), nullable=True)
    buyer_bill_id:     Mapped[str]        = mapped_column(String(80), nullable=False)
    seller_bill_id:    Mapped[str]        = mapped_column(String(80), nullable=False)
    #: 这条绑定落在哪台托管合约上。合约换地址（v2 升级到 v3）之后，绑定必须回到
    #: **它自己那台**合约上收尾（finalize / cancel）：拿旧 binding id 去新合约问，
    #: 合约根本不认识它（UnknownBinding），钱会被一次升级永久卡死。
    contract_address:  Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    scope_hash:        Mapped[str]        = mapped_column(String(80), nullable=False, default="")
    task_id:           Mapped[str|None]   = mapped_column(String(64), nullable=True, index=True)
    amount_usdc:       Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    stake_usdc:        Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    state:             Mapped[str]        = mapped_column(String(16), nullable=False, default="active")
    proof_hash:        Mapped[str|None]   = mapped_column(String(80), nullable=True)
    bind_tx_hash:      Mapped[str|None]   = mapped_column(String(80), nullable=True, unique=True)
    submit_tx_hash:    Mapped[str|None]   = mapped_column(String(80), nullable=True)
    finalize_tx_hash:  Mapped[str|None]   = mapped_column(String(80), nullable=True)
    pull_after:        Mapped[int|None]   = mapped_column(Integer, nullable=True)
    #: 买方在链上打过「确认放款」标记的时刻（v4 ``buyerConfirm``）。有它就不必
    #: 再等争议窗口：验证已过 + 买方自己点头，划款立刻可执行。
    buyer_confirmed_at: Mapped[datetime|None] = mapped_column(UTCDateTime, nullable=True)
    created_at:        Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VoucherModel(Base):
    __tablename__ = "vouchers"

    voucher_id:                 Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    buyer_identity_id:          Mapped[str]      = mapped_column(String(64), nullable=False)
    seller_identity_id:         Mapped[str]      = mapped_column(String(64), nullable=False)
    profile_id:                 Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
    amount:                     Mapped[float]    = mapped_column(Float, nullable=False)
    currency:                   Mapped[str]      = mapped_column(String(8), default="USDC")
    bill_credit_amount:         Mapped[float]    = mapped_column(Float, nullable=False)
    task_type:                  Mapped[str]      = mapped_column(String(64), nullable=False)
    task_description_hash:      Mapped[str]      = mapped_column(String(128), nullable=False)
    progress_rule_hash:         Mapped[str]      = mapped_column(String(128), nullable=False)
    evidence_requirement_hash:  Mapped[str]      = mapped_column(String(128), nullable=False)
    expiry_time:                Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    nonce:                      Mapped[str]      = mapped_column(String(128), nullable=False)
    buyer_signature:            Mapped[str]      = mapped_column(Text, nullable=False)
    status:                     Mapped[str]      = mapped_column(String(16), nullable=False, default="created")
    buyer_sub_identity_id:      Mapped[str|None] = mapped_column(String(64))
    seller_sub_identity_id:     Mapped[str|None] = mapped_column(String(64))
    seller_profile_id:          Mapped[str|None] = mapped_column(String(64), nullable=True)
    accepted_at:                Mapped[datetime|None] = mapped_column(UTCDateTime)
    created_at:                 Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    progress_rule_spec:         Mapped[dict|None] = mapped_column(JSON, nullable=True)
    task_precision:             Mapped[float|None] = mapped_column(Float, nullable=True)
    payment_mode:               Mapped[str]      = mapped_column(String(16), nullable=False, default="manual")
    chain_anchor_hash:          Mapped[str|None] = mapped_column(String(128), nullable=True)
    rejection_reason:           Mapped[str|None] = mapped_column(Text, nullable=True)
    rejected_at:                Mapped[datetime|None] = mapped_column(UTCDateTime, nullable=True)
    rejected_by_identity_id:    Mapped[str|None] = mapped_column(String(64), nullable=True)
    task_id:                    Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("buyer_identity_id", "nonce", name="uq_voucher_buyer_nonce"),
    )


class VoucherEventModel(Base):
    """Auditable voucher lifecycle events visible to buyer/seller (phase 1)."""

    __tablename__ = "voucher_events"

    event_id:              Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    voucher_id:            Mapped[str]      = mapped_column(String(64), nullable=False, index=True)
    event_type:            Mapped[str]      = mapped_column(String(32), nullable=False)
    actor_identity_id:     Mapped[str|None] = mapped_column(String(64), nullable=True)
    target_identity_id:    Mapped[str|None] = mapped_column(String(64), nullable=True)
    payload:               Mapped[dict]     = mapped_column(JSON, nullable=False, default=dict)
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Identity Profile & Sub Identity
# ---------------------------------------------------------------------------

class IdentityProfileModel(Base):
    __tablename__ = "identity_profiles"

    identity_id:            Mapped[str]      = mapped_column(String(128), primary_key=True)
    display_id:             Mapped[str]      = mapped_column(String(64), nullable=False, unique=True)
    legal_identity_status:  Mapped[str]      = mapped_column(String(32), nullable=False, default="unbound")
    status:                 Mapped[str]      = mapped_column(String(32), nullable=False, default="active")
    bound_wallet_address:   Mapped[str|None] = mapped_column(String(128), nullable=True)
    did_agent_address:      Mapped[str|None] = mapped_column(String(64), nullable=True)
    on_chain_did:           Mapped[str|None] = mapped_column(String(66), nullable=True, unique=True)
    projection_readonly:    Mapped[bool]     = mapped_column(Boolean, default=False)
    projection_source:      Mapped[str|None] = mapped_column(String(32), nullable=True)
    created_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubIdentityModel(Base):
    __tablename__ = "sub_identities"

    sub_identity_id:      Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    parent_identity_id:   Mapped[str]      = mapped_column(String(64), nullable=False)
    sub_identity_type:    Mapped[str]      = mapped_column(String(32), nullable=False)
    alias:                Mapped[str]      = mapped_column(String(64), nullable=False)
    status:               Mapped[str]      = mapped_column(String(16), nullable=False, default="active")
    created_at:           Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    deleted_at:           Mapped[datetime|None] = mapped_column(UTCDateTime)

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
    joined_at:              Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_at:            Mapped[datetime|None] = mapped_column(UTCDateTime)


class ArbitrationAssignmentModel(Base):
    __tablename__ = "arbitration_assignments"

    assignment_id:            Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    case_id:                  Mapped[str]      = mapped_column(String(64), ForeignKey("arbitration_cases.case_id"), nullable=False)
    arbitrator_identity_id:   Mapped[str]      = mapped_column(String(64), nullable=False)
    assigned_at:              Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
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
    submitted_at:           Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

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
    voted_at:               Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("case_id", "arbitrator_identity_id", name="uq_arbitration_vote"),
    )


class ArbitrationCaseEventModel(Base):
    __tablename__ = "arbitration_case_events"

    event_id:               Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    case_id:                Mapped[str]      = mapped_column(String(64), ForeignKey("arbitration_cases.case_id"), nullable=False)
    event_type:             Mapped[str]      = mapped_column(String(32), nullable=False)
    detail:                 Mapped[str]      = mapped_column(Text, nullable=False)
    metadata_:              Mapped[dict]     = mapped_column("metadata", JSON, default=dict)
    created_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


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
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

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
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


class ResponsibilityScanRunModel(Base):
    __tablename__ = "responsibility_scan_runs"

    scan_id:               Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    status:                Mapped[str]      = mapped_column(String(16), nullable=False, default="pending")
    execution_mode:        Mapped[str]      = mapped_column(String(16), nullable=False, default="sync")
    scan_mode:             Mapped[str]      = mapped_column(String(16), nullable=False, default="full")
    base_scan_id:          Mapped[str|None] = mapped_column(String(64))
    incremental_since_at:  Mapped[datetime|None] = mapped_column(UTCDateTime)
    requested_identity_ids: Mapped[list|None] = mapped_column(JSON)
    window_hours:          Mapped[int]      = mapped_column(Integer, nullable=False, default=24)
    max_hops:              Mapped[int]      = mapped_column(Integer, nullable=False, default=4)
    min_score_threshold:   Mapped[float]    = mapped_column(Float, nullable=False, default=8.0)
    retry_max_attempts:    Mapped[int]      = mapped_column(Integer, nullable=False, default=3)
    retry_backoff_seconds: Mapped[int]      = mapped_column(Integer, nullable=False, default=30)
    current_attempt:       Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    claimed_by:            Mapped[str|None] = mapped_column(String(64))
    claimed_at:            Mapped[datetime|None] = mapped_column(UTCDateTime)
    lease_expires_at:      Mapped[datetime|None] = mapped_column(UTCDateTime)
    last_heartbeat_at:     Mapped[datetime|None] = mapped_column(UTCDateTime)
    started_at:            Mapped[datetime|None] = mapped_column(UTCDateTime)
    next_retry_at:         Mapped[datetime|None] = mapped_column(UTCDateTime)
    last_error:            Mapped[str|None] = mapped_column(Text)
    cancelled_at:          Mapped[datetime|None] = mapped_column(UTCDateTime)
    cancel_reason:         Mapped[str|None] = mapped_column(Text)
    dead_lettered_at:      Mapped[datetime|None] = mapped_column(UTCDateTime)
    dead_letter_reason:    Mapped[str|None] = mapped_column(Text)
    total_identities:      Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    flagged_identities:    Mapped[int]      = mapped_column(Integer, nullable=False, default=0)
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    completed_at:          Mapped[datetime|None] = mapped_column(UTCDateTime)


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
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


class ResponsibilityScanEventModel(Base):
    __tablename__ = "responsibility_scan_events"

    event_id:              Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    scan_id:               Mapped[str]      = mapped_column(String(64), ForeignKey("responsibility_scan_runs.scan_id"), nullable=False)
    event_type:            Mapped[str]      = mapped_column(String(32), nullable=False)
    detail:                Mapped[str]      = mapped_column(Text, nullable=False)
    metadata_:             Mapped[dict]     = mapped_column("metadata", JSON, default=dict)
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Security Threshold Policy Center (P2 security hardening)
# ---------------------------------------------------------------------------

class SecurityThresholdPolicyModel(Base):
    __tablename__ = "security_threshold_policies"

    policy_id:             Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    version:               Mapped[int]      = mapped_column(Integer, nullable=False, unique=True)
    status:                Mapped[str]      = mapped_column(String(16), nullable=False, default="draft")
    rollout_percent:       Mapped[int]      = mapped_column(Integer, nullable=False, default=100)
    config:                Mapped[dict]     = mapped_column(JSON, nullable=False, default=dict)
    note:                  Mapped[str|None] = mapped_column(Text)
    created_by:            Mapped[str|None] = mapped_column(String(64))
    created_at:            Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    activated_at:          Mapped[datetime|None] = mapped_column(UTCDateTime)
    archived_at:           Mapped[datetime|None] = mapped_column(UTCDateTime)
    parent_policy_id:      Mapped[str|None] = mapped_column(String(64))


class SecurityPolicyChangeRequestModel(Base):
    __tablename__ = "security_policy_change_requests"

    request_id:               Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    action:                   Mapped[str]      = mapped_column(String(32), nullable=False)
    status:                   Mapped[str]      = mapped_column(String(16), nullable=False, default="pending")
    target_policy_id:         Mapped[str|None] = mapped_column(String(64))
    target_rollback_policy_id: Mapped[str|None] = mapped_column(String(64))
    rollout_percent:          Mapped[int|None] = mapped_column(Integer)
    note:                     Mapped[str|None] = mapped_column(Text)
    requested_by:             Mapped[str|None] = mapped_column(String(64))
    requested_at:             Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    applied_at:               Mapped[datetime|None] = mapped_column(UTCDateTime)
    required_approvals:       Mapped[int]      = mapped_column(Integer, nullable=False, default=2)
    dry_run_report:           Mapped[dict|None] = mapped_column(JSON)


class SecurityPolicyChangeApprovalModel(Base):
    __tablename__ = "security_policy_change_approvals"

    approval_id:              Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    request_id:               Mapped[str]      = mapped_column(
        String(64),
        ForeignKey("security_policy_change_requests.request_id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_id:              Mapped[str]      = mapped_column(String(64), nullable=False)
    decision:                 Mapped[str]      = mapped_column(String(16), nullable=False)
    comment:                  Mapped[str|None] = mapped_column(Text)
    created_at:               Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("request_id", "approver_id", name="uq_security_policy_change_approver"),
    )


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
    verified_at:     Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Runtime Key (Agent Runtime Gateway — public SDK / Console)
# ---------------------------------------------------------------------------


class AgentAutomationPolicyModel(Base):
    """
    Server-side record of operator-configured AI automation bounds (Console).

    Must be saved before minting a Runtime Key when ``runtime_require_saved_automation_policy`` is enabled.
    """

    __tablename__ = "agent_automation_policies"

    karma_identity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    auto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    single_limit: Mapped[float] = mapped_column(Float, nullable=False)
    daily_limit: Mapped[float] = mapped_column(Float, nullable=False)
    permissions: Mapped[list] = mapped_column(JSON, nullable=False)
    high_risk_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="always")
    responsibility_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    preauth_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_task_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    task_precision_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    task_precision_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    trusted_counterparty_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payment_code_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    responsibility_boundary_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auto_accept_incoming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_execute_pipeline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    human_not_present_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PaymentIntentModel(Base):
    """AP2 / M5 Payment Intent — merchant-facing payment contract (Phase 3)."""

    __tablename__ = "payment_intents"

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    merchant_ref: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    payer: Mapped[str] = mapped_column(String(128), nullable=False)
    payee: Mapped[str] = mapped_column(String(128), nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    voucher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ap2_mandate_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradeOrderModel(Base):
    """Auditable preauth trade order pipeline (phase 1.5)."""

    __tablename__ = "trade_orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    voucher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    buyer_identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seller_identity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    decomposed_spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    launch_idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True, unique=True)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v2")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OpenclawHandoffAttestationModel(Base):
    """Operator attestation that Console authorization is complete for a task (per identity)."""

    __tablename__ = "openclaw_handoff_attestations"

    attestation_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    karma_identity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attested_by_actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    handoff_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handoff_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    readiness_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "karma_identity_id",
            name="uq_handoff_attestation_task_identity",
        ),
    )


class RuntimeKeyDailySpendModel(Base):
    """Per-key daily spend totals (UTC date) for Runtime fund limits."""

    __tablename__ = "runtime_key_daily_spend"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spend_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    amount_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RuntimeKeyCallLogModel(Base):
    """Runtime Key 的逐条调用记录 —— 「这把钥匙最近替我做了什么」。

    额度表（``runtime_key_daily_spend``）只有汇总，回答不了「钱是被哪一次调用花掉的」。
    这张表按请求逐条落账：agent 拿钥匙调了哪个动作端、结果如何、金额多少。
    记的是「事」，不是「钱」：写入失败绝不影响请求本身（见 services/runtime_call_log.py）。
    """

    __tablename__ = "runtime_key_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    karma_identity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    # ok / rejected（服务端按权限、额度、nonce、状态拒了）/ failed（异常）
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    http_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, index=True)


class ConsoleNoticeModel(Base):
    """操作台站内提醒：主人自己的钥匙/授权发生了什么，落库留痕。

    邮件通道需要 SMTP 凭据（现网没有），所以「取消绑定之后要留个提醒」这件事
    先落在站内：注销后会写一条，进操作台就能看见红点，点过才消。
    """

    __tablename__ = "console_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    karma_identity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # key_unbound（主人亲手取消绑定）/ key_bound（agent 绑定生效）
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RuntimeKeyModel(Base):
    """
    Stores metadata and a bcrypt hash of the secret segment of a Runtime Key.
    Plaintext ``KRM_RT_*`` tokens are never persisted after creation.
    """

    __tablename__ = "runtime_keys"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    karma_identity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    permissions: Mapped[list] = mapped_column(JSON, nullable=False)
    single_limit: Mapped[float] = mapped_column(Float, nullable=False)
    daily_limit: Mapped[float] = mapped_column(Float, nullable=False)
    expire_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(256), nullable=False)
    agent_binding: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 这把 key 是「服务端托管」（认 key 不认人）还是「钉死在某个 agent 公钥上」（逐请求验签）。
    key_binding: Mapped[str | None] = mapped_column(String(16), nullable=True, default="service")
    # agent 的 Ed25519 裸公钥（base64，32 字节）。绑定后每个请求都要它验签。
    agent_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 会动钱的权限（place_order / request_settlement）→ 每请求强制 nonce。
    nonce_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    # 待确认的接入：agent 申请了绑定、但用户还没在操作台输入匹配码。
    # 只有 pending_code_hash 对上（confirm_key_binding）才会写进 agent_public_key。
    pending_agent_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    pending_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    pending_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# ---------------------------------------------------------------------------
# Reputation
# ---------------------------------------------------------------------------


class ReputationModel(Base):
    __tablename__ = "reputation"

    agent_id:           Mapped[str]   = mapped_column(String(64), ForeignKey("agents.agent_id"), primary_key=True)
    profile_id:         Mapped[str|None] = mapped_column(String(64), nullable=True, index=True)
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
    last_updated: Mapped[datetime]     = mapped_column(UTCDateTime, default=datetime.utcnow)
    last_incident_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_incident_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    onchain_packed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    onchain_packed_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    onchain_pack_tx: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dividend_weight: Mapped[float] = mapped_column(Float, default=0.0)


# ---------------------------------------------------------------------------
# Master identity verification (证件 + 扫脸)
# ---------------------------------------------------------------------------


class IdentityVerificationModel(Base):
    """主身份认证记录：只存密文包与摘要，永远不存证件 / 人脸明文。

    浏览器端先用钱包签名派生的密钥做 AES-GCM 加密，服务端拿到的只有：密文包、
    SHA-256 摘要、加密参数（算法 / KDF / 迭代 / 盐 / IV）以及用户确认过的脱敏字段。
    核验记录本身不构成对外披露，披露要走 identity_disclosures 的显式授权。
    """

    __tablename__ = "identity_verifications"

    identity_id:  Mapped[str]        = mapped_column(String(128), primary_key=True)
    status:       Mapped[str]        = mapped_column(String(16), nullable=False, default="none")
    level:        Mapped[str]        = mapped_column(String(16), nullable=False, default="basic")
    doc_digest:   Mapped[str | None] = mapped_column(String(128), nullable=True)
    face_digest:  Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption:   Mapped[dict]       = mapped_column(JSON, default=dict)
    extracted:    Mapped[dict]       = mapped_column(JSON, default=dict)
    # 第三方实名 / 活体服务商的核验状态（会话号、事件审计）。
    # 只放脱敏的白名单字段：服务商那边自己发号（CertifyId / BizToken / inquiry id）、
    # 结论、原因码；**不放**服务商回传的报文原文，也不放姓名 / 证件号。
    provider:     Mapped[dict]       = mapped_column(JSON, default=dict)
    reviewer_identity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note:  Mapped[str | None] = mapped_column(String(2000), nullable=True)
    verified_at:  Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at:   Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:   Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Data-API economy: verified subjects, published skills, metered usage
#
# 数据 API 是 Karma 第一个真正商业化的品类：调用方与提供方都是「有主体」的公司，
# 单笔金额小、频次高。所以这一层要回答三件事：
#   1. 这家公司是不是真的（主体资质 + 官网控制权）—— entity_verifications
#   2. 这个技能是不是本人上架的（主体认证 + 钱包签名 + 域名归属）—— skills
#   3. 累计到多少才划一次钱（小额高频累计，到阈值才结算）—— usage_meters / charges / settlements
# ---------------------------------------------------------------------------


class EntityVerificationModel(Base):
    """主体资质认证：数据 API 提供方上架前必须先过的关。

    与 ``identity_verifications``（自然人证件 + 扫脸）分开：这里认证的是**主体**
    （企业 / 个体工商户）以及它对**官网**的控制权。资质原件同样只存密文包 + 摘要，
    服务端永远拿不到明文 —— 与自然人认证同一套加密约定。
    """

    __tablename__ = "entity_verifications"

    identity_id:      Mapped[str]        = mapped_column(String(128), primary_key=True)
    status:           Mapped[str]        = mapped_column(String(16), nullable=False, default="none")
    subject_type:     Mapped[str]        = mapped_column(String(16), nullable=False, default="business")
    legal_name:       Mapped[str]        = mapped_column(String(200), nullable=False, default="")
    registration_no:  Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    jurisdiction:     Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    legal_rep:        Mapped[str]        = mapped_column(String(120), nullable=False, default="")
    official_domain:  Mapped[str]        = mapped_column(String(255), nullable=False, default="", index=True)
    contact_email:    Mapped[str]        = mapped_column(String(200), nullable=False, default="")
    service_category: Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    service_scope:    Mapped[str]        = mapped_column(Text, nullable=False, default="")
    # 资质清单 [{kind, name, digest}]：只有名字与摘要，原件在密文包里。
    certifications:   Mapped[list]       = mapped_column(JSON, default=list)
    doc_digest:       Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_digest:   Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_cipher:   Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption:       Mapped[dict]       = mapped_column(JSON, default=dict)
    extracted:        Mapped[dict]       = mapped_column(JSON, default=dict)
    # 官网控制权：域名下放一份一次性 token，服务端回读比对。
    website_token:        Mapped[str | None] = mapped_column(String(128), nullable=True)
    website_challenge_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    website_verified_at:  Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    website_digest:       Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewer_identity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note:      Mapped[str | None] = mapped_column(String(2000), nullable=True)
    verified_at:      Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    submitted_at:     Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at:       Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:       Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillDeveloperModel(Base):
    """技能开发者实名：一个可追责的自然人 + 开发者协议签名存证。

    主体认证回答「这家公司是谁」，这里回答「操作这个身份的是哪个人」。一个身份可以有
    多个开发者档案（每人一个钱包），上架时签名钱包必须命中其中一个**已通过复核**的档案
    —— 见 services/developer_registry.assert_can_publish。签名只能由本人钱包签出，
    ``signer_wallet`` 是 recover 出来的地址，不是客户端自报的。
    """

    __tablename__ = "skill_developers"

    developer_id:      Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    identity_id:       Mapped[str]      = mapped_column(String(128), nullable=False, index=True)
    legal_name:        Mapped[str]      = mapped_column(String(200), nullable=False, default="")
    real_name:         Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    role_title:        Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    contact_email:     Mapped[str]      = mapped_column(String(200), nullable=False, default="")
    developer_role:    Mapped[str]      = mapped_column(String(32), nullable=False, default="developer")
    agreement_version: Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    agreement_digest:  Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    signer_wallet:     Mapped[str | None] = mapped_column(String(128), nullable=True)
    signature:         Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 材料清单 [{kind, name, digest}]+ 密文包：与主体认证同一套「只存密文 + 摘要」约定。
    materials:         Mapped[list]     = mapped_column(JSON, default=list)
    package_digest:    Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_cipher:    Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption:        Mapped[dict]     = mapped_column(JSON, default=dict)
    extracted:         Mapped[dict]     = mapped_column(JSON, default=dict)
    status:            Mapped[str]      = mapped_column(String(16), nullable=False, default="none", index=True)
    reviewer_identity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note:       Mapped[str | None] = mapped_column(String(2000), nullable=True)
    verified_at:       Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    submitted_at:      Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at:        Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillModel(Base):
    """技能 / 插件登记：一个可以被 agent 调用、按次计费的服务。

    ``status`` 只有经过「主体已认证 + 上架签名由本人钱包签出 + endpoint 落在认证过的
    官网域名下」才会变成 ``published``（见 services/skill_registry）。
    """

    __tablename__ = "skills"

    skill_id:          Mapped[str]      = mapped_column(String(64), primary_key=True, default=_uuid)
    owner_identity_id: Mapped[str]      = mapped_column(String(128), nullable=False, index=True)
    slug:              Mapped[str]      = mapped_column(String(80), nullable=False, unique=True)
    name:              Mapped[str]      = mapped_column(String(120), nullable=False)
    category:          Mapped[str]      = mapped_column(String(64), nullable=False, default="data_api")
    summary:           Mapped[str]      = mapped_column(String(300), nullable=False, default="")
    description:       Mapped[str]      = mapped_column(Text, nullable=False, default="")
    endpoint_url:      Mapped[str]      = mapped_column(String(500), nullable=False)
    method:            Mapped[str]      = mapped_column(String(8), nullable=False, default="POST")
    unit:              Mapped[str]      = mapped_column(String(32), nullable=False, default="call")
    unit_price_usdc:   Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)
    settlement_threshold_usdc: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    default_cap_usdc:  Mapped[float | None]  = mapped_column(Float, nullable=True)
    version:           Mapped[int]      = mapped_column(Integer, nullable=False, default=1)
    manifest_digest:   Mapped[str]      = mapped_column(String(64), nullable=False, default="")
    publisher_signature: Mapped[str | None] = mapped_column(String(200), nullable=True)
    publisher_wallet:  Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_domain:   Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 上架时签名钱包对应的开发者实名档案（SKILL_REQUIRE_DEVELOPER_VERIFICATION 关掉时为空）。
    developer_id:      Mapped[str | None] = mapped_column(String(64), nullable=True)
    status:            Mapped[str]      = mapped_column(String(16), nullable=False, default="draft", index=True)
    published_at:      Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    paused_at:         Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at:        Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UsageMeterModel(Base):
    """(付款方, 技能) 的累计计费器：小额高频先记账，到阈值才生成一张结算单。

    钱不在这一步动 —— 这一步只回答「这个调用方一共欠这个技能多少钱」。
    ``cap_usdc`` 是边界：付到这个数就拒绝继续调用（相当于子身份额度）。
    """

    __tablename__ = "usage_meters"

    meter_id:           Mapped[str]        = mapped_column(String(64), primary_key=True, default=_uuid)
    skill_id:           Mapped[str]        = mapped_column(String(64), nullable=False, index=True)
    payer_identity_id:  Mapped[str]        = mapped_column(String(128), nullable=False, index=True)
    provider_identity_id: Mapped[str]      = mapped_column(String(128), nullable=False, index=True)
    calls:              Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    accrued_usdc:       Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    billed_usdc:        Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    settled_usdc:       Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    threshold_usdc:     Mapped[float]      = mapped_column(Float, nullable=False, default=1.0)
    cap_usdc:           Mapped[float | None] = mapped_column(Float, nullable=True)
    status:             Mapped[str]        = mapped_column(String(24), nullable=False, default="open")
    last_used_at:       Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at:         Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    updated_at:         Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("skill_id", "payer_identity_id", name="uq_usage_meter_skill_payer"),
    )


class UsageChargeModel(Base):
    """一次调用 = 一条流水。(skill_id, request_id) 唯一 —— 重放不会重复计费。"""

    __tablename__ = "usage_charges"

    charge_id:          Mapped[str]        = mapped_column(String(64), primary_key=True, default=_uuid)
    request_id:         Mapped[str]        = mapped_column(String(80), nullable=False)
    skill_id:           Mapped[str]        = mapped_column(String(64), nullable=False, index=True)
    payer_identity_id:  Mapped[str]        = mapped_column(String(128), nullable=False, index=True)
    provider_identity_id: Mapped[str]      = mapped_column(String(128), nullable=False, index=True)
    units:              Mapped[int]        = mapped_column(Integer, nullable=False, default=1)
    unit_price_usdc:    Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    amount_usdc:        Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    settlement_id:      Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    occurred_at:        Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    created_at:         Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("skill_id", "request_id", name="uq_usage_charge_skill_request"),
    )


class UsageSettlementModel(Base):
    """阈值结算单：把一段累计的调用打包成一笔真实划转。

    ``mode`` 说明这笔钱走哪条路：``escrow_allowance`` 走 Karma 现有的非托管授权划转
    （调用方的锁仓 → 提供方钱包），``manual`` 表示先出账、由运营/多签合约执行。
    """

    __tablename__ = "usage_settlements"

    settlement_id:      Mapped[str]        = mapped_column(String(64), primary_key=True, default=_uuid)
    skill_id:           Mapped[str]        = mapped_column(String(64), nullable=False, index=True)
    payer_identity_id:  Mapped[str]        = mapped_column(String(128), nullable=False, index=True)
    provider_identity_id: Mapped[str]      = mapped_column(String(128), nullable=False, index=True)
    amount_usdc:        Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    stake_usdc:         Mapped[float]      = mapped_column(Float, nullable=False, default=0.0)
    calls:              Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    status:             Mapped[str]        = mapped_column(String(16), nullable=False, default="open", index=True)
    mode:               Mapped[str]        = mapped_column(String(24), nullable=False, default="escrow_allowance")
    digest:             Mapped[str]        = mapped_column(String(64), nullable=False, default="")
    escrow_binding_id:  Mapped[str | None] = mapped_column(String(64), nullable=True)
    tx_hash:            Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_reason:     Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at:         Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow)
    settled_at:         Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at:         Mapped[datetime]   = mapped_column(UTCDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
