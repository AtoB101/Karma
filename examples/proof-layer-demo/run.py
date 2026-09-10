#!/usr/bin/env python3
"""
Karma Proof Layer Demo — 30-second walkthrough.

Demonstrates the core proof primitives:
  1. Execution Receipt (signed record of one tool call)
  2. Evidence Bundle (portable audit package)
  3. Verification (structural checks)

Usage:
    python examples/proof-layer-demo/run.py
"""
import os
import sys
import json
import uuid
from datetime import datetime, timezone

# Add repo root to path so we can import from sdk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def banner(text):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def demo():
    task_id = f"demo_{uuid.uuid4().hex[:8]}"

    banner("Karma Proof Layer Demo")

    # ─── Step 1: Create Execution Receipt ─────────────────────────
    banner("Step 1: Execution Receipt")

    receipt = {
        "receipt_id": f"rcp_{uuid.uuid4().hex[:12]}",
        "task_id": task_id,
        "agent_id": "demo-agent-001",
        "step_index": 1,
        "tool_name": "mcp.search",
        "input_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        "output_hash": "f0e1d2c3b4a59687a6b5c4d3e2f101928374655647382910a0b1c2d3e4f50617",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 247,
        "status": "success",
        "payment_ref": {"type": "x402", "id": f"pay_{uuid.uuid4().hex[:8]}"},
        "metadata": {"template": "mcp", "mcp_server_id": "demo-server"},
    }

    print(f"  task_id:    {task_id}")
    print(f"  receipt_id: {receipt['receipt_id']}")
    print(f"  tool:       {receipt['tool_name']}")
    print(f"  status:     {receipt['status']}")
    print(f"  payment:    {receipt['payment_ref']['type']} / {receipt['payment_ref']['id']}")

    # ─── Step 2: Build Evidence Bundle ────────────────────────────
    banner("Step 2: Evidence Bundle")

    bundle = {
        "bundle_id": f"bun_{uuid.uuid4().hex[:12]}",
        "task_id": task_id,
        "receipts": [receipt],
        "payment_refs": [receipt["payment_ref"]],
        "delivery_metadata": {
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "recipient": receipt["agent_id"],
        },
        "verification_hints": {
            "expected_tool": "mcp.search",
            "expected_input_schema": "search_query_v1",
            "expected_output_schema": "search_result_v1",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"  bundle_id:    {bundle['bundle_id']}")
    print(f"  receipts:     {len(bundle['receipts'])}")
    print(f"  payment_refs: {len(bundle['payment_refs'])}")
    print(f"  hints:        {json.dumps(bundle['verification_hints'])}")

    # ─── Step 3: Verify ───────────────────────────────────────────
    banner("Step 3: Verification")

    checks = [
        {"name": "receipt.signature", "passed": True},
        {"name": "receipt.chain", "passed": True},
        {"name": "input_hash.match", "passed": True},
        {"name": "output_hash.match", "passed": True},
        {"name": "timestamp.order", "passed": True},
        {"name": "tool_name.match", "passed": True},
        {"name": "payment_ref.present", "passed": True},
        {"name": "bundle.completeness", "passed": True},
    ]

    all_passed = all(c["passed"] for c in checks)
    verification_result = {
        "verification_id": f"vrf_{uuid.uuid4().hex[:8]}",
        "task_id": task_id,
        "bundle_id": bundle["bundle_id"],
        "decision": "release" if all_passed else "hold",
        "confidence": 1.0 if all_passed else 0.0,
        "checks": checks,
    }

    print(f"  verification_id: {verification_result['verification_id']}")
    print(f"  decision:        {verification_result['decision']}")
    print(f"  confidence:      {verification_result['confidence']}")
    for c in checks:
        icon = "✅" if c["passed"] else "❌"
        print(f"    {icon} {c['name']}")

    # ─── Summary ──────────────────────────────────────────────────
    banner("Summary")
    print(f"  task_id:          {task_id}")
    print(f"  receipt_id:       {receipt['receipt_id']}")
    print(f"  bundle_id:        {bundle['bundle_id']}")
    print(f"  verification:     {verification_result['decision']}")
    print()
    print("  ✅ Proof layer demo complete!")
    print()
    print("  Next steps:")
    print("    - Run the API: uvicorn api.app:app --reload")
    print("    - Submit a real receipt: POST /v1/receipts")
    print("    - Try the MCP plugin: pip install -e ./packages/karma-openclaw")
    print("    - Read the docs: docs/PROOF_LAYER.md")
    print()


if __name__ == "__main__":
    demo()
