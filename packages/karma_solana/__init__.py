"""
Karma Trust Protocol — Solana Integration SDK
==============================================

Plugs Karma's verifiable execution (signed receipts + evidence bundles)
into the Solana agent ecosystem (x402, Agent-to-Agent payments, Verifiable Execution).

Quickstart
----------
    from karma_solana import KarmaSolanaVerifier

    verifier = KarmaSolanaVerifier(
        karma_endpoint="https://api.karma.xyz",
        api_key="karma_...",
        solana_rpc="https://api.devnet.solana.com",
    )

    result = await verifier.verify_and_settle(
        task_id="task-001",
        evidence_bundle=bundle,
        signer_keypair=keypair,
    )

See the README for the full guide.
"""

from __future__ import annotations

try:
    from .verifier import KarmaSolanaVerifier, SolanaSettlementResult
    from .transaction_builder import SolanaTransactionBuilder
except ImportError:
    KarmaSolanaVerifier = None  # type: ignore
    SolanaSettlementResult = None  # type: ignore
    SolanaTransactionBuilder = None  # type: ignore
from .evidence_store import SolanaEvidenceStore, ArweaveUploader
from .x402 import SolanaX402Hook, SolanaPaymentProof

__all__ = [
    # Core verifier
    "KarmaSolanaVerifier",
    "SolanaSettlementResult",
    # Transaction building
    "SolanaTransactionBuilder",
    # Evidence storage
    "SolanaEvidenceStore",
    "ArweaveUploader",
    # x402 payments
    "SolanaX402Hook",
    "SolanaPaymentProof",
]

__version__ = "0.1.0"
