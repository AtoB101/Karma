#!/usr/bin/env python3
"""
Submit KarmaBilateral.settle(bindingId, proofHash) → FINALIZING.

Does not finalize; after the dispute window run:
  python scripts/testnet/testnet_finalize.py --binding-id <n>

Usage:
    python scripts/testnet/testnet_release.py \\
      --task-id <id> --binding-id <n> --amount <base-units>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="KarmaBilateral settle (→ FINALIZING)")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--binding-id", type=int, required=True)
    parser.add_argument("--amount", type=int, default=100)
    args = parser.parse_args()

    from core.schemas import (
        EvidenceBundle,
        TaskContract,
        TaskStatus,
        VerificationCheck,
        VerificationDecision,
        VerificationResult,
    )
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    contract = TaskContract(
        task_id=args.task_id,
        client_agent_id="testnet-client",
        worker_agent_id="testnet-worker",
        title="Testnet settle",
        description="KarmaBilateral settle",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=float(args.amount),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
        onchain_binding_id=args.binding_id,
    )
    bundle = EvidenceBundle(
        task_id=args.task_id,
        task_contract_hash="a" * 64,
        receipt_ids=[],
        receipt_hashes=[],
        final_result_hash="b" * 64,
        total_steps=0,
        successful_steps=0,
        failed_steps=0,
        total_duration_ms=0,
        settlement_status=TaskStatus.VERIFIED,
    )
    verification = VerificationResult(
        task_id=args.task_id,
        bundle_id=bundle.bundle_id,
        decision=VerificationDecision.RELEASE,
        confidence=1.0,
        checks=[VerificationCheck(name="testnet", passed=True)],
        notes="testnet_release",
    )

    adapter = OnChainSettlementAdapter()
    tx = adapter.release_payment(contract, verification, bundle, args.amount)
    print("[ok] settle submitted (FINALIZING):")
    print(f"  tx_hash: {tx.tx_hash}")
    print(f"  binding_id: {tx.binding_id}")
    print(f"  status: {tx.status}")
    print("  next: wait dispute window, then testnet_finalize.py --binding-id ...")


if __name__ == "__main__":
    main()
