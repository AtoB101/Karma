#!/usr/bin/env python3
"""
Call KarmaBilateral.finalizeSettle(bindingId) after the dispute window.

Usage:
    python scripts/testnet/testnet_finalize.py --task-id <id> --binding-id <n>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="KarmaBilateral finalizeSettle")
    parser.add_argument("--task-id", default="testnet-finalize")
    parser.add_argument("--binding-id", type=int, required=True)
    args = parser.parse_args()

    from core.schemas import TaskContract
    from services.chain.settlement_adapter import OnChainSettlementAdapter

    contract = TaskContract(
        task_id=args.task_id,
        client_agent_id="testnet-client",
        title="Testnet finalize",
        description="KarmaBilateral finalizeSettle",
        expected_output_schema={},
        expected_step_count=1,
        escrow_amount=0.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
        onchain_binding_id=args.binding_id,
    )

    adapter = OnChainSettlementAdapter()
    tx = adapter.finalize_settle(contract)
    print("[ok] finalizeSettle:")
    print(f"  tx_hash: {tx.tx_hash}")
    print(f"  binding_id: {tx.binding_id}")
    print(f"  status: {tx.status}")


if __name__ == "__main__":
    main()
