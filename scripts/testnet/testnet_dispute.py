#!/usr/bin/env python3
"""
Record an off-chain dispute.
KarmaSettlementEngine has no on-chain dispute method.

Usage:
    python scripts/testnet/testnet_dispute.py --task-id <id> --bundle-hash <hash>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id",     required=True)
    parser.add_argument("--bundle-hash", default="0x" + "0" * 64)
    args = parser.parse_args()

    from services.chain.settlement_adapter import OnChainSettlementAdapter
    adapter = OnChainSettlementAdapter()
    result  = adapter.open_dispute(args.task_id, args.bundle_hash)
    print(f"[ok] Dispute recorded (off-chain):")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("\n[note] Dispute resolution handled by the private runtime arbitration engine.")


if __name__ == "__main__":
    main()
