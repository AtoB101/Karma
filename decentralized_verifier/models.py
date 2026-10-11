"""
Karma Decentralized Verifier — Database Models
===============================================
SQLAlchemy ORM models for verifier nodes, attestations, and challenges.

These models extend the shared Base from db.models.orm so that Alembic
autogenerate can discover them.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.orm import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════
# Verifier Node
# ═══════════════════════════════════════════════════════════════════

class VerifierNode(Base):
    __tablename__ = "verifier_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    wallet_address: Mapped[str] = mapped_column(
        String(42), nullable=False, unique=True, index=True
    )
    stake_amount: Mapped[float] = mapped_column(Float, default=0.0)
    reputation_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_attestations: Mapped[int] = mapped_column(Integer, default=0)
    successful_attestations: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(2048))
    # ── G12：质押金库（bond）相关列 ─────────────────────────────────────
    # 主人身份：节点钱包必须与该身份绑定的钱包一致（见 services/verifier_bond.py）。
    # 为空 = 运维/白名单直接建档的「名单档」：跟名单，不跟押金（历史行留空）。
    owner_identity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # 现算出来的在任状态：active / no_stake / below_min / unbacked / cooling / released
    # / appointed。它是**快照**，不是通行证 —— 每次动权限都重新算一遍。
    bond_state: Mapped[str] = mapped_column(String(16), default="appointed")
    # 登记那一刻承诺的保证金下限（记「当时的口径」，真正的钱在链上与 capacity 镜像里）。
    bond_floor: Mapped[float] = mapped_column(Float, default=0.0)
    # 退出冷却：发起退出时的时间与额度；冷却期内保证金**仍可被罚没**。
    unbond_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    unbond_amount: Mapped[float] = mapped_column(Float, default=0.0)
    # 判负但链上出账没落定的金额：禁止同钱包再登记，并从未来奖励里先扣。
    slash_unsettled: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# ═══════════════════════════════════════════════════════════════════
# Attestation
# ═══════════════════════════════════════════════════════════════════

class Attestation(Base):
    __tablename__ = "attestations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verifier_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("verifier_nodes.id"), nullable=False
    )
    bundle_id: Mapped[str | None] = mapped_column(String(64))
    bundle_cid: Mapped[str | None] = mapped_column(String(256))  # IPFS CID
    decision: Mapped[str | None] = mapped_column(
        String(32)
    )  # ATTESTED_OK, ATTESTED_FAIL, FLAGGED
    confidence: Mapped[float | None] = mapped_column(Float)
    checks_passed: Mapped[int] = mapped_column(Integer, default=0)
    checks_total: Mapped[int] = mapped_column(Integer, default=0)
    eip712_signature: Mapped[str | None] = mapped_column(Text)  # EIP-712 signature hex
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════
# Challenge
# ═══════════════════════════════════════════════════════════════════

class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bundle_id: Mapped[str | None] = mapped_column(String(64))
    raised_by: Mapped[str | None] = mapped_column(String(128))  # agent_id
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")  # OPEN, ACTIVE, RESOLVED, EXPIRED
    window_start: Mapped[datetime | None] = mapped_column(DateTime)
    window_end: Mapped[datetime | None] = mapped_column(DateTime)
    quorum_size: Mapped[int] = mapped_column(Integer, default=3)
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


# ═══════════════════════════════════════════════════════════════════
# Bond Slash Ledger（G12 罚没台账）
# ═══════════════════════════════════════════════════════════════════

class BondSlash(Base):
    """一笔罚没的**台账**：先落账、后出账（见 services/bond_slash.py）。

    为什么要有它
    ------------
    在 G12 之前，「挑战判负」只是把 ``challenges.status`` 写成一个自由文本 ——
    不改节点状态、不动钱、不扣分。这张表把「判负」变成有后果的一件事，并且
    **幂等**：同一（主体, 来源）只允许一条记录，重复裁决不会重复扣款。

    出账是异步的：金库合约还没部署（``VERIFIER_BOND_VAULT_ADDRESS`` 为空）时，
    状态停在 ``pending`` —— 账已经记了、节点已经停了，但钱没动，**不许**伪装成
    ``settled``。线上金库部署到位后由 ``settle_bond_slash`` 推进到 ``submitted``
    / ``settled`` / ``failed``。
    """
    __tablename__ = "bond_slashes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    # verifier_node（节点质押） | arbitrator_role（仲裁员被推翻）
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 节点：verifier_nodes.id；仲裁员：identity_role_profiles.owner_identity_id
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 被罚没主体在链上的保证金钱包（金库合约里的 bond 归属）。
    wallet_address: Mapped[str | None] = mapped_column(String(42))
    # 受害方（80% 收款人）。为空 = 没有可指认的受害方，那 80% 也进池。
    victim_wallet_address: Mapped[str | None] = mapped_column(String(42))
    victim_identity_id: Mapped[str | None] = mapped_column(String(64))
    # challenge | arbitration_overturn
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    victim_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pool_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    victim_share_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=8000)
    pool_share_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    reason: Mapped[str | None] = mapped_column(Text)
    # pending | submitted | settled | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "subject_kind", "subject_id", "source_kind", "source_id",
            name="uq_bond_slash_source",
        ),
    )
