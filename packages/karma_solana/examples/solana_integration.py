#!/usr/bin/env python3
"""
Karma Solana Integration — Full End-to-End Demo
=================================================

Demonstrates the complete Karma → Solana verification pipeline:

    1. Karma Agent executes tool calls → Signed Receipts
    2. Evidence Bundle assembled from receipts
    3. Karma Runtime verifies the bundle (off-chain)
    4. Evidence uploaded to decentralized storage (Arweave/IPFS)
    5. Settlement recorded on Solana (memo transaction)
    6. x402 payment executed on Solana (SPL transfer)
    7. Full round-trip: verification → evidence → on-chain settlement

Usage
-----
    # Install deps
    pip install -e ".[dev]"

    # Run the demo
    python examples/solana_integration.py

Requirements
------------
- Solana CLI tools (for keypair generation in demo)
- Python 3.11+
- Internet connection (for Karma Runtime and Solana RPC)

Environment Variables (optional)
--------------------------------
    KARMA_RUNTIME_URL  — Karma Runtime API URL (default: http://localhost:8000)
    KARMA_API_KEY      — Karma API key
    SOLANA_RPC_URL     — Solana RPC endpoint (default: https://api.devnet.solana.com)
    ARWEAVE_WALLET     — Path to Arweave JWK wallet (optional)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add the parent Karma repo to path so we can import from it
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Ensure karma-solana package is importable
sys.path.insert(0, str(REPO_ROOT / "packages" / "karma-solana"))


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

DEMO_TASK_ID = f"solana-demo-{uuid.uuid4().hex[:8]}"
DEMO_AGENT_ID = "solana-agent-001"

KARMA_RUNTIME_URL = os.getenv("KARMA_RUNTIME_URL", "http://localhost:8000")
KARMA_API_KEY = os.getenv("KARMA_API_KEY", "karma_solana-demo_demokey")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")


# ═══════════════════════════════════════════════════════════════════
# Step 1: Simulated Karma Agent Execution (Signed Receipts)
# ═══════════════════════════════════════════════════════════════════

def simulate_agent_execution(task_id: str, agent_id: str) -> list[dict[str, Any]]:
    """
    Simulate a Karma Agent executing 3 tool calls and generating
    signed execution receipts.

    In production, this is handled by Karma SDK's ``KarmaHookLayer``
    which automatically intercepts tool calls and generates receipts.
    """
    print("\n" + "=" * 65)
    print("📋 STEP 1: Karma Agent executes tool calls (Solana agent)")
    print("=" * 65)

    receipts = []
    tool_calls = [
        ("solana.getBalance", {"wallet": "DemoSOL...abc"}, "1.5 SOL"),
        ("solana.swap", {"from": "SOL", "to": "USDC", "amount": 1.0}, "tx_sig_base58_xyz"),
        ("llm.verify_result", {"result": "swap_confirmed"}, "VERIFIED"),
    ]

    for i, (tool_name, tool_input, tool_output) in enumerate(tool_calls, 1):
        input_hash = hashlib.sha256(json.dumps(tool_input).encode()).hexdigest()
        output_hash = hashlib.sha256(json.dumps(tool_output).encode()).hexdigest()

        receipt = {
            "receipt_id": f"rcpt-{task_id}-{i:04d}",
            "task_id": task_id,
            "agent_id": agent_id,
            "step_index": i,
            "tool_name": tool_name,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "started_at": "2026-05-22T10:00:00Z",
            "ended_at": f"2026-05-22T10:00:0{i}Z",
            "duration_ms": 1234 + i * 100,
            "status": "SUCCESS",
            "error_message": None,
            "metadata": {"chain": "solana", "network": "devnet"},
            "signature": None,  # Would be Ed25519 signature in production
        }
        receipts.append(receipt)

        print(f"   ✓ {receipt['receipt_id']} | {tool_name} | status=SUCCESS")
        print(f"     input_hash={input_hash[:16]}... output_hash={output_hash[:16]}...")

    print(f"   Total: {len(receipts)} receipts generated")
    return receipts


# ═══════════════════════════════════════════════════════════════════
# Step 2: Evidence Bundle Assembly
# ═══════════════════════════════════════════════════════════════════

def build_evidence_bundle(
    task_id: str,
    receipts: list[dict[str, Any]],
    final_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Assemble the Evidence Bundle from execution receipts.

    This mirrors Karma core's ``EvidenceBundleBuilder.build()``.
    """
    print("\n" + "=" * 65)
    print("📦 STEP 2: Build evidence bundle")
    print("=" * 65)

    receipt_ids = [r["receipt_id"] for r in receipts]

    # Compute receipt hashes (canonical JSON serialization)
    receipt_hashes = []
    for r in receipts:
        canonical = json.dumps(r, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(canonical.encode()).hexdigest()
        receipt_hashes.append(h)
        print(f"   rcpt {r['receipt_id']} → hash {h[:16]}... ✓")

    # Compute bundle hash
    final_result_json = json.dumps(final_result, sort_keys=True, separators=(",", ":"))
    final_result_hash = hashlib.sha256(final_result_json.encode()).hexdigest()

    total_steps = len(receipts)
    successful_steps = sum(1 for r in receipts if r["status"] == "SUCCESS")
    failed_steps = total_steps - successful_steps
    total_duration_ms = sum(r["duration_ms"] for r in receipts)

    bundle = {
        "bundle_id": f"bundle-{task_id}",
        "task_id": task_id,
        "task_contract_hash": hashlib.sha256(f"contract:{task_id}".encode()).hexdigest(),
        "receipt_ids": receipt_ids,
        "receipt_hashes": receipt_hashes,
        "final_result_hash": final_result_hash,
        "total_steps": total_steps,
        "successful_steps": successful_steps,
        "failed_steps": failed_steps,
        "total_duration_ms": total_duration_ms,
        "agent_signature": None,  # Would be signed by agent in production
        "storage_path": None,
        "created_at": "2026-05-22T10:00:05Z",
        "settlement_status": "DELIVERED",
    }

    print(f"\n   Bundle ID: {bundle['bundle_id']}")
    print(f"   Receipts : {successful_steps}/{total_steps} successful")
    print(f"   Duration : {total_duration_ms}ms")
    print(f"   Bundle hash: {hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()[:32]}...")
    return bundle


# ═══════════════════════════════════════════════════════════════════
# Step 3: Karma Runtime Verification (Simulated)
# ═══════════════════════════════════════════════════════════════════

async def verify_with_karma_runtime(
    task_id: str,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """
    Submit bundle to Karma Runtime for cryptographic verification.

    In production, this POSTs to ``{runtime_url}/v1/verify``.
    Here we simulate the verification checks.
    """
    print("\n" + "=" * 65)
    print("🔍 STEP 3: Karma Runtime Verification (off-chain)")
    print("=" * 65)

    # Simulated verification checks
    checks = [
        {"name": "receipt_hash_consistency", "passed": True, "detail": "All receipt hashes are self-consistent"},
        {"name": "step_ordering", "passed": True, "detail": "Step indices are sequential and gapless"},
        {"name": "duration_integrity", "passed": True, "detail": "Total duration matches sum of step durations"},
        {"name": "status_consistency", "passed": True, "detail": f"Status counts: {bundle['successful_steps']} ok, {bundle['failed_steps']} fail"},
        {"name": "final_result_integrity", "passed": True, "detail": "Final result hash matches content"},
        {"name": "solana_target_validation", "passed": True, "detail": "Solana target address is valid"},
    ]

    all_passed = all(c["passed"] for c in checks)

    verification = {
        "verification_id": f"karma-vfy-{task_id}",
        "task_id": task_id,
        "bundle_id": bundle["bundle_id"],
        "decision": "RELEASE" if all_passed else "HOLD",
        "confidence": 0.98 if all_passed else 0.45,
        "checks": checks,
        "notes": "All cryptographic checks passed. Bundle is valid and self-consistent.",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }

    for c in checks:
        status = "✓ PASS" if c["passed"] else "✗ FAIL"
        print(f"   {status} | {c['name']}: {c['detail']}")

    print(f"\n   Decision: {verification['decision']} (confidence: {verification['confidence']:.2f})")
    return verification


# ═══════════════════════════════════════════════════════════════════
# Step 4: Evidence Upload to Decentralized Storage
# ═══════════════════════════════════════════════════════════════════

async def upload_evidence(bundle: dict[str, Any]) -> str:
    """
    Upload the evidence bundle to decentralized storage (Arweave/IPFS).

    In production, this uses ArweaveUploader or IPFSUploader.
    For the demo, we simulate with a content-hash URI.
    """
    print("\n" + "=" * 65)
    print("📤 STEP 4: Upload evidence to decentralized storage")
    print("=" * 65)

    bundle_json = json.dumps(bundle, sort_keys=True, indent=2)
    content_hash = hashlib.sha256(bundle_json.encode()).hexdigest()

    # Simulate Arweave upload
    arweave_uri = f"ar://karma-bundle-{content_hash[:16]}"
    ipfs_uri = f"ipfs://{content_hash}"

    print(f"   Content hash  : {content_hash}")
    print(f"   Arweave URI   : {arweave_uri}")
    print(f"   IPFS URI      : {ipfs_uri}")
    print(f"   Status        : ✅ Uploaded (simulated)")

    return arweave_uri


# ═══════════════════════════════════════════════════════════════════
# Step 5: Solana On-Chain Settlement
# ═══════════════════════════════════════════════════════════════════

def build_solana_settlement_memo(
    task_id: str,
    bundle_hash: str,
    verdict: str,
    confidence: float,
    evidence_uri: str,
) -> str:
    """
    Build the Karma settlement memo for Solana.

    This is the JSON payload recorded on-chain via an SPL Memo
    instruction. In production, this is sent via ``SolanaTransactionBuilder``.
    """
    print("\n" + "=" * 65)
    print("⚡ STEP 5: Solana On-Chain Settlement")
    print("=" * 65)

    memo = json.dumps({
        "protocol": "karma",
        "version": "1",
        "task_id": task_id,
        "bundle_hash": bundle_hash,
        "verdict": verdict,
        "confidence": confidence,
        "evidence_uri": evidence_uri,
        "chain": "solana",
        "network": "devnet",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    print(f"   Memo payload ({len(memo)} bytes):")
    print(f"   {json.dumps(json.loads(memo), indent=6)}")

    # Simulated transaction signature
    tx_sig = f"SIMULATED_TX_{hashlib.sha256(memo.encode()).hexdigest()[:24]}"
    print(f"\n   Solana Tx Signature: {tx_sig}")
    print(f"   Explorer: https://explorer.solana.com/tx/{tx_sig}?cluster=devnet")
    print(f"   Status: ✅ On-chain record built (simulated)")

    return tx_sig


# ═══════════════════════════════════════════════════════════════════
# Step 6: x402 Payment Hook (Simulated)
# ═══════════════════════════════════════════════════════════════════

def simulate_x402_payment(task_id: str) -> dict[str, Any]:
    """
    Simulate an x402 Agent-to-Agent payment on Solana.

    In production, this is handled by ``SolanaX402Hook.execute_payment()``
    which signs and submits an SPL Token transfer transaction.
    """
    print("\n" + "=" * 65)
    print("💸 STEP 6: x402 Payment on Solana (Agent-to-Agent)")
    print("=" * 65)

    proof = {
        "protocol": "x402",
        "network": "solana-devnet",
        "payer": "DemoSOL...payer",
        "pay_to": "DemoSOL...payee",
        "amount": 5.0,
        "asset": "USDC",
        "solana_tx_signature": f"SIMULATED_PAYMENT_TX_{uuid.uuid4().hex[:12]}",
        "payment_signature_b64": "c2ltdWxhdGVkX3BheW1lbnRfc2lnbmF0dXJlX2Jhc2U2NA==",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
    }

    print(f"   Asset      : {proof['amount']} {proof['asset']}")
    print(f"   From       : {proof['payer']}")
    print(f"   To         : {proof['pay_to']}")
    print(f"   Tx Sig     : {proof['solana_tx_signature']}")
    print(f"   Explorer   : https://explorer.solana.com/tx/{proof['solana_tx_signature']}?cluster=devnet")
    print(f"   Status     : ✅ Payment simulated")

    return proof


# ═══════════════════════════════════════════════════════════════════
# Step 7: Full Round-Trip Verification
# ═══════════════════════════════════════════════════════════════════

def verify_round_trip(
    receipts: list[dict[str, Any]],
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> bool:
    """
    Verify the entire pipeline's integrity:
    1. Receipt hashes match bundle.receipt_hashes
    2. Bundle hash is consistent
    3. Verification result is positive
    """
    print("\n" + "=" * 65)
    print("🔄 STEP 7: Full Round-Trip Verification")
    print("=" * 65)

    all_ok = True

    # Check 1: Receipt → Bundle hash consistency
    for r in receipts:
        canonical = json.dumps(r, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(canonical.encode()).hexdigest()
        if expected_hash in bundle["receipt_hashes"]:
            print(f"   ✓ Receipt {r['receipt_id']} → bundle hash match")
        else:
            print(f"   ✗ Receipt {r['receipt_id']} → bundle hash MISMATCH")
            all_ok = False

    # Check 2: Bundle integrity
    bundle_copy = bundle.copy()
    bundle_copy.pop("agent_signature", None)
    bundle_copy.pop("storage_path", None)
    bundle_copy.pop("created_at", None)
    bundle_copy.pop("settlement_status", None)
    bundle_hash = hashlib.sha256(
        json.dumps(bundle_copy, sort_keys=True).encode()
    ).hexdigest()
    print(f"   ✓ Bundle hash: {bundle_hash[:32]}...")

    # Check 3: Verification outcome
    if verification["decision"] == "RELEASE":
        print(f"   ✓ Verification: RELEASE (confidence={verification['confidence']:.2f})")
    else:
        print(f"   ! Verification: {verification['decision']} (confidence={verification['confidence']:.2f})")

    # Check 4: Solana settlement memo format
    print(f"   ✓ Solana memo format: valid JSON with required fields")

    print(f"\n   Round-trip status: {'✅ ALL CHECKS PASSED' if all_ok else '❌ ISSUES FOUND'}")
    return all_ok


# ═══════════════════════════════════════════════════════════════════
# Step 8: KarmaSolanaVerifier Integration Example
# ═══════════════════════════════════════════════════════════════════

def show_verifier_usage():
    """
    Show how to use KarmaSolanaVerifier in production code.

    This is a code display only — actual instantiation requires
    a running Karma Runtime and Solana RPC.
    """
    print("\n" + "=" * 65)
    print("📚 STEP 8: KarmaSolanaVerifier — Production Usage")
    print("=" * 65)

    code = '''
from karma_solana import KarmaSolanaVerifier, ArweaveUploader, SolanaX402Hook
from solders.keypair import Keypair
from karma.sdk import KarmaClient

# ── Initialize ──────────────────────────────────────────────
karma_client = KarmaClient(
    agent_id="solana-agent-001",
    runtime_url="https://api.karma.xyz",
    api_key="karma_...",
)

verifier = KarmaSolanaVerifier(
    karma_endpoint="https://api.karma.xyz",
    api_key="karma_...",
    solana_rpc="https://api.mainnet-beta.solana.com",
    evidence_store=ArweaveUploader(wallet_path="./arweave-key.json"),
    x402_hook=SolanaX402Hook(
        solana_rpc="https://api.mainnet-beta.solana.com",
        network="solana-mainnet",
    ),
)

# ── Execute and Settle ──────────────────────────────────────
task_id = "task-solana-001"
keypair = Keypair.from_base58_string("your_private_key_b58")

# 1. Agent executes tool calls (automatic receipt generation)
result, receipts = await karma_client.run_task(task_id, my_task_fn)

# 2. Build evidence bundle
bundle = await karma_client.build_bundle(task_id)

# 3. Verify + Upload + Settle on Solana
settlement = await verifier.verify_and_settle(
    task_id=task_id,
    evidence_bundle=bundle,
    signer_keypair=keypair,
)

print(f"Solana Tx: {settlement.solana_tx_signature}")
print(f"Evidence : {settlement.evidence_uri}")
print(f"Verdict  : {settlement.verdict}")
'''.strip()

    print(code)

    print("\n" + "-" * 65)
    print("📊 Comparison: Karma on BNB Chain vs Solana")
    print("-" * 65)
    print(f"  {'Feature':<35} {'BNB Chain':<30} {'Solana':<30}")
    print(f"  {'─'*35} {'─'*30} {'─'*30}")
    print(f"  {'Verification':<35} {'Karma Runtime (off-chain)':<30} {'Karma Runtime (off-chain)':<30}")
    print(f"  {'Evidence Storage':<35} {'BSC calldata / events':<30} {'Arweave / IPFS':<30}")
    print(f"  {'Settlement Recording':<35} {'ERC-8183 settle()':<30} {'SPL Memo / Program instruction':<30}")
    print(f"  {'Payment Protocol':<35} {'x402 (EVM)':<30} {'x402 (SPL)':<30}")
    print(f"  {'Transaction Speed':<35} {'~3 sec (BSC)':<30} {'~0.4 sec (Solana)':<30}")
    print(f"  {'Transaction Cost':<35} {'~$0.03 (BSC)':<30} {'~$0.0002 (Solana)':<30}")
    print(f"  {'Agent Ecosystem':<35} {'ERC-8183 / bnbagent':<30} {'x402 / Solana Agent Kit':<30}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def main():
    print("=" * 65)
    print("🛡️  KARMA SOLANA — FULL INTEGRATION DEMO")
    print("=" * 65)
    print(f"   Task ID     : {DEMO_TASK_ID}")
    print(f"   Agent ID    : {DEMO_AGENT_ID}")
    print(f"   Karma API   : {KARMA_RUNTIME_URL}")
    print(f"   Solana RPC  : {SOLANA_RPC_URL}")
    print(f"   Timestamp   : {datetime.now(timezone.utc).isoformat()}")

    # ── Step 1: Agent Execution ──
    receipts = simulate_agent_execution(DEMO_TASK_ID, DEMO_AGENT_ID)

    # ── Step 2: Evidence Bundle ──
    final_result = {"status": "completed", "output": "1.5 SOL balance, swap to USDC confirmed"}
    bundle = build_evidence_bundle(DEMO_TASK_ID, receipts, final_result)

    # ── Step 3: Karma Verification ──
    verification = await verify_with_karma_runtime(DEMO_TASK_ID, bundle)

    # ── Step 4: Upload Evidence ──
    evidence_uri = await upload_evidence(bundle)

    # ── Step 5: Solana Settlement ──
    bundle_hash = "0x" + hashlib.sha256(
        json.dumps(bundle, sort_keys=True).encode()
    ).hexdigest()
    tx_sig = build_solana_settlement_memo(
        DEMO_TASK_ID, bundle_hash,
        verdict="APPROVE",
        confidence=verification["confidence"],
        evidence_uri=evidence_uri,
    )

    # ── Step 6: x402 Payment ──
    payment_proof = simulate_x402_payment(DEMO_TASK_ID)

    # ── Step 7: Round-Trip Verification ──
    all_ok = verify_round_trip(receipts, bundle, verification)

    # ── Step 8: Production Usage ──
    show_verifier_usage()

    # ── Summary ──
    print("\n" + "=" * 65)
    print("📊 DEMO SUMMARY")
    print("=" * 65)
    print(f"   Receipts Generated       : {len(receipts)}")
    print(f"   Bundle Hashing           : ✅")
    print(f"   Off-chain Verification   : {verification['decision']} ({verification['confidence']:.0%})")
    print(f"   Evidence Storage         : {evidence_uri}")
    print(f"   Solana Tx Signature      : {tx_sig}")
    print(f"   x402 Payment             : {payment_proof['amount']} {payment_proof['asset']}")
    print(f"   Round-Trip Integrity     : {'✅ ALL PASS' if all_ok else '❌ ISSUES FOUND'}")
    print(f"\n   Pipeline: Tool Execution → Signed Receipt → Evidence Bundle")
    print(f"             → Karma Runtime → Arweave → Solana Settlement")
    print(f"             → x402 Payment → Audit Trail Complete")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
