#!/usr/bin/env python3
"""
Record an off-chain refund decision.
KarmaSettlementEngine has no on-chain refund method — this records
the decision in the runtime without any chain interaction.

Usage:
    python scripts/testnet/testnet_refund.py --task-id <id>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()

    from core.schemas import VerificationDecision, VerificationResult, VerificationCheck
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    verification = VerificationResult(
        task_id=args.task_id,
        bundle_id="testnet-bundle",
        decision=VerificationDecision.REFUND,
        confidence=0.95,
        checks=[VerificationCheck(name="testnet_refund", passed=True)],
        notes="Manual testnet refund",
    )

    adapter = OnChainSettlementAdapter()
    result  = adapter.refund_payment(args.task_id, verification)
    print(f"[ok] Refund recorded (off-chain):")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("\n[note] The existing KarmaSettlementEngine has no on-chain refund method.")
    print("       Funds remain with the payer — submitSettlement() was never called.")


if __name__ == "__main__":
    main()
