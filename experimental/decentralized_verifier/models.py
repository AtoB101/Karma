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
