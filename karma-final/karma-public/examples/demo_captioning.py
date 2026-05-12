"""
Karma Trust Protocol — Demo: Image Captioning Task
===================================================
End-to-end example of the Karma runtime using mock data.
Demonstrates the full flow:

    Contract → Escrow Lock → Tool Execution (with hooks)
    → Evidence Bundle → Verification → Settlement

Run
---
    python examples/demo_captioning.py
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta

from core.schemas import AgentRole, TaskContract
from core.hooks.hook_layer import KarmaHookLayer, InMemoryReceiptStore
from core.evidence.bundle_builder import EvidenceBundleBuilder
from core.verification.engine import MockVerificationEngine
from core.settlement.engine import InMemorySettlementStore
from agents.runtime.adapter import KarmaRuntimeAgent


# ---------------------------------------------------------------------------
# Mock tools
# ---------------------------------------------------------------------------

async def mock_caption_tool(input_data: dict) -> dict:
    """Simulate captioning an image. Returns a generated caption."""
    await asyncio.sleep(random.uniform(0.05, 0.2))   # simulate network latency
    image_url = input_data.get("image_url", "unknown")
    return {
        "image_url": image_url,
        "caption": f"A detailed scene captured at {image_url.split('/')[-1]}",
        "confidence": round(random.uniform(0.82, 0.99), 3),
    }


async def mock_quality_check_tool(input_data: dict) -> dict:
    """Simulate a quality check on a generated caption."""
    await asyncio.sleep(random.uniform(0.01, 0.05))
    return {
        "passed": True,
        "score": round(random.uniform(0.8, 1.0), 3),
    }


# ---------------------------------------------------------------------------
# Task runner (called by LangGraph run_agent node)
# ---------------------------------------------------------------------------

async def caption_task_runner(contract: TaskContract, agent: KarmaRuntimeAgent) -> dict:
    """
    Process N images: generate caption + quality check for each.
    Returns aggregated results.
    """
    image_urls = [
        f"https://cdn.example.com/images/{i:04d}.jpg"
        for i in range(1, 6)   # 5 images for demo
    ]
    results = []

    for url in image_urls:
        # Step 1: Generate caption
        caption_result, _ = await agent.run_tool(
            task_id=contract.task_id,
            tool_name="caption.generate",
            tool_fn=mock_caption_tool,
            input_data={"image_url": url},
            metadata={"image_index": image_urls.index(url)},
        )

        # Step 2: Quality check
        qc_result, _ = await agent.run_tool(
            task_id=contract.task_id,
            tool_name="caption.quality_check",
            tool_fn=mock_quality_check_tool,
            input_data={"caption": caption_result["caption"]},
        )

        results.append({
            "image_url": url,
            "caption": caption_result["caption"],
            "confidence": caption_result["confidence"],
            "quality_passed": qc_result["passed"],
        })

    return {
        "task_id": contract.task_id,
        "total_images": len(results),
        "successful_captions": sum(1 for r in results if r["quality_passed"]),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

async def run_demo() -> None:
    print("\n" + "=" * 60)
    print("  KARMA TRUSTED AGENT RUNTIME — Demo")
    print("  Scenario: Image Captioning Task (5 images)")
    print("=" * 60 + "\n")

    # --- Setup ---
    receipt_store = InMemoryReceiptStore()
    hooks         = KarmaHookLayer(agent_id="worker-demo-001", receipt_store=receipt_store)
    agent         = KarmaRuntimeAgent(agent_id="worker-demo-001", hook_layer=hooks)
    builder       = EvidenceBundleBuilder(receipt_store=receipt_store)
    verifier      = MockVerificationEngine()

    # --- Contract ---
    contract = TaskContract(
        client_agent_id="client-demo-001",
        worker_agent_id="worker-demo-001",
        title="Caption 5 Product Images",
        description="Generate accurate English captions for each image URL provided.",
        expected_output_schema={
            "type": "object",
            "properties": {
                "results": {"type": "array"},
            },
        },
        expected_step_count=10,   # 5 images × 2 steps each
        escrow_amount=25.00,
        currency="USD",
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )
    print(f"📄 Task Contract created: {contract.task_id}")
    print(f"   Escrow: ${contract.escrow_amount} {contract.currency}")
    print(f"   Expected steps: {contract.expected_step_count}\n")

    # --- Execute ---
    print("🤖 Agent executing task...\n")
    final_result = await caption_task_runner(contract, agent)

    receipts = await receipt_store.list_by_task(contract.task_id)
    print(f"✅ Execution complete — {len(receipts)} receipts generated")
    for r in receipts:
        print(f"   Step {r.step_index:02d} | {r.tool_name:<30} | {r.status:<8} | {r.duration_ms}ms")

    # --- Bundle ---
    print(f"\n📦 Building evidence bundle...")
    bundle = await builder.build(contract, final_result)
    print(f"   Bundle ID:       {bundle.bundle_id}")
    print(f"   Total steps:     {bundle.total_steps}")
    print(f"   Successful:      {bundle.successful_steps}")
    print(f"   Total duration:  {bundle.total_duration_ms}ms")

    # --- Verify ---
    print(f"\n🔍 Submitting to Verification Engine...")
    result = await verifier.verify(bundle, contract)
    print(f"   Decision:   {result.decision.upper()}")
    print(f"   Confidence: {result.confidence:.0%}")
    passed  = sum(1 for c in result.checks if c.passed)
    print(f"   Checks:     {passed}/{len(result.checks)} passed")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"  RESULT: {result.decision.upper()}")
    print(f"  Task:   {contract.task_id}")
    print(f"  Images: {final_result['successful_captions']}/{final_result['total_images']} captioned")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(run_demo())
