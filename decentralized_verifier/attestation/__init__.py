"""
Karma Decentralized Verification — Attestation Package
=======================================================
EIP-712 attestation signing and verification for Karma verifier nodes.

Exports:
  sign_attestation   — Produce an EIP-712 typed signature over a VerifierAttestation
  verify_attestation — Recover signer and verify the attestation signature
  AttestationAggregator — Collect and aggregate attestations into N-of-M quorums
"""
from __future__ import annotations

from decentralized_verifier.attestation.signer import (
    build_attestation_eip712_payload,
    sign_attestation,
    verify_attestation,
)
from decentralized_verifier.attestation.aggregator import AttestationAggregator

__all__ = [
    "AttestationAggregator",
    "build_attestation_eip712_payload",
    "sign_attestation",
    "verify_attestation",
]
