"""Off-chain settlement plan builder mapped to KarmaBilateral (not NCPA)."""
from __future__ import annotations

import os
from typing import Any

from decentralized_verifier import (
    AttestationQuorum,
    ChallengeWindow,
    ChallengeWindowStatus,
    QuorumStatus,
)
from evidence_runtime.operational_controls import OperationalControls
from evidence_runtime.schemas import EvidenceBundle, TaskContract, VerificationResult
from evidence_runtime.settlement_idempotency import settlement_step_key


def _bilateral_calls(
    *,
    seller: str,
    token: str,
    amount_wei: int,
    scope_hex: str,
    proof_hash: str,
    deadline_unix: int,
    pause_payout: bool = False,
) -> list[dict[str, Any]]:
    """Canonical recommended call sequence for KarmaBilateral.

    Note on field semantics: ``function`` is a logical plan-step name (used by
    callers for idempotency keys), while ``onchain`` is the real KarmaBilateral
    function selector. The buyer and agent both call the same ``lock(token, amount)``
    (there is no ``lockBuyer``/``lockAgent`` on the contract); the ``party``/``seller``
    keys on the agent step are plan-only metadata and must not be forwarded as
    contract arguments when broadcasting.
    """
    _ = deadline_unix  # retained for plan metadata / client TTL
    calls: list[dict[str, Any]] = [
        {
            "function": "lockBuyer",
            "onchain": "lock",
            "args": {"token": token, "amount": amount_wei},
            "note": "Buyer locks USDC; mints Bill Token 1:1 (MINTED).",
        },
        {
            "function": "lockAgent",
            "onchain": "lock",
            "args": {"token": token, "amount": amount_wei, "party": "agent", "seller": seller},
            "note": "Agent/seller locks matching Bill Token (MINTED).",
        },
        {
            "function": "bind",
            "onchain": "bind",
            "args": {
                "buyerBillId": "<buyer_bill_id>",
                "agentBillId": "<agent_bill_id>",
                "scopeHash": scope_hex,
            },
            "note": "Bilateral bind freezes both bills (BOUND).",
        },
        {
            "function": "settle",
            "onchain": "settle",
            "args": {
                "bindingId": "<binding_id>",
                "proofHash": proof_hash,
            },
            "note": "Submit proof; binding enters FINALIZING (dispute window).",
        },
        {
            "function": "finalizeSettle",
            "onchain": "finalizeSettle",
            "args": {"bindingId": "<binding_id>"},
            "note": "After dispute window; burns bills and releases USDC.",
        },
    ]
    if pause_payout:
        calls = [c for c in calls if c.get("function") not in ("settle", "finalizeSettle")]
    return calls


