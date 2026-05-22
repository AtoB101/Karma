"""
KarmaSolanaVerifier — Core Solana Verification & Settlement Engine
===================================================================

Bridges Karma's off-chain verifiable execution (signed receipts + evidence bundles)
to Solana on-chain settlement. Mirrors the BNB Chain pattern: verify off-chain, then
record proof on-chain via Solana Program Instructions.

Architecture
------------
    Karma Runtime (off-chain)
           │
           ▼
    KarmaSolanaVerifier.verify_and_settle()
           │
           ├─ 1. POST /v1/verify → Karma Runtime
           ├─ 2. Upload Evidence Bundle → Arweave/IPFS
           ├─ 3. Build Solana Transaction (record bundle hash + verdict)
           ├─ 4. Execute x402 payment hook (if configured)
           └─ 5. Return SolanaSettlementResult

Usage
-----
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
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import httpx

from core.schemas import EvidenceBundle, ExecutionReceipt, VerificationDecision, VerificationResult
from .transaction_builder import SolanaTransactionBuilder
from .evidence_store import SolanaEvidenceStore, ArweaveUploader
from .x402 import SolanaX402Hook, SolanaPaymentProof

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data Types
# ═══════════════════════════════════════════════════════════════════

class SolanaSettlementStatus(str, Enum):
    """Settlement outcome on Solana."""
    SETTLED = "settled"            # Fully verified and recorded on-chain
    PENDING_VERIFICATION = "pending_verification"  # Submitted, awaiting confirmation
    REJECTED = "rejected"         # Verification failed
    ERROR = "error"               # Unexpected error during settlement


@dataclass
class SolanaSettlementResult:
    """Result of a Karma → Solana settlement attempt.

    Attributes
    ----------
    task_id : str
        Karma task identifier.
    status : SolanaSettlementStatus
        Final settlement status.
    verdict : VerificationDecision | None
        Karma verification verdict.
    confidence : float
        Karma's confidence score (0.0–1.0).
    solana_tx_signature : str | None
        Base58 Solana transaction signature (if settled on-chain).
    evidence_uri : str | None
        Arweave/IPFS URI of the uploaded evidence bundle.
    bundle_hash_on_chain : str | None
        SHA-256 hash of the evidence bundle, recorded on Solana.
    payment_proof : SolanaPaymentProof | None
        x402 payment proof (if x402 hook was used).
    verified_at : datetime | None
        Timestamp of Karma verification.
    error_message : str | None
        Error detail if status is ERROR or REJECTED.
    """
    task_id: str
    status: SolanaSettlementStatus
    verdict: Optional[VerificationDecision] = None
    confidence: float = 0.0
    solana_tx_signature: Optional[str] = None
    evidence_uri: Optional[str] = None
    bundle_hash_on_chain: Optional[str] = None
    payment_proof: Optional[SolanaPaymentProof] = None
    verified_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def is_success(self) -> bool:
        return self.status == SolanaSettlementStatus.SETTLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "verdict": self.verdict.value if self.verdict else None,
            "confidence": self.confidence,
            "solana_tx_signature": self.solana_tx_signature,
            "evidence_uri": self.evidence_uri,
            "bundle_hash_on_chain": self.bundle_hash_on_chain,
            "payment_proof": self.payment_proof.to_dict() if self.payment_proof else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "error_message": self.error_message,
        }


# ═══════════════════════════════════════════════════════════════════
# Core Verifier
# ═══════════════════════════════════════════════════════════════════

class KarmaSolanaVerifier:
    """
    Off-chain verifier that bridges Karma's cryptographic proof-of-execution
    to Solana on-chain settlement.

    Responsibilities
    ----------------
    1. Submit evidence bundle to Karma Runtime for verification
    2. Upload full bundle to Arweave/IPFS for decentralized auditability
    3. Build and submit a Solana transaction that records:
       - SHA-256 hash of the evidence bundle
       - Verification verdict (APPROVE / REJECT)
       - Arweave/IPFS content URI pointer
    4. Optionally handle x402 payment (Agent-to-Agent payment on Solana)

    Design Notes
    ------------
    - **No new on-chain program required.** Uses existing Solana SPL Token
      and System Program instructions. For MVP, bundle hashes are recorded
      via memo instructions; a dedicated Karma Solana Program can be added
      later for structured on-chain evidence storage.
    - **Stateless.** The verifier itself holds no state; all state lives
      on-chain or in Karma Runtime.
    - **Composable.** Can be used standalone, embedded in Solana agent
      frameworks, or composed with x402 middleware.

    Parameters
    ----------
    karma_endpoint : str
        URL of the Karma Runtime API (e.g., "https://api.karma.xyz").
    api_key : str
        Karma API key for authentication.
    solana_rpc : str
        Solana RPC endpoint (e.g., "https://api.devnet.solana.com").
    evidence_store : SolanaEvidenceStore | None
        Pre-configured evidence store. If None, defaults to ArweaveUploader.
    x402_hook : SolanaX402Hook | None
        Pre-configured x402 payment hook for Agent-to-Agent payments.
    timeout : float
        HTTP timeout in seconds for Karma API calls.

    Example
    -------
    >>> verifier = KarmaSolanaVerifier(
    ...     karma_endpoint="https://api.karma.xyz",
    ...     api_key="karma_...",
    ...     solana_rpc="https://api.devnet.solana.com",
    ... )
    >>> result = await verifier.verify_and_settle(
    ...     task_id="task-001",
    ...     evidence_bundle=bundle,
    ...     signer_keypair=keypair,
    ... )
    >>> print(result.solana_tx_signature)
    """

    def __init__(
        self,
        *,
        karma_endpoint: str,
        api_key: str,
        solana_rpc: str,
        evidence_store: Optional[SolanaEvidenceStore] = None,
        x402_hook: Optional[SolanaX402Hook] = None,
        timeout: float = 30.0,
    ) -> None:
        self.karma_endpoint = karma_endpoint.rstrip("/")
        self._api_key = api_key  # Private — never expose in logs, repr, or errors
        self.solana_rpc = solana_rpc
        self.timeout = timeout

        # Sub-components
        self._tx_builder = SolanaTransactionBuilder(rpc_url=solana_rpc)
        self._evidence_store = evidence_store or ArweaveUploader()
        self._x402_hook = x402_hook

        # Shared HTTP client
        self._http = httpx.AsyncClient(
            base_url=self.karma_endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"KarmaSolanaSDK/{__import__('karma_solana').__version__}",
            },
            timeout=httpx.Timeout(timeout),
        )

    def __repr__(self) -> str:
        """Safe repr — never leaks API key or internal state."""
        return (
            f"KarmaSolanaVerifier("
            f"karma_endpoint={self.karma_endpoint!r}, "
            f"solana_rpc={self.solana_rpc!r})"
        )

    # ── Public API ────────────────────────────────────────────────

    async def verify_and_settle(
        self,
        task_id: str,
        evidence_bundle: EvidenceBundle,
        signer_keypair: Any,  # solders.Keypair (avoid hard import for optional deps)
        *,
        skip_on_chain: bool = False,
        payment_accept: Optional[Any] = None,  # PaymentRequiredAccept from x402
    ) -> SolanaSettlementResult:
        """
        Full verification + settlement pipeline.

        1. Submit bundle to Karma Runtime for verification
        2. Upload evidence bundle to Arweave/IPFS
        3. Record verification result on Solana
        4. (Optional) Execute x402 payment

        Parameters
        ----------
        task_id : str
            Karma task identifier.
        evidence_bundle : EvidenceBundle
            The assembled evidence bundle from Karma SDK.
        signer_keypair : solders.Keypair
            Solana keypair that will sign the settlement transaction.
        skip_on_chain : bool
            If True, skip on-chain recording (dry-run / testing).
        payment_accept : PaymentRequiredAccept | None
            x402 payment option to execute before settlement.

        Returns
        -------
        SolanaSettlementResult
        """
        try:
            # ── Step 1: Off-chain verification via Karma Runtime ──
            verification = await self._verify_bundle(task_id, evidence_bundle)

            if verification is None:
                return SolanaSettlementResult(
                    task_id=task_id,
                    status=SolanaSettlementStatus.ERROR,
                    error_message="Karma Runtime verification returned no result",
                )

            logger.info(
                "Karma verification complete | task=%s | decision=%s | confidence=%.2f",
                task_id, verification.decision.value, verification.confidence,
            )

            # ── Step 2: Upload evidence bundle to Arweave/IPFS ──
            evidence_uri = None
            if evidence_bundle.storage_path is None:
                evidence_uri = await self._evidence_store.upload(evidence_bundle)
            else:
                evidence_uri = evidence_bundle.storage_path

            # ── Step 3: Compute bundle hash for on-chain record ──
            bundle_hash = self._compute_bundle_hash(evidence_bundle)

            # ── Step 4: Build and submit Solana transaction ──
            solana_tx_sig = None
            if not skip_on_chain and verification.decision == VerificationDecision.RELEASE:
                solana_tx_sig = await self._record_on_chain(
                    signer_keypair=signer_keypair,
                    task_id=task_id,
                    bundle_hash=bundle_hash,
                    verdict="APPROVE",
                    confidence=verification.confidence,
                    evidence_uri=evidence_uri,
                )

            # ── Step 5: x402 payment hook (optional) ──
            payment_proof = None
            if self._x402_hook and payment_accept:
                payment_proof = await self._x402_hook.execute_payment(
                    signer_keypair=signer_keypair,
                    accept=payment_accept,
                    task_id=task_id,
                )

            # ── Determine status ──
            if verification.decision == VerificationDecision.RELEASE:
                status = SolanaSettlementStatus.SETTLED
            elif verification.decision in (VerificationDecision.HOLD, VerificationDecision.DISPUTE):
                status = SolanaSettlementStatus.PENDING_VERIFICATION
            else:
                status = SolanaSettlementStatus.REJECTED

            return SolanaSettlementResult(
                task_id=task_id,
                status=status,
                verdict=verification.decision,
                confidence=verification.confidence,
                solana_tx_signature=solana_tx_sig,
                evidence_uri=evidence_uri,
                bundle_hash_on_chain=bundle_hash,
                payment_proof=payment_proof,
                verified_at=verification.verified_at,
            )

        except Exception as exc:
            logger.exception("Settlement failed for task=%s: %s", task_id, exc)
            return SolanaSettlementResult(
                task_id=task_id,
                status=SolanaSettlementStatus.ERROR,
                error_message=str(exc),
            )

    async def verify_only(
        self,
        task_id: str,
        evidence_bundle: EvidenceBundle,
    ) -> Optional[VerificationResult]:
        """
        Submit evidence bundle to Karma Runtime for verification only
        (no on-chain settlement).

        Useful for pre-flight checks or integration testing.
        """
        return await self._verify_bundle(task_id, evidence_bundle)

    async def record_existing_verification(
        self,
        task_id: str,
        verification: VerificationResult,
        evidence_bundle: EvidenceBundle,
        signer_keypair: Any,
    ) -> str:
        """
        Record an already-completed verification result on Solana.

        Use this when verification was done separately (e.g., batch verification).

        Returns
        -------
        str
            Solana transaction signature (Base58).
        """
        bundle_hash = self._compute_bundle_hash(evidence_bundle)
        evidence_uri = evidence_bundle.storage_path

        if evidence_uri is None:
            evidence_uri = await self._evidence_store.upload(evidence_bundle)

        return await self._record_on_chain(
            signer_keypair=signer_keypair,
            task_id=task_id,
            bundle_hash=bundle_hash,
            verdict="APPROVE" if verification.decision == VerificationDecision.RELEASE else "REJECT",
            confidence=verification.confidence,
            evidence_uri=evidence_uri,
        )

    # ── Internal Methods ──────────────────────────────────────────

    async def _verify_bundle(
        self,
        task_id: str,
        bundle: EvidenceBundle,
    ) -> Optional[VerificationResult]:
        """
        POST /v1/verify to Karma Runtime.

        The runtime performs cryptographic verification:
        - Receipt hash consistency checks
        - Signature validation (Ed25519 agent signature)
        - Merkle proof verification of evidence bundle
        - Decision confidence scoring
        """
        payload = {
            "task_id": task_id,
            "bundle_id": bundle.bundle_id,
            "task_contract_hash": bundle.task_contract_hash,
            "receipt_ids": bundle.receipt_ids,
            "receipt_hashes": bundle.receipt_hashes,
            "final_result_hash": bundle.final_result_hash,
            "total_steps": bundle.total_steps,
            "successful_steps": bundle.successful_steps,
            "failed_steps": bundle.failed_steps,
            "total_duration_ms": bundle.total_duration_ms,
            "agent_signature": bundle.agent_signature,
        }
        try:
            resp = await self._http.post("/v1/verify", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return VerificationResult(**data)
        except httpx.HTTPStatusError as exc:
            logger.error("Karma verification HTTP error: %s — %s", exc.response.status_code, exc.response.text[:500])
            return None
        except Exception as exc:
            logger.error("Karma verification failed: %s", exc)
            return None

    def _compute_bundle_hash(self, bundle: EvidenceBundle) -> str:
        """
        Compute a deterministic SHA-256 hash of the evidence bundle.

        Uses the same canonical JSON serialization as Karma core's
        ``EvidenceBundleBuilder`` for cross-chain consistency.
        """
        payload = {
            "bundle_id": bundle.bundle_id,
            "task_id": bundle.task_id,
            "task_contract_hash": bundle.task_contract_hash,
            "receipt_ids": bundle.receipt_ids,
            "receipt_hashes": bundle.receipt_hashes,
            "final_result_hash": bundle.final_result_hash,
            "total_steps": bundle.total_steps,
            "successful_steps": bundle.successful_steps,
            "failed_steps": bundle.failed_steps,
            "total_duration_ms": bundle.total_duration_ms,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "0x" + hashlib.sha256(canonical.encode()).hexdigest()

    async def _record_on_chain(
        self,
        signer_keypair: Any,
        task_id: str,
        bundle_hash: str,
        verdict: str,
        confidence: float,
        evidence_uri: Optional[str],
    ) -> str:
        """
        Build and submit a Solana transaction that records the
        Karma verification result on-chain.

        For MVP, uses a Memo instruction with structured JSON payload.
        A dedicated Karma Solana Program would replace this with typed
        Account + Instruction for production use.

        The memo format:
            KARMA|v1|<task_id>|<bundle_hash>|<verdict>|<confidence>|<evidence_uri>
        """
        memo_payload = json.dumps({
            "protocol": "karma",
            "version": "1",
            "task_id": task_id,
            "bundle_hash": bundle_hash,
            "verdict": verdict,
            "confidence": confidence,
            "evidence_uri": evidence_uri or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        tx_signature = await self._tx_builder.send_memo(
            signer_keypair=signer_keypair,
            memo_text=memo_payload,
        )

        logger.info(
            "Karma settlement recorded on Solana | task=%s | tx=%s | verdict=%s",
            task_id, tx_signature, verdict,
        )
        return tx_signature

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> "KarmaSolanaVerifier":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
