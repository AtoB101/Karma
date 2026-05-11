#!/usr/bin/env python3
"""
Full testnet flow end-to-end:

  1. Create task contract
  2. Lock pre-check (balance, allowance, nonce)
  3. Execute mock agent task (generates receipts)
  4. Build evidence bundle
  5. Run verification (MockVerificationEngine)
  6. Compute evidence bundle hash
  7. Submit on-chain release via KarmaSettlementEngine
  8. Store tx_hash
  9. Print final summary

Usage:
    python scripts/testnet/testnet_full_flow.py --amount <wei>

Requires .env with SETTLEMENT_MODE=testnet and all testnet vars set.
"""
import asyncio, sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def run_mock_task(contract, hooks):
    """Simulate agent executing a 3-step captioning task."""
    results = []
    for i in range(1, 4):
        async def tool(data, i=i):
            import asyncio
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
        print(f"  Step {i}: {receipt.tool_name} → {receipt.status} ({receipt.duration_ms}ms, receipt {receipt.receipt_id[:8]})")
    return {"results": results, "count": len(results)}


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--amount", type=int, default=100, help="Amount in token base units")
    args = parser.parse_args()

    from config.settings import settings
    print(f"\n{'='*60}")
    print(f"  KARMA TESTNET FULL FLOW")
    print(f"  Mode:     {settings.settlement_mode}")
    print(f"  Chain ID: {settings.testnet_chain_id}")
    print(f"  Engine:   {settings.karma_engine_address or '(not set)'}")
    print(f"  Token:    {settings.erc20_token_address or '(not set)'}")
    print(f"  Amount:   {args.amount} base units")
    print(f"{'='*60}\n")

    from core.schemas import TaskContract
    from core.hooks.hook_layer import InMemoryReceiptStore, KarmaHookLayer
    from core.evidence.bundle_builder import EvidenceBundleBuilder
    from core.verification.engine import MockVerificationEngine
    from services.chain.settlement_adapter import OnChainSettlementAdapter, settlement_router

    # 1. Task contract
    contract = TaskContract(
        task_id=f"testnet-task-{int(datetime.utcnow().timestamp())}",
        client_agent_id="testnet-client-001",
        worker_agent_id="testnet-worker-001",
        title="Testnet Caption Task (3 images)",
        description="Full testnet flow test",
        expected_output_schema={"type": "object"},
        expected_step_count=3,
        escrow_amount=float(args.amount),
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )
    print(f"[1] Task contract: {contract.task_id}")

    # 2. Lock pre-check
    print(f"[2] Lock pre-check...")
    if settlement_router.is_onchain():
        try:
            lock_result = settlement_router.lock_funds(contract)
            print(f"    ✓ balance={lock_result['balance']}, allowance={lock_result['allowance']}, nonce={lock_result['nonce']}")
        except Exception as e:
            print(f"    ✗ Lock check failed: {e}")
            sys.exit(1)
    else:
        print(f"    (skipped — mode={settings.settlement_mode})")

    # 3. Execute task
    print(f"[3] Agent executing task...")
    store   = InMemoryReceiptStore()
    hooks   = KarmaHookLayer(agent_id="testnet-worker-001", receipt_store=store)
    result  = await run_mock_task(contract, hooks)

    # 4. Build evidence bundle
    print(f"[4] Building evidence bundle...")
    builder = EvidenceBundleBuilder(receipt_store=store)
    bundle  = await builder.build(contract, result)
    print(f"    bundle_id={bundle.bundle_id[:16]}...")
    print(f"    total_steps={bundle.total_steps}, successful={bundle.successful_steps}")

    # 5. Verify
    print(f"[5] Running verification...")
    verifier     = MockVerificationEngine()
    verification = await verifier.verify(bundle, contract)
    print(f"    decision={verification.decision}, confidence={verification.confidence:.0%}")

    # 6. Evidence hash
    print(f"[6] Computing evidence bundle hash...")
    adapter     = OnChainSettlementAdapter()
    bundle_hash = adapter.submit_evidence_hash(contract.task_id, bundle)
    print(f"    bundle_hash={bundle_hash[:18]}...")

    # 7. On-chain release (or off-chain)
    print(f"[7] Settlement ({settings.settlement_mode})...")
    tx_hash      = None
    block_number = None
    onchain_status = "offchain"

    if settlement_router.should_submit_onchain(verification.decision):
        try:
            tx_result = adapter.release_payment(contract, verification, bundle, args.amount)
            tx_hash        = tx_result.tx_hash
            block_number   = tx_result.block_number
            onchain_status = tx_result.status
            print(f"    ✓ On-chain release!")
            print(f"    tx_hash={tx_hash}")
            print(f"    block_number={block_number}")
        except Exception as e:
            print(f"    ✗ On-chain release failed: {e}")
            onchain_status = "failed"
    else:
        if verification.decision.value == "release":
            print(f"    (off-chain release — mode={settings.settlement_mode})")
        else:
            print(f"    Decision: {verification.decision} — no on-chain action")

    # 8. Summary
    print(f"\n{'='*60}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  task_id:         {contract.task_id}")
    print(f"  bundle_id:       {bundle.bundle_id}")
    print(f"  decision:        {verification.decision}")
    print(f"  confidence:      {verification.confidence:.0%}")
    print(f"  evidence_hash:   {bundle_hash[:20]}...")
    print(f"  settlement_mode: {settings.settlement_mode}")
    print(f"  onchain_status:  {onchain_status}")
    print(f"  tx_hash:         {tx_hash or '(none)'}")
    print(f"  block_number:    {block_number or '(none)'}")
    print(f"  chain_id:        {settings.testnet_chain_id}")
    print(f"  contract:        {settings.karma_engine_address or '(not set)'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
