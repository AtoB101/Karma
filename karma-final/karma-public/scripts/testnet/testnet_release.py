#!/usr/bin/env python3
"""
Execute an on-chain release payment via KarmaSettlementEngine.
Signs EIP-712 Quote and calls submitSettlement().

Usage:
    python scripts/testnet/testnet_release.py --task-id <id> --amount <wei>
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id",   required=True)
    parser.add_argument("--bundle-id", default="demo-bundle-001")
    parser.add_argument("--amount",    type=int, required=True, help="Amount in token base units")
    args = parser.parse_args()

    from datetime import datetime, timedelta
    from core.schemas import (
        EvidenceBundle, TaskContract, TaskStatus,
        VerificationDecision, VerificationResult, VerificationCheck,
    )
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    contract = TaskContract(
        task_id=args.task_id,
        client_agent_id="testnet-client",
        title="Testnet release",
        description="On-chain release test",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=float(args.amount),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )

    bundle = EvidenceBundle(
        bundle_id=args.bundle_id,
        task_id=args.task_id,
        task_contract_hash="0x" + "a" * 64,
        receipt_ids=[], receipt_hashes=[],
        final_result_hash="0x" + "b" * 64,
        total_steps=1, successful_steps=1, failed_steps=0,
        total_duration_ms=500,
        settlement_status=TaskStatus.VERIFIED,
    )

    verification = VerificationResult(
        task_id=args.task_id,
        bundle_id=args.bundle_id,
        decision=VerificationDecision.RELEASE,
        confidence=1.0,
        checks=[VerificationCheck(name="testnet_release", passed=True)],
        notes="Manual testnet release",
    )

    adapter = OnChainSettlementAdapter()

    print(f"[info] Submitting on-chain release...")
    print(f"  Task ID:  {args.task_id}")
    print(f"  Amount:   {args.amount} base units")
    print(f"  Payee:    {__import__('config.settings', fromlist=['settings']).settings.payee_address}")

    result = adapter.release_payment(contract, verification, bundle, args.amount)

    print(f"\n[ok] Transaction submitted!")
    print(f"  tx_hash:      {result.tx_hash}")
    print(f"  block_number: {result.block_number}")
    print(f"  status:       {result.status}")
    print(f"  gas_used:     {result.gas_used}")
    print(f"  quote_id:     {result.quote_id}")


if __name__ == "__main__":
    main()
