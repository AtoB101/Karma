"""
Karma Decentralized Verification — Verifier Node
=================================================
Independent verifier node that fetches evidence via CID, runs public
verification rules, and produces signed EIP-712 attestations.
"""
from __future__ import annotations

from decentralized_verifier.node.verifier import KarmaVerifierNode

__all__ = ["KarmaVerifierNode"]
