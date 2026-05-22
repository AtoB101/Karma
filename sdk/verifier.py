"""
Karma SDK — Decentralized Verifier Client
===========================================
High-level client for the decentralized verification layer.
One import surface for Evidence Publisher + Verifier Node + Attestation.

    from karma.sdk import DecentralizedVerifier

    dv = DecentralizedVerifier(
        verifier_id="node-001",
        wallet_address="0x...",
        karma_endpoint="https://api.karma.xyz",
        api_key="karma_...",
    )
    # Publish evidence
    pub = await dv.publish_evidence(bundle_dict, publisher_id="agent-001")
    
    # Run as verifier node
    attestation = await dv.verify_and_attest(task_dict, bundle_dict, receipts)

    # Check quorum
    quorum = dv.aggregator.collect(attestations)
    if dv.aggregator.is_quorum_reached(quorum):
        print(f"Settlement approved: {quorum.decision}")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from decentralized_verifier import (
    AttestationQuorum,
    ChallengeWindow,
    ChallengeWindowStatus,
    EvidencePublication,
    QuorumStatus,
    VerifierAttestation,
    VerifierNodeInfo,
)
from decentralized_verifier.attestation.aggregator import AttestationAggregator
from decentralized_verifier.attestation.signer import sign_attestation, verify_attestation
from decentralized_verifier.challenge.window import ChallengeWindowManager
from decentralized_verifier.node.verifier import KarmaVerifierNode
from decentralized_verifier.publisher import EvidencePublisher
from decentralized_verifier.rules.structural import structural_verify
from decentralized_verifier.rules.evidence_integrity import verify_evidence_integrity


@dataclass
class DecentralizedVerifierConfig:
    """Configuration for the DecentralizedVerifier SDK client."""
    verifier_id: str = ""
    wallet_address: str = ""
    private_key_hex: str = ""          # For EIP-712 attestation signing
    karma_endpoint: str = "http://localhost:8000"
    api_key: str = ""
    ipfs_gateway: str = "https://ipfs.io"
    verifier_registry_url: str = ""
    default_threshold: int = 3
    default_challenge_seconds: int = 1800  # 30 min
    signer: Optional[Callable] = None  # Custom signing callback


class DecentralizedVerifier:
    """
    High-level SDK client for Karma's decentralized verification layer.

    Bundles Evidence Publisher, Verifier Node, Attestation Aggregator,
    and Challenge Window into a single interface.

    Usage
    -----
        dv = DecentralizedVerifier(verifier_id="node-001", wallet_address="0x...")
        
        # As publisher
        pub = await dv.publish_evidence(bundle, "agent-001")
        
        # As verifier
        att = await dv.verify_and_attest(task, bundle, receipts)
        
        # Check settlement readiness
        ready = dv.check_settlement_ready(quorum, challenge_window)
    """

    def __init__(self, config: DecentralizedVerifierConfig) -> None:
        self.config = config

        # Sub-components
        self.publisher = EvidencePublisher(
            ipfs_gateway=config.ipfs_gateway,
            signer=config.signer,
        )
        self.node = KarmaVerifierNode(
            verifier_id=config.verifier_id,
            wallet_address=config.wallet_address,
            verifier_registry_url=config.verifier_registry_url,
        )
        self.aggregator = AttestationAggregator(
            threshold=config.default_threshold,
        )
        self.challenge_manager = ChallengeWindowManager(
            default_duration_seconds=config.default_challenge_seconds,
        )

    # ── Evidence Publishing ─────────────────────────────────────────

    async def publish_evidence(
        self, bundle: dict[str, Any], publisher_id: str
    ) -> EvidencePublication:
        """Publish evidence bundle to IPFS + MinIO. Returns publication record."""
        return await self.publisher.publish(bundle, publisher_id)

    async def verify_publication(self, cid: str, expected_hash: str) -> bool:
        """Verify a published evidence bundle by CID."""
        return await self.publisher.verify_publication(cid, expected_hash)

    # ── Verification ────────────────────────────────────────────────

    async def verify_and_attest(
        self,
        task: dict[str, Any],
        bundle: dict[str, Any],
        receipts: list[dict[str, Any]],
        cid: str = "",
    ) -> VerifierAttestation:
        """Run structural + evidence integrity checks and produce signed attestation."""
        attestation = await self.node.verify(task, bundle, receipts, cid)
        if self.config.private_key_hex:
            attestation.signature = sign_attestation(
                attestation, self.config.private_key_hex
            )
        elif self.config.signer:
            attestation.signature = self.config.signer(
                attestation.to_eip712_dict()
            )
        return attestation

    # ── Quorum ──────────────────────────────────────────────────────

    async def collect_quorum(
        self, attestations: list[VerifierAttestation]
    ) -> AttestationQuorum:
        """Collect attestations and compute quorum status."""
        return await self.aggregator.collect(attestations)

    def is_quorum_reached(self, quorum: AttestationQuorum) -> bool:
        """Check if N-of-M attestation threshold is met."""
        return self.aggregator.is_quorum_reached(quorum)

    # ── Challenge Window ────────────────────────────────────────────

    def open_challenge_window(
        self, task_id: str, evidence_hash: str, task_type: str = "default"
    ) -> ChallengeWindow:
        """Open a challenge window for a verified task."""
        return self.challenge_manager.open_window(task_id, evidence_hash, task_type)

    def raise_challenge(
        self,
        window: ChallengeWindow,
        challenger: str,
        reason: str,
        evidence_cid: str = "",
    ) -> Any:
        """Raise a challenge during the challenge window."""
        return self.challenge_manager.raise_challenge(
            window, challenger, reason, evidence_cid
        )

    # ── Settlement Readiness ────────────────────────────────────────

    def check_settlement_ready(
        self, quorum: AttestationQuorum, challenge_window: ChallengeWindow
    ) -> tuple[bool, str]:
        """
        Check if a task is ready for settlement.

        Returns (ready: bool, reason: str).
        Settlement requires: quorum ATTESTED_OK + challenge window CLOSED + no dispute.
        """
        if quorum.status != QuorumStatus.ATTESTED_OK:
            return False, f"quorum not reached: {quorum.status.value}"
        if not self.challenge_manager.is_window_closed(challenge_window):
            return False, "challenge window still open"
        if challenge_window.status == ChallengeWindowStatus.DISPUTED:
            return False, "task is disputed"
        return True, "ready for settlement"


# ── Re-export public functions for direct use ──────────────────────

__all__ = [
    "DecentralizedVerifier",
    "DecentralizedVerifierConfig",
    "EvidencePublisher",
    "KarmaVerifierNode",
    "AttestationAggregator",
    "ChallengeWindowManager",
    "structural_verify",
    "verify_evidence_integrity",
    "sign_attestation",
    "verify_attestation",
]