class SettlementAdapter:
    """
    Maps verification / attestation outcomes to a KarmaBilateral call plan.
    Does not broadcast transactions (offchain plan objects only).
    """

    def __init__(self, contract_name: str = "KarmaBilateral") -> None:
        self.contract_name = contract_name

    def build_offchain_plan(
        self,
        task: TaskContract,
        bundle: EvidenceBundle,
        proof_hash: str,
        scope_hex: str,
        *,
        seller: str,
        token: str,
        amount_wei: int,
        deadline_unix: int,
        verify: VerificationResult,
        controls: OperationalControls | None = None,
    ) -> dict[str, Any]:
        mode = os.environ.get("SETTLEMENT_MODE", "offchain").lower()
        trace_id = task.trace_id or verify.trace_id or ""
        base: dict[str, Any] = {
            "task_id": task.task_id,
            "bundle_id": bundle.bundle_id,
            "trace_id": trace_id,
            "evidence_bundle_digest": verify.evidence_bundle_digest,
            "karma_contract": self.contract_name,
            "mode": mode,
            "proof_hash": proof_hash,
            "scope_hash_hex": scope_hex,
            "verification": {
                "verification_id": verify.verification_id,
                "decision": verify.decision,
                "public_reasons": verify.public_reasons,
                "verified_at": verify.verified_at,
                "trace_id": verify.trace_id,
            },
        }

        if verify.decision != "STRUCT_OK":
            base["recommended_calls"] = []
            base["settlement_step_keys"] = []
            base["tx_hash"] = None
            base["onchain_status"] = "blocked_structural_failure"
            return base

        if controls is not None:
            sb = controls.settlement_block_reason(task)
            if sb:
                base["recommended_calls"] = []
                base["settlement_step_keys"] = []
                base["tx_hash"] = None
                base["onchain_status"] = f"operational_blocked:{sb}"
                base["operational_block"] = sb
                return base

        calls = _bilateral_calls(
            seller=seller,
            token=token,
            amount_wei=amount_wei,
            scope_hex=scope_hex,
            proof_hash=proof_hash,
            deadline_unix=deadline_unix,
            pause_payout=bool(controls and controls.pause_payout),
        )
        if controls is not None and controls.pause_payout:
            base["operational_notes"] = ["pause_payout:settle_finalize_omitted"]

        base["recommended_calls"] = calls
        base["settlement_step_keys"] = [
            {
                "function": c["function"],
                "idempotency_key": settlement_step_key(trace_id, bundle.bundle_id, str(c["function"])),
            }
            for c in calls
        ]
        base["tx_hash"] = None
        if mode == "offchain":
            base["onchain_status"] = "offchain_simulated"
        elif mode in ("hybrid", "testnet"):
            base["onchain_status"] = "use_bilateral_lock_bind_settle"
        else:
            base["onchain_status"] = "pending_testnet_implementation"
        return base

    def build_attested_plan(
        self,
        task: TaskContract,
        bundle: EvidenceBundle,
        proof_hash: str,
        scope_hex: str,
        *,
        quorum: AttestationQuorum,
        challenge_window: ChallengeWindow,
        seller: str,
        token: str,
        amount_wei: int,
        deadline_unix: int,
        controls: OperationalControls | None = None,
        verify: VerificationResult | None = None,
    ) -> dict[str, Any]:
        """
        Settlement plan gated on decentralized attestation quorum + challenge window.

        On success, returns the KarmaBilateral lock → bind → settle → finalizeSettle plan.
        """
        mode = os.environ.get("SETTLEMENT_MODE", "offchain").lower()
        trace_id = task.trace_id or (verify.trace_id if verify else "")
        evidence_bundle_digest = (
            verify.evidence_bundle_digest if verify else quorum.evidence_hash
        )

        base: dict[str, Any] = {
            "task_id": task.task_id,
            "bundle_id": bundle.bundle_id,
            "trace_id": trace_id,
            "evidence_bundle_digest": evidence_bundle_digest,
            "karma_contract": self.contract_name,
            "mode": mode,
            "proof_hash": proof_hash,
            "scope_hash_hex": scope_hex,
            "attestation": {
                "quorum_id": quorum.quorum_id,
                "status": quorum.status.value,
                "threshold": quorum.threshold,
                "total_verifiers": quorum.total_verifiers,
                "valid_signatures": quorum.valid_signatures,
                "decision": quorum.decision,
            },
            "challenge_window": {
                "challenge_id": challenge_window.challenge_id,
                "status": challenge_window.status.value,
                "start_at": challenge_window.start_at,
                "end_at": challenge_window.end_at,
                "duration_seconds": challenge_window.duration_seconds,
            },
        }

        if quorum.status != QuorumStatus.ATTESTED_OK:
            base["recommended_calls"] = []
            base["settlement_step_keys"] = []
            base["tx_hash"] = None
            base["onchain_status"] = f"blocked_quorum:{quorum.status.value}"
            return base

        if challenge_window.status == ChallengeWindowStatus.OPEN:
            base["recommended_calls"] = []
            base["settlement_step_keys"] = []
            base["tx_hash"] = None
            base["onchain_status"] = "blocked_challenge_window_open"
            return base

        if challenge_window.status == ChallengeWindowStatus.DISPUTED:
            base["recommended_calls"] = []
            base["settlement_step_keys"] = []
            base["tx_hash"] = None
            base["onchain_status"] = "blocked_disputed"
            return base

        if controls is not None:
            sb = controls.settlement_block_reason(task)
            if sb:
                base["recommended_calls"] = []
                base["settlement_step_keys"] = []
                base["tx_hash"] = None
                base["onchain_status"] = f"operational_blocked:{sb}"
                base["operational_block"] = sb
                return base

        calls = _bilateral_calls(
            seller=seller,
            token=token,
            amount_wei=amount_wei,
            scope_hex=scope_hex,
            proof_hash=proof_hash,
            deadline_unix=deadline_unix,
            pause_payout=bool(controls and controls.pause_payout),
        )
        if controls is not None and controls.pause_payout:
            base["operational_notes"] = ["pause_payout:settle_finalize_omitted"]

        base["recommended_calls"] = calls
        base["settlement_step_keys"] = [
            {
                "function": c["function"],
                "idempotency_key": settlement_step_key(
                    trace_id, bundle.bundle_id, str(c["function"])
                ),
            }
            for c in calls
        ]
        base["tx_hash"] = None

        if mode == "offchain":
            base["onchain_status"] = "offchain_simulated_attested"
        elif mode in ("hybrid", "testnet"):
            base["onchain_status"] = "use_bilateral_lock_bind_settle"
        else:
            base["onchain_status"] = "pending_testnet_implementation"

        return base
