"""
Karma Decentralized Verification — Rules Package
=================================================
Public, objective verification rules run independently by every verifier node.

Exports:
  structural_verify  — structural integrity of evidence bundles vs task & receipts
  verify_evidence_integrity — objective evidence-integrity, signature, and constraint checks

All rules are pure functions: dict in, decision out. No DB, no network, no private state.
"""
from __future__ import annotations

from decentralized_verifier.rules.structural import structural_verify
from decentralized_verifier.rules.evidence_integrity import verify_evidence_integrity

__all__ = ["structural_verify", "verify_evidence_integrity"]
