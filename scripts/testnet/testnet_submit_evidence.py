#!/usr/bin/env python3
"""
Compute and display the evidence bundle hash that will be embedded
in the EIP-712 scopeHash when release_payment() is called.

Usage:
    python scripts/testnet/testnet_submit_evidence.py --task-id <id> --bundle-id <id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id",   required=True)
    parser.add_argument("--bundle-id", required=True)
    args = parser.parse_args()

    from datetime import datetime
    from core.schemas import EvidenceBundle, TaskStatus
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    # Minimal bundle for hash computation
    bundle = EvidenceBundle(
        bundle_id=args.bundle_id,
        task_id=args.task_id,
        task_contract_hash="a" * 64,
        receipt_ids=[],
        receipt_hashes=[],
        final_result_hash="b" * 64,
        total_steps=0,
        successful_steps=0,
        failed_steps=0,
        total_duration_ms=0,
        settlement_status=TaskStatus.SUBMITTED,
    )

    adapter     = OnChainSettlementAdapter()
    bundle_hash = adapter.submit_evidence_hash(args.task_id, bundle)

    print(f"[ok] Evidence bundle hash: {bundle_hash}")
    print(f"     Task ID:   {args.task_id}")
    print(f"     Bundle ID: {args.bundle_id}")
    print(f"     This hash will be embedded in scopeHash during release_payment().")


if __name__ == "__main__":
    main()
