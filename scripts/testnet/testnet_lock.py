#!/usr/bin/env python3
"""
KarmaBilateral lock pre-check (and optional broadcast).

Validates token allowlist / balance / allowance against KarmaBilateral.
With --do-lock, broadcasts lock() and prints bill_id.

Usage:
    python scripts/testnet/testnet_lock.py --task-id <id> --amount <base-units>
    python scripts/testnet/testnet_lock.py --task-id <id> --amount <base-units> --do-lock
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="KarmaBilateral lock pre-check / lock")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--amount", type=int, required=True, help="Amount in token base units")
    parser.add_argument(
        "--do-lock",
        action="store_true",
        help="Broadcast lock() (requires TESTNET_PRIVATE_KEY + allowance)",
    )
    args = parser.parse_args()

    from config.settings import settings
    from core.schemas import TaskContract
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    if settings.settlement_mode == "offchain":
        print("[warn] SETTLEMENT_MODE=offchain — set to testnet or hybrid to use chain")

    print(f"Bilateral: {settings.karma_bilateral_address or '(not set)'}")
    print(f"Token:     {settings.erc20_token_address or '(not set)'}")

    contract = TaskContract(
        task_id=args.task_id,
        client_agent_id="testnet-client",
        title="Testnet lock check",
        description="KarmaBilateral lock pre-flight",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=float(args.amount),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
        onchain_do_lock=bool(args.do_lock),
    )

    adapter = OnChainSettlementAdapter()
    result = adapter.lock_funds(contract)
    print("[ok] Lock result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    if contract.onchain_buyer_bill_id is not None:
        print(f"  onchain_buyer_bill_id: {contract.onchain_buyer_bill_id}")


if __name__ == "__main__":
    main()
