#!/usr/bin/env python3
"""
Full testnet flow (KarmaBilateral):

  1. Create task contract
  2. Lock pre-check (optional --do-lock)
  3. Execute mock agent task (receipts)
  4. Build evidence bundle + verify
  5. If --buyer-bill-id + --agent-bill-id: bind → settle
  6. If --finalize and binding set: finalizeSettle (only after dispute window)

Usage:
    python scripts/testnet/testnet_full_flow.py --amount 100
    python scripts/testnet/testnet_full_flow.py --amount 100 \\
      --buyer-bill-id 1 --agent-bill-id 2 --finalize

Requires SETTLEMENT_MODE=testnet|hybrid and KARMA_BILATERAL_ADDRESS + RPC keys.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def run_mock_task(contract, hooks):
    results = []
    for i in range(1, 4):
        async def tool(data, i=i):
            await asyncio.sleep(0.05 + i * 0.03)
            return {"caption": f"Caption {i} for {data.get('url')}", "confidence": 0.95}

        result, receipt = await hooks.run_tool(
            task_id=contract.task_id,
            tool_name="caption.generate",
            tool_fn=tool,
            input_data={"url": f"https://cdn.example.com/{i:04d}.jpg"},
            metadata={"step": i},
        )
        results.append(result)
        print(
            f"  Step {i}: {receipt.tool_name} → {receipt.status} "
            f"({receipt.duration_ms}ms, receipt {receipt.receipt_id[:8]})"
        )
    return {"results": results, "count": len(results)}


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="KarmaBilateral testnet full flow")
    parser.add_argument("--amount", type=int, default=100, help="Amount in token base units")
    parser.add_argument("--do-lock", action="store_true", help="Broadcast lock() in pre-check")
    parser.add_argument("--buyer-bill-id", type=int, default=None)
    parser.add_argument("--agent-bill-id", type=int, default=None)
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Call finalizeSettle after settle (requires dispute window elapsed)",
    )
    args = parser.parse_args()

    from config.settings import settings
    from core.evidence.bundle_builder import EvidenceBundleBuilder
    from core.hooks.hook_layer import InMemoryReceiptStore, KarmaHookLayer
    from core.schemas import TaskContract
    from core.verification.engine import MockVerificationEngine
    from services.chain.settlement_adapter import OnChainSettlementAdapter, settlement_router

    print(f"\n{'='*60}")
    print("  KARMA TESTNET FULL FLOW (KarmaBilateral)")
    print(f"  Mode:      {settings.settlement_mode}")
    print(f"  Chain ID:  {settings.testnet_chain_id}")
    print(f"  Bilateral: {settings.karma_bilateral_address or '(not set)'}")
    print(f"  Token:     {settings.erc20_token_address or '(not set)'}")
    print(f"  Amount:    {args.amount} base units")
    print(f"{'='*60}\n")

    contract = TaskContract(
        task_id=f"testnet-task-{int(datetime.utcnow().timestamp())}",
        client_agent_id="testnet-client-001",
        worker_agent_id="testnet-worker-001",
        title="Testnet Caption Task (3 images)",
        description="Full testnet flow test (KarmaBilateral)",
        expected_output_schema={"type": "object"},
        expected_step_count=3,
        escrow_amount=float(args.amount),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
        onchain_do_lock=bool(args.do_lock),
        onchain_buyer_bill_id=args.buyer_bill_id,
        onchain_agent_bill_id=args.agent_bill_id,
    )
    print(f"[1] Task contract: {contract.task_id}")

    print("[2] Lock pre-check...")
    if settlement_router.is_onchain():
        try:
            lock_result = settlement_router.lock_funds(contract)
            print(
                f"    ✓ status={lock_result.get('status')} "
                f"balance={lock_result.get('balance')} "
                f"allowance={lock_result.get('allowance')}"
            )
            if lock_result.get("bill_id") is not None:
                print(f"    bill_id={lock_result['bill_id']}")
        except Exception as e:
            print(f"    ✗ Lock check failed: {e}")
            sys.exit(1)
    else:
        print(f"    (skipped — mode={settings.settlement_mode})")

    print("[3] Agent executing task...")
    store = InMemoryReceiptStore()
    hooks = KarmaHookLayer(agent_id="testnet-worker-001", receipt_store=store)
    result = await run_mock_task(contract, hooks)

    print("[4] Building evidence bundle...")
    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle = await builder.build(contract, result)
    print(f"    bundle_id={bundle.bundle_id[:16]}...")
    print(f"    total_steps={bundle.total_steps}, successful={bundle.successful_steps}")

    print("[5] Running verification...")
    verifier = MockVerificationEngine()
    verification = await verifier.verify(bundle, contract)
    print(f"    decision={verification.decision}, confidence={verification.confidence:.0%}")

    adapter = OnChainSettlementAdapter()
    bundle_hash = adapter.submit_evidence_hash(contract.task_id, bundle)
    print(f"[6] evidence_hash={bundle_hash[:18]}...")

    tx_hash = None
    block_number = None
    onchain_status = "offchain"
    binding_id = contract.onchain_binding_id

    print(f"[7] Settlement ({settings.settlement_mode})...")
    if (
        settlement_router.is_onchain()
        and contract.onchain_buyer_bill_id is not None
        and contract.onchain_agent_bill_id is not None
        and contract.onchain_binding_id is None
    ):
        try:
            bind_tx = adapter.bind_bills(contract)
            binding_id = bind_tx.binding_id
            print(f"    ✓ bind binding_id={binding_id} tx={bind_tx.tx_hash}")
        except Exception as e:
            print(f"    ✗ bind failed: {e}")
            sys.exit(1)

    if settlement_router.should_submit_onchain(verification.decision):
        if contract.onchain_binding_id is None:
            print("    ✗ settle skipped — set --buyer-bill-id/--agent-bill-id or onchain_binding_id")
            onchain_status = "missing_binding"
        else:
            try:
                tx_result = adapter.release_payment(contract, verification, bundle, args.amount)
                tx_hash = tx_result.tx_hash
                block_number = tx_result.block_number
                onchain_status = "finalizing"
                binding_id = tx_result.binding_id
                print(f"    ✓ settle → FINALIZING tx={tx_hash}")
            except Exception as e:
                print(f"    ✗ settle failed: {e}")
                onchain_status = "failed"
    else:
        print(f"    (no on-chain settle — mode={settings.settlement_mode})")

    if args.finalize and settlement_router.is_onchain() and contract.onchain_binding_id is not None:
        print("[8] finalizeSettle...")
        try:
            fin = adapter.finalize_settle(contract)
            tx_hash = fin.tx_hash
            block_number = fin.block_number
            onchain_status = "settled"
            print(f"    ✓ finalized tx={fin.tx_hash}")
        except Exception as e:
            print(f"    ✗ finalize failed (dispute window open?): {e}")
            if onchain_status == "finalizing":
                print("    hint: wait disputeWindowSeconds then re-run testnet_finalize.py")

    print(f"\n{'='*60}")
    print("  FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  task_id:         {contract.task_id}")
    print(f"  bundle_id:       {bundle.bundle_id}")
    print(f"  decision:        {verification.decision}")
    print(f"  evidence_hash:   {bundle_hash[:20]}...")
    print(f"  binding_id:      {binding_id}")
    print(f"  settlement_mode: {settings.settlement_mode}")
    print(f"  onchain_status:  {onchain_status}")
    print(f"  tx_hash:         {tx_hash or '(none)'}")
    print(f"  block_number:    {block_number or '(none)'}")
    print(f"  chain_id:        {settings.testnet_chain_id}")
    print(f"  contract:        {settings.karma_bilateral_address or '(not set)'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
