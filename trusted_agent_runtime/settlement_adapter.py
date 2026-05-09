from __future__ import annotations

import os
from typing import Any

from trusted_agent_runtime.schemas import EvidenceBundle, TaskContract, VerificationResult


class SettlementAdapter:
    """
    Maps verification outcome to **existing** Karma `NonCustodialAgentPayment` intent surface.
    Does not broadcast transactions (Phase 2: offchain-only plan objects).
    """

    def __init__(self, contract_name: str = "NonCustodialAgentPayment") -> None:
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
    ) -> dict[str, Any]:
        mode = os.environ.get("SETTLEMENT_MODE", "offchain").lower()
        base: dict[str, Any] = {
            "task_id": task.task_id,
            "bundle_id": bundle.bundle_id,
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
            },
        }

        if verify.decision != "STRUCT_OK":
            base["recommended_calls"] = []
            base["tx_hash"] = None
            base["onchain_status"] = "blocked_structural_failure"
            return base

        # Align with INonCustodialAgentPayment.createBill(seller, token, amount, scopeHash, proofHash, deadline)
        base["recommended_calls"] = [
            {
                "function": "lockFunds",
                "args": {"token": token, "amount": amount_wei},
                "note": "Buyer locks logical capacity before createBill (existing Karma flow).",
            },
            {
                "function": "createBill",
                "args": {
                    "seller": seller,
                    "token": token,
                    "amount": amount_wei,
                    "scopeHash": scope_hex,
                    "proofHash": proof_hash,
                    "deadline": deadline_unix,
                },
                "note": "Use bytes32 scopeHash on-chain; pass 0x-prefixed hex in your client library.",
            },
            {
                "function": "confirmBill",
                "args": {"billId": "<returned_bill_id>"},
                "note": "After buyer confirms delivery / evidence acceptance.",
            },
            {
                "function": "requestBillPayout",
                "args": {"billId": "<returned_bill_id>"},
                "note": "Existing settlement path; may emit InvalidTransferIntent off-chain in clients.",
            },
        ]
        base["tx_hash"] = None
        if mode == "offchain":
            base["onchain_status"] = "offchain_simulated"
        elif mode in ("hybrid", "testnet"):
            base["onchain_status"] = "use_scripts_testnet_full_flow_send"
        else:
            base["onchain_status"] = "pending_testnet_implementation"
        return base
