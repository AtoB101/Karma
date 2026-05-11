#!/usr/bin/env python3
"""
Verify on-chain pre-conditions for a task (balance, allowance, nonce, engine state).
This is the "lock" check — for the KarmaSettlementEngine, funds are not locked
until submitSettlement() is called, so this is a pre-flight validation.

Usage:
    python scripts/testnet/testnet_lock.py --task-id <id> --amount <wei>
"""
import argparse, asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--amount",  type=int, required=True, help="Amount in token base units (wei)")
    args = parser.parse_args()

    from config.settings import settings
    if settings.settlement_mode == "offchain":
        print("[warn] SETTLEMENT_MODE=offchain — set to testnet or hybrid to use chain")

    from datetime import datetime, timedelta
    from core.schemas import TaskContract
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    contract = TaskContract(
        task_id=args.task_id,
        client_agent_id="testnet-client",
        title="Testnet lock check",
        description="Pre-flight check",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=float(args.amount),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )

    adapter = OnChainSettlementAdapter()
    result  = adapter.lock_funds(contract)
    print("[ok] Lock pre-checks passed:")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
