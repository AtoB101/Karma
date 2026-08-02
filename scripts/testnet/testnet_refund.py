#!/usr/bin/env python3
"""
On-chain refund via KarmaBilateral.

  --binding-id  → refundOnTimeout(bindingId)
  --bill-id     → unlock(billId) for unbound MINTED bills

Usage:
    python scripts/testnet/testnet_refund.py --task-id <id> --binding-id <n>
    python scripts/testnet/testnet_refund.py --task-id <id> --bill-id <n>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="KarmaBilateral refundOnTimeout / unlock")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--binding-id", type=int, default=None)
    parser.add_argument("--bill-id", type=int, default=None)
    args = parser.parse_args()

    if args.binding_id is None and args.bill_id is None:
        parser.error("Provide --binding-id and/or --bill-id")

    from core.schemas import TaskContract, VerificationCheck, VerificationDecision, VerificationResult
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    contract = TaskContract(
        task_id=args.task_id,
        client_agent_id="testnet-client",
        title="Testnet refund",
        description="KarmaBilateral refund",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=0.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
        onchain_binding_id=args.binding_id,
        onchain_buyer_bill_id=args.bill_id,
    )
    verification = VerificationResult(
        task_id=args.task_id,
        bundle_id="bundle-refund",
        decision=VerificationDecision.REFUND,
        confidence=1.0,
        checks=[VerificationCheck(name="testnet", passed=False)],
        notes="testnet_refund",
    )

    adapter = OnChainSettlementAdapter()
    result = adapter.refund_payment(args.task_id, verification, task_contract=contract)
    print("[ok] refund:")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
