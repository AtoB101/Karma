"""
Karma Decentralized Verification — Public Schemas
===================================================
Shared data structures for the decentralized verification layer.
These are the canonical types that Verifier Nodes, Attestation
Aggregator, Challenge Window, and Settlement Adapter build against.

All schemas are public-safe — no private rules, no secret scoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from enum import Enum


# ═══════════════════════════════════════════════════════════════════
# Verifier Attestation
# ═══════════════════════════════════════════════════════════════════

class AttestationDecision(str, Enum):
    STRUCT_OK = "STRUCT_OK"
    STRUCT_FAIL = "STRUCT_FAIL"


@dataclass
class VerifierAttestation:
    """
    A single verifier node's signed attestation over an evidence bundle.

    Uses EIP-712 typed signing for on-chain verifiability.
    """
    attestation_version: str = "karma-attestation-v1"
    task_id: str = ""
    bundle_id: str = ""
    evidence_hash: str = ""        # SHA-256 of evidence bundle (64-char hex)
    cid: str = ""                  # IPFS / Arweave content identifier
    verifier_id: str = ""
    verifier_wallet: str = ""      # Ethereum address (0x...)
    decision: str = ""             # STRUCT_OK | STRUCT_FAIL
    reason_codes: list[str] = field(default_factory=list)
    verified_at: str = ""          # ISO-8601
    chain_id: int = 0
    contract_address: str = ""     # VerifierRegistry address
    signature: str = ""            # EIP-712 signature (0x...)

    def to_eip712_dict(self) -> dict[str, Any]:
        """Canonical dict for EIP-712 signing."""
        return {
            "attestation_version": self.attestation_version,
            "task_id": self.task_id,
            "bundle_id": self.bundle_id,
            "evidence_hash": self.evidence_hash,
            "cid": self.cid,
            "verifier_id": self.verifier_id,
            "verifier_wallet": self.verifier_wallet,
            "decision": self.decision,
            "reason_codes": self.reason_codes,
            "verified_at": self.verified_at,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
        }


# ═══════════════════════════════════════════════════════════════════
# Attestation Quorum
# ═══════════════════════════════════════════════════════════════════

class QuorumStatus(str, Enum):
    COLLECTING = "collecting"
    ATTESTED_OK = "attested_ok"
    ATTESTED_FAIL = "attested_fail"
    INSUFFICIENT_SIGNATURES = "insufficient_signatures"


@dataclass
class AttestationQuorum:
    """Aggregated result from N-of-M verifier attestations."""
    quorum_id: str = ""
    task_id: str = ""
    evidence_hash: str = ""
    threshold: int = 3              # N in N-of-M
    total_verifiers: int = 5        # M in N-of-M
    valid_signatures: int = 0
    decision: str = ""              # ATTESTED_OK | ATTESTED_FAIL
    attestation_ids: list[str] = field(default_factory=list)
    verifier_ids: list[str] = field(default_factory=list)
    status: QuorumStatus = QuorumStatus.COLLECTING
    created_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# Challenge Window
# ═══════════════════════════════════════════════════════════════════

class ChallengeWindowStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    DISPUTED = "disputed"


class ChallengeDecision(str, Enum):
    UPHELD = "upheld"       # Challenge valid, settlement blocked
    OVERRULED = "overruled" # Challenge invalid, settlement proceeds


@dataclass
class ChallengeWindow:
    """Time window after attestation where anyone can challenge."""
    challenge_id: str = ""
    task_id: str = ""
    evidence_hash: str = ""
    start_at: str = ""          # ISO-8601
    end_at: str = ""            # ISO-8601
    duration_seconds: int = 1800  # Default: 30 min for API/MCP tasks
    status: ChallengeWindowStatus = ChallengeWindowStatus.PENDING


@dataclass
class ChallengeRecord:
    """A challenge raised during the challenge window."""
    challenge_id: str = ""
    task_id: str = ""
    challenger_wallet: str = ""     # 0x...
    reason_code: str = ""           # e.g., "evidence_hash_mismatch"
    evidence_hash: str = ""
    challenge_evidence_cid: str = ""  # IPFS CID of challenge evidence
    status: str = ""                # open | resolved | dismissed
    decision: str = ""              # upheld | overruled
    created_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# Evidence Publication
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EvidencePublication:
    """Record of an evidence bundle published to decentralized storage."""
    id: str = ""
    task_id: str = ""
    bundle_id: str = ""
    evidence_hash: str = ""         # SHA-256 of bundle
    cid: str = ""                   # IPFS CID or Arweave tx_id
    storage_provider: str = "ipfs"  # ipfs | arweave | minio
    published_at: str = ""
    publisher_actor: str = ""
    publisher_signature: str = ""


# ═══════════════════════════════════════════════════════════════════
# Verifier Registry Entry
# ═══════════════════════════════════════════════════════════════════

class VerifierStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    SLASHED = "slashed"
    PENDING = "pending"


@dataclass
class VerifierNodeInfo:
    """Record of a registered verifier node."""
    verifier_id: str = ""
    wallet_address: str = ""        # 0x...
    public_key: str = ""            # hex
    endpoint_url: str = ""          # https://verifier.example.com
    status: VerifierStatus = VerifierStatus.PENDING
    stake_amount: int = 0           # wei
    reputation_score: float = 0.0
    success_count: int = 0
    false_attestation_count: int = 0
    slashed_count: int = 0
    joined_at: str = ""
    created_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# Challenge Window Durations (per task type)
# ═══════════════════════════════════════════════════════════════════

CHALLENGE_DURATIONS: dict[str, int] = {
    "api": 1800,                    # 30 minutes
    "mcp": 1800,                    # 30 minutes
    "data_content": 86400,          # 24 hours
    "ai_content": 86400,            # 24 hours
    "multi_agent": 86400,           # 24 hours
    "chain_operation": 1800,        # 30 minutes after confirmation
    "default": 1800,
}


def utc_now_iso() -> str:
    """ISO-8601 timestamp in UTC with Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
