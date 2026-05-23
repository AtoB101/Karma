"""
Karma Decentralized Verifier — Pydantic Schemas
================================================
Request/response schemas for the Verifier Network API routes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# Verifier Node Schemas
# ═══════════════════════════════════════════════════════════════════

class VerifierRegisterRequest(BaseModel):
    """Request to register a new verifier node."""
    wallet_address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    stake_amount: float = Field(default=0.0, ge=0.0)
    endpoint_url: Optional[str] = Field(default=None)


class VerifierStakeUpdateRequest(BaseModel):
    """Request to update verifier stake amount."""
    stake_amount: float = Field(..., ge=0.0)


class VerifierNodeResponse(BaseModel):
    """Public response for a verifier node."""
    id: str
    wallet_address: str
    stake_amount: float
    reputation_score: float
    total_attestations: int
    successful_attestations: int
    is_active: bool
    endpoint_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VerifierListResponse(BaseModel):
    """List of verifier nodes."""
    verifiers: list[VerifierNodeResponse]
    total: int


# ═══════════════════════════════════════════════════════════════════
# Attestation Schemas
# ═══════════════════════════════════════════════════════════════════

class AttestationSubmitRequest(BaseModel):
    """Request to submit an attestation."""
    task_id: str
    verifier_id: str
    bundle_id: Optional[str] = None
    bundle_cid: Optional[str] = None
    decision: str = Field(..., pattern=r"^(ATTESTED_OK|ATTESTED_FAIL|FLAGGED)$")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    checks_passed: int = Field(default=0, ge=0)
    checks_total: int = Field(default=0, ge=0)
    eip712_signature: Optional[str] = None


class AttestationResponse(BaseModel):
    """Public response for an attestation."""
    id: str
    task_id: str
    verifier_id: str
    bundle_id: Optional[str] = None
    bundle_cid: Optional[str] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    checks_passed: int
    checks_total: int
    eip712_signature: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AttestationListResponse(BaseModel):
    """List of attestations for a task."""
    attestations: list[AttestationResponse]
    task_id: str
    total: int


# ═══════════════════════════════════════════════════════════════════
# Challenge Schemas
# ═══════════════════════════════════════════════════════════════════

class ChallengeOpenRequest(BaseModel):
    """Request to open a challenge."""
    task_id: str
    bundle_id: Optional[str] = None
    raised_by: Optional[str] = None
    reason: Optional[str] = None
    quorum_size: int = Field(default=3, ge=1)


class ChallengeResolveRequest(BaseModel):
    """Request to resolve a challenge."""
    resolution: str
    status: str = Field(..., pattern=r"^(RESOLVED|DISMISSED)$")


class ChallengeResponse(BaseModel):
    """Public response for a challenge."""
    id: str
    task_id: str
    bundle_id: Optional[str] = None
    raised_by: Optional[str] = None
    reason: Optional[str] = None
    status: str
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    quorum_size: int
    resolution: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════
# Network Stats Schema
# ═══════════════════════════════════════════════════════════════════

class NetworkStatsResponse(BaseModel):
    """Network-wide statistics."""
    total_verifiers: int
    active_verifiers: int
    total_attestations: int
    total_challenges: int
    open_challenges: int
    average_reputation: float
