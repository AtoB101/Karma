"""
Karma Decentralized Verifier — Pydantic Schemas
================================================
Request/response schemas for the Verifier Network API routes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# Verifier Node Schemas
# ═══════════════════════════════════════════════════════════════════

class NodeSignatureFields(BaseModel):
    """节点自有 key 的签名两件套（见 services/verifier_wallet.py）。

    ``signature`` 是节点钱包对 ``POST /v1/verifiers/sign-message`` 给出的那段文字签的
    EIP-191 personal message；``signature_nonce`` 是同一段文字里的一次性随机串，
    服务端按（钱包, 端点, nonce）去重防重放。
    ``VERIFIER_REQUIRE_NODE_SIGNATURE`` 打开后没有这两样一律拒。
    """

    signature: Optional[str] = Field(default=None)
    signature_nonce: Optional[str] = Field(default=None, max_length=128)


class VerifierRegisterRequest(NodeSignatureFields):
    """Request to register a new verifier node."""
    wallet_address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    stake_amount: float = Field(default=0.0, ge=0.0)
    endpoint_url: Optional[str] = Field(default=None)


class VerifierStakeUpdateRequest(NodeSignatureFields):
    """Request to update verifier stake amount.

    签名要对到**库里那条节点的钱包**上（按 verifier_id 查），所以这里不收
    wallet_address —— 收了也只能是同一个值，多一个可自报的字段就是多一条歧义。
    """
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

class AttestationSubmitRequest(NodeSignatureFields):
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

class ChallengeOpenRequest(NodeSignatureFields):
    """Request to open a challenge."""
    task_id: str
    bundle_id: Optional[str] = None
    raised_by: Optional[str] = None
    reason: Optional[str] = None
    quorum_size: int = Field(default=3, ge=1)
    # 挑战是节点发起的：签名要对到发起节点的钱包（登记过的节点钱包）。
    wallet_address: Optional[str] = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")


class ChallengeResolveRequest(NodeSignatureFields):
    """Request to resolve a challenge."""
    resolution: str
    status: str = Field(..., pattern=r"^(RESOLVED|DISMISSED)$")
    wallet_address: Optional[str] = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")


class NodeSignMessageRequest(BaseModel):
    """按动作要一段待签文字：payload 就是即将发出的请求体（外加 signature_nonce）。"""

    kind: str = Field(..., pattern=r"^(register|stake|attestation|challenge|challenge_resolve)$")
    payload: dict[str, Any] = Field(default_factory=dict)


class NodeSignMessageResponse(BaseModel):
    """待签文字 + 它绑定的那个 nonce。"""

    kind: str
    message: str
    nonce: str


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
