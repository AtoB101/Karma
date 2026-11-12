"""
Karma Decentralized Verification — Attestation Aggregator
===========================================================
Collects signed VerifierAttestations from independent verifier nodes
and aggregates them into an N-of-M AttestationQuorum.

Design principles:
  - Deduplicates verifier_ids (one attestation per verifier).
  - Enforces evidence_hash consistency (all attestations must agree on
    what evidence they verified).
  - Verifies each attestation's EIP-712 signature before counting.
  - Invalid signatures are silently dropped; only valid ones count.
  - Quorum is reached when valid signatures ≥ threshold.

Typical usage:
    aggregator = AttestationAggregator(threshold=3, total_verifiers=5)
    quorum = await aggregator.collect(attestations)
    if aggregator.is_quorum_reached(quorum):
        verdict = aggregator.get_verdict(quorum)
"""
from __future__ import annotations

import uuid
from typing import Optional

from decentralized_verifier import (
    AttestationQuorum,
    QuorumStatus,
    VerifierAttestation,
    VerifierNodeInfo,
    utc_now_iso,
)
from decentralized_verifier.attestation.signer import verify_attestation


class AttestationAggregator:
    """
    N-of-M attestation aggregator for the Karma decentralized verification network.

    Collects attestations from independent verifier nodes, validates signatures
    and evidence consistency, and determines if a quorum has been reached.

    Parameters:
        threshold:         Number of valid signatures required for quorum (N)
        total_verifiers:   Total number of registered verifiers (M)
        verifier_registry: Optional mapping of verifier_id → VerifierNodeInfo.
                           If provided, attestations from unregistered verifiers
                           are rejected.
    """

    def __init__(
        self,
        *,
        threshold: int = 3,
        total_verifiers: int = 5,
        verifier_registry: dict[str, VerifierNodeInfo] | None = None,
    ):
        if threshold < 1:
            raise ValueError("threshold must be at least 1")
        if total_verifiers < threshold:
            raise ValueError(
                f"total_verifiers ({total_verifiers}) must be ≥ threshold ({threshold})"
            )

        self.threshold = threshold
        self.total_verifiers = total_verifiers
        self.verifier_registry: dict[str, VerifierNodeInfo] = (
            verifier_registry or {}
        )

    # ── Public API ──────────────────────────────────────────────────────

    async def collect(
        self,
        attestations: list[VerifierAttestation],
    ) -> AttestationQuorum:
        """
        Collect and validate attestations, producing an AttestationQuorum.

        Pipeline:
          1. Deduplicate by verifier_id (keep first seen).
          2. Reject unregistered verifiers if registry is set.
          3. Enforce evidence_hash consistency (first attestation's hash
             becomes the canonical hash; mismatches are dropped).
          4. Verify each attestation's EIP-712 signature.
          5. Count valid signatures and compare against threshold.
          6. Determine quorum status and verdict.

        Args:
            attestations: List of VerifierAttestation objects, each with
                          a populated signature field.

        Returns:
            AttestationQuorum with status, decision, and aggregated metadata.
        """
        if not attestations:
            return self._empty_quorum()

        # ── Step 1: Deduplicate by verifier_id ────────────────────────
        seen_ids: set[str] = set()
        deduped: list[VerifierAttestation] = []
        for a in attestations:
            if a.verifier_id not in seen_ids:
                seen_ids.add(a.verifier_id)
                deduped.append(a)

        # ── Step 2: Reject unregistered verifiers ─────────────────────
        if self.verifier_registry:
            deduped = [
                a
                for a in deduped
                if a.verifier_id in self.verifier_registry
                and self.verifier_registry[a.verifier_id].status.value == "active"
            ]

        if not deduped:
            return self._empty_quorum()

        # ── Step 3: Enforce evidence_hash consistency ─────────────────
        canonical_hash = deduped[0].evidence_hash
        consistent: list[VerifierAttestation] = []
        for a in deduped:
            if a.evidence_hash == canonical_hash:
                consistent.append(a)
            # Attestations with mismatched hashes are silently dropped

        if not consistent:
            return self._empty_quorum()

        # ── Step 4 & 5: Verify signatures, count valid ────────────────
        valid_attestations: list[VerifierAttestation] = []
        invalid_count = 0
        for a in consistent:
            if verify_attestation(a):
                valid_attestations.append(a)
            else:
                invalid_count += 1

        valid_count = len(valid_attestations)

        # ── Step 6: Determine quorum status and verdict ───────────────
        if valid_count >= self.threshold:
            status = QuorumStatus.ATTESTED_OK
        else:
            status = QuorumStatus.INSUFFICIENT_SIGNATURES

        task_id = valid_attestations[0].task_id if valid_attestations else ""

        quorum = AttestationQuorum(
            quorum_id=str(uuid.uuid4()),
            task_id=task_id,
            evidence_hash=canonical_hash,
            threshold=self.threshold,
            total_verifiers=self.total_verifiers,
            valid_signatures=valid_count,
            decision=self._compute_verdict(valid_attestations),
            attestation_ids=[a.verifier_id for a in valid_attestations],
            verifier_ids=[a.verifier_id for a in valid_attestations],
            status=status,
            created_at=utc_now_iso(),
        )

        return quorum

    def is_quorum_reached(self, quorum: AttestationQuorum) -> bool:
        """
        Check if the quorum has collected enough valid signatures.

        Args:
            quorum: An AttestationQuorum produced by collect().

        Returns:
            True if valid_signatures ≥ threshold, False otherwise.
        """
        return quorum.status == QuorumStatus.ATTESTED_OK

    def get_verdict(self, quorum: AttestationQuorum) -> str:
        """
        Get the human-readable verdict for a quorum.

        Returns one of:
          - "ATTESTED_OK"   — quorum reached, majority decision is STRUCT_OK
          - "ATTESTED_FAIL" — quorum reached, majority decision is STRUCT_FAIL
          - "insufficient"  — quorum not reached

        Args:
            quorum: An AttestationQuorum produced by collect().

        Returns:
            Verdict string.
        """
        if not self.is_quorum_reached(quorum):
            return "insufficient"
        return quorum.decision

    # ── Internal Helpers ────────────────────────────────────────────────

    def _compute_verdict(
        self,
        valid_attestations: list[VerifierAttestation],
    ) -> str:
        """
        Determine the majority decision from a set of valid attestations.

        "ATTESTED_OK" if majority decided STRUCT_OK, else "ATTESTED_FAIL".
        """
        if not valid_attestations:
            return "ATTESTED_FAIL"

        ok_count = sum(
            1 for a in valid_attestations if a.decision == "STRUCT_OK"
        )
        fail_count = len(valid_attestations) - ok_count

        return "ATTESTED_OK" if ok_count >= fail_count else "ATTESTED_FAIL"

    def _empty_quorum(self) -> AttestationQuorum:
        """Return an empty quorum representing no valid attestations."""
        return AttestationQuorum(
            quorum_id=str(uuid.uuid4()),
            threshold=self.threshold,
            total_verifiers=self.total_verifiers,
            valid_signatures=0,
            decision="ATTESTED_FAIL",
            status=QuorumStatus.INSUFFICIENT_SIGNATURES,
            created_at=utc_now_iso(),
        )

    def __repr__(self) -> str:
        registry_count = len(self.verifier_registry)
        return (
            f"AttestationAggregator("
            f"threshold={self.threshold}/{self.total_verifiers}, "
            f"registry_size={registry_count})"
        )
