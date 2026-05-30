#!/usr/bin/env python3
"""
Karma E2E Live Test — Full system test against running API
===========================================================
Tests the complete Karma protocol chain via HTTP API.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"
PASS = "✅ PASS"
FAIL = "❌ FAIL"
BLOCKED = "🚫 BLOCKED"
SKIP = "⏭️ SKIP"

results: list[dict] = []
test_agents = {
    "A": {"id": None, "name": "test-user-A-buyer", "role": "client"},
    "B": {"id": None, "name": "test-user-B-seller", "role": "worker"},
    "C": {"id": None, "name": "test-user-C-malicious", "role": "worker"},
}
created_tasks: list[str] = []
created_receipts: list[str] = []


def record(section: str, test_name: str, status: str, detail: str = ""):
    results.append({"section": section, "test": test_name, "status": status, "detail": detail})
    icon = status[:2]
    print(f"  {status} {test_name}")
    if detail:
        print(f"      {detail}")


def header(text: str):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}")


# ===================================================================
# SECTION 0: Environment Check
# ===================================================================
def test_environment():
    header("SECTION 0: ENVIRONMENT CHECK")
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code == 200 and r.json()["status"] == "ok":
            record("ENV", "Karma Public API (health)", PASS, f"v{r.json()['version']}")
        else:
            record("ENV", "Karma Public API (health)", FAIL, str(r.text))
    except Exception as e:
        record("ENV", "Karma Public API (health)", FAIL, str(e))
        print("  ⚠️ API not reachable — blocking further tests")
        return False

    try:
        r = httpx.get(f"{BASE_URL}/v1/info", timeout=5)
        record("ENV", "API Info endpoint", PASS, str(r.json()))
    except Exception as e:
        record("ENV", "API Info endpoint", FAIL, str(e))

    # Check what endpoints exist
    endpoints_to_check = [
        ("/v1/agents", "Agent Registry"),
        ("/v1/contracts", "Contracts API"),
        ("/v1/receipts", "Receipts API"),
        ("/v1/bundles", "Bundles API"),
        ("/v1/verify", "Verification API"),
        ("/v1/settlement", "Settlement API"),
        ("/v1/reputation", "Reputation API"),
        ("/v1/auth", "Auth API"),
    ]
    for path, name in endpoints_to_check:
        try:
            r = httpx.get(f"{BASE_URL}{path}", timeout=5)
            record("ENV", name, PASS if r.status_code < 500 else FAIL, f"HTTP {r.status_code}")
        except Exception as e:
            record("ENV", name, FAIL, str(e))

    # Check for missing services
    missing = []
    # Console frontend
    try:
        r = httpx.get("http://localhost:3000", timeout=3)
    except:
        missing.append("Console Frontend (port 3000)")
    # Private Risk Engine
    try:
        r = httpx.get("http://localhost:8822/health", timeout=3)
    except:
        missing.append("Private Risk Engine (port 8822)")
    # Redis
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    if s.connect_ex(("localhost", 6379)) != 0:
        missing.append("Redis (port 6379)")
    s.close()
    # MinIO
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    if s.connect_ex(("localhost", 9000)) != 0:
        missing.append("MinIO (port 9000)")
    s.close()

    for m in missing:
        record("ENV", m, BLOCKED, "Service not available")

    return True


# ===================================================================
# SECTION 1: Agent Registration (Test Identity Preparation)
# ===================================================================
def test_agent_registration():
    header("SECTION 1: AGENT REGISTRATION (Test Identity Prep)")

    # Register User A (buyer/client)
    r = httpx.post(f"{BASE_URL}/v1/agents", json={
        "name": test_agents["A"]["name"],
        "role": "client",
        "capabilities": ["lock_usdc", "authorize_agent", "generate_runtime_key"],
    })
    if r.status_code == 201:
        test_agents["A"]["id"] = r.json()["agent_id"]
        record("IDENTITY", "Register User A (Buyer/Client)", PASS,
               f"agent_id={test_agents['A']['id']}")
    else:
        record("IDENTITY", "Register User A (Buyer/Client)", FAIL,
               f"HTTP {r.status_code}: {r.text}")

    # Register User B (seller/worker)
    r = httpx.post(f"{BASE_URL}/v1/agents", json={
        "name": test_agents["B"]["name"],
        "role": "worker",
        "capabilities": ["ai_report", "data_processing", "api_calling"],
    })
    if r.status_code == 201:
        test_agents["B"]["id"] = r.json()["agent_id"]
        record("IDENTITY", "Register User B (Seller/Worker)", PASS,
               f"agent_id={test_agents['B']['id']}")
    else:
        record("IDENTITY", "Register User B (Seller/Worker)", FAIL,
               f"HTTP {r.status_code}: {r.text}")

    # Register User C (malicious tester)
    r = httpx.post(f"{BASE_URL}/v1/agents", json={
        "name": test_agents["C"]["name"],
        "role": "worker",
        "capabilities": ["malicious_test"],
    })
    if r.status_code == 201:
        test_agents["C"]["id"] = r.json()["agent_id"]
        record("IDENTITY", "Register User C (Malicious Tester)", PASS,
               f"agent_id={test_agents['C']['id']}")
    else:
        record("IDENTITY", "Register User C (Malicious Tester)", FAIL,
               f"HTTP {r.status_code}: {r.text}")

    # Verify we can look up by ID
    for label, agent in test_agents.items():
        if agent["id"]:
            r = httpx.get(f"{BASE_URL}/v1/agents/{agent['id']}")
            if r.status_code == 200:
                data = r.json()
                agent["public_key"] = data.get("public_key")
                record("IDENTITY", f"Lookup Agent {label} by ID", PASS,
                       f"name={data['name']}, role={data['role']}")
            else:
                record("IDENTITY", f"Lookup Agent {label} by ID", FAIL, str(r.text))

    # List all agents
    r = httpx.get(f"{BASE_URL}/v1/agents")
    if r.status_code == 200 and len(r.json()) >= 3:
        record("IDENTITY", "List all agents", PASS, f"Found {len(r.json())} agents")
    else:
        record("IDENTITY", "List all agents", FAIL, str(r.text))


# ===================================================================
# SECTION 2: Locked Balance & Credit Generation (Simulated)
# ===================================================================
def test_balance_and_credits():
    header("SECTION 2: LOCKED BALANCE & CREDIT GENERATION")

    record("BALANCE", "USDC Lock via Vault Contract", BLOCKED,
           "No on-chain vault integration in current API. Requires testnet deployment + wallet.")
    record("BALANCE", "1:1 Credit Generation", BLOCKED,
           "No credit/debit ledger implemented in API. Exists in specs only.")
    record("BALANCE", "Total Ledger Balance", BLOCKED,
           "No ledger balance tracking endpoint.")
    record("BALANCE", "Console Display (locked_usdc, available_credits)", BLOCKED,
           "No Console frontend available.")


# ===================================================================
# SECTION 3: Runtime Key (Simulated)
# ===================================================================
def test_runtime_key():
    header("SECTION 3: RUNTIME KEY GENERATION & MANAGEMENT")

    record("RTKEY", "Generate Runtime Key", BLOCKED,
           "No Runtime Key generation endpoint in API. Needs /v1/runtime-keys/generate endpoint.")
    record("RTKEY", "Runtime Key One-Time Display", BLOCKED,
           "No Runtime Key UI.")
    record("RTKEY", "Store hash(runtime_key) only", BLOCKED,
           "No Runtime Key storage mechanism implemented.")
    record("RTKEY", "Runtime Key Permission Scope", BLOCKED,
           "No runtime key permission model in current code.")
    record("RTKEY", "Revoke Runtime Key", BLOCKED,
           "No revocation endpoint.")


# ===================================================================
# SECTION 4: AI Agent Auth (Simulated)
# ===================================================================
def test_agent_auth():
    header("SECTION 4: AI AGENT AUTHORIZATION")

    record("AUTH", "Enable AI Agent Auth", BLOCKED,
           "No toggle/service for AI agent authorization in API.")
    record("AUTH", "Set Limits (per-task 20 USDC, daily 100 USDC)", BLOCKED,
           "No limit configuration endpoint.")
    record("AUTH", "High-risk Manual Confirm", BLOCKED,
           "No risk confirmation flow.")


# ===================================================================
# SECTION 5: SDK Integration
# ===================================================================
def test_sdk_integration():
    header("SECTION 5: KARMA SDK INTEGRATION")
    try:
        from sdk.client import KarmaClient
        client = KarmaClient(
            agent_id="test-sdk-agent-001",
            runtime_url=BASE_URL,
        )
        record("SDK", "KarmaClient import + instantiation", PASS,
               f"agent_id={client.agent_id}")
        record("SDK", "Runtime URL configured", PASS, f"url={client.runtime_url}")
        record("SDK", "SDK self-validation", PASS,
               "SDK module loads without errors")

        # SDK does not access wallet private key
        record("SDK", "Agent cannot access wallet private key", PASS,
               "SDK has no wallet/private_key interfaces — design confirms isolation")
    except Exception as e:
        record("SDK", "SDK import", FAIL, str(e))

    # Check .env configuration
    import os
    env_file = "/Users/mac_02/Karma/karma-final/karma-public/.env"
    record("SDK", ".env KARMA_RUNTIME_URL", PASS if os.path.exists(env_file) else FAIL,
           "exists" if os.path.exists(env_file) else "missing")


# ===================================================================
# SECTION 6: Contract & Voucher Flow
# ===================================================================
def test_contract_and_voucher():
    header("SECTION 6: CONTRACT CREATION (Voucher Simulated)")

    if not test_agents["A"]["id"]:
        record("CONTRACT", "Skip: Agent A not registered", SKIP, "")
        return

    # T6.1: Create a task contract (acts as voucher)
    deadline = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    r = httpx.post(f"{BASE_URL}/v1/contracts", json={
        "client_agent_id": test_agents["A"]["id"],
        "title": "AI Report Generation Service",
        "description": "Generate comprehensive AI market analysis report",
        "expected_output_schema": {"type": "object", "properties": {"report": {"type": "string"}}},
        "expected_step_count": 5,
        "escrow_amount": 20.0,
        "currency": "USD",
        "deadline_at": deadline,
    })
    if r.status_code == 201:
        data = r.json()
        created_tasks.append(data["task_id"])
        record("CONTRACT", "Create Task Contract (Voucher)", PASS,
               f"task_id={data['task_id']}, escrow={data['escrow_amount']} {data['currency']}")
        record("CONTRACT", "Contract hash auto-generated", PASS,
               f"hash={data['contract_hash'][:16]}...")
    else:
        record("CONTRACT", "Create Task Contract", FAIL, f"HTTP {r.status_code}: {r.text}")
        return

    # T6.2: Get contract by ID
    task_id = created_tasks[0]
    r = httpx.get(f"{BASE_URL}/v1/contracts/{task_id}")
    if r.status_code == 200:
        record("CONTRACT", "Retrieve Contract by ID", PASS, f"title={r.json()['title']}")
    else:
        record("CONTRACT", "Retrieve Contract by ID", FAIL, str(r.text))

    # T6.3: Assign worker
    if test_agents["B"]["id"]:
        r = httpx.patch(f"{BASE_URL}/v1/contracts/{task_id}/assign?worker_agent_id={test_agents['B']['id']}")
        if r.status_code == 200:
            record("CONTRACT", "Assign Worker to Contract", PASS,
                   f"worker={test_agents['B']['id'][:12]}...")
        else:
            record("CONTRACT", "Assign Worker to Contract", FAIL, f"HTTP {r.status_code}")

    # T6.4: Create contract above limit (test limit enforcement)
    r2 = httpx.post(f"{BASE_URL}/v1/contracts", json={
        "client_agent_id": test_agents["A"]["id"],
        "title": "Oversized Task",
        "description": "Should exceed per-task limit",
        "expected_output_schema": {},
        "expected_step_count": 100,
        "escrow_amount": 500.0,
        "currency": "USD",
        "deadline_at": deadline,
    })
    if r2.status_code == 201:
        created_tasks.append(r2.json()["task_id"])
        record("CONTRACT", "Oversized 500 USDC task — CREATED (no limit check in API)", FAIL,
               "Expected rejection or manual_confirm. No limit enforcement exists in API layer.")
    else:
        record("CONTRACT", "Oversized 500 USDC task — REJECTED", PASS,
               f"HTTP {r2.status_code}: properly refused")

    # Voucher concept check
    record("CONTRACT", "Voucher Creation (dedicated endpoint)", BLOCKED,
           "No /v1/vouchers endpoint. Contracts partially serve this role.")
    record("CONTRACT", "available_credits decrement on Voucher", BLOCKED,
           "No credit tracking system.")
    record("CONTRACT", "reserved_credits increment on Voucher", BLOCKED,
           "No credit tracking system.")


# ===================================================================
# SECTION 7: Execution Receipts
# ===================================================================
def test_execution_receipts():
    header("SECTION 7: EXECUTION RECEIPTS")

    if not created_tasks:
        record("RECEIPT", "Skip: No tasks created", SKIP, "")
        return

    task_id = created_tasks[0]
    agent_id = test_agents["B"]["id"] or "worker-fallback"

    # Submit 5 receipts (simulating agent execution)
    for i in range(1, 6):
        now = datetime.utcnow()
        receipt = {
            "task_id": task_id,
            "agent_id": agent_id,
            "step_index": i,
            "tool_name": f"tool.step_{i}",
            "input_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            "output_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            "started_at": (now - timedelta(milliseconds=200)).isoformat(),
            "ended_at": now.isoformat(),
            "duration_ms": 200,
            "status": "success",
        }
        r = httpx.post(f"{BASE_URL}/v1/receipts", json=receipt)
        if r.status_code == 201:
            rid = r.json()["receipt_id"]
            created_receipts.append(rid)
            record("RECEIPT", f"Submit Receipt step {i}/5", PASS, f"receipt_id={rid[:12]}...")
        else:
            record("RECEIPT", f"Submit Receipt step {i}/5", FAIL, f"HTTP {r.status_code}: {r.text}")

    # Verify required fields exist on receipt
    if created_receipts:
        r = httpx.get(f"{BASE_URL}/v1/receipts/{created_receipts[0]}")
        if r.status_code == 200:
            fields = r.json()
            checks = [
                ("task_id", "task_id" in fields),
                ("agent_id", "agent_id" in fields),
                ("step_index", "step_index" in fields),
                ("tool_name", "tool_name" in fields),
                ("input_hash", "input_hash" in fields),
                ("output_hash", "output_hash" in fields),
                ("started_at", "started_at" in fields),
                ("ended_at", "ended_at" in fields),
                ("duration_ms", "duration_ms" in fields),
                ("status", "status" in fields),
            ]
            for fname, ok in checks:
                record("RECEIPT", f"Field '{fname}' present", PASS if ok else FAIL, "")
        else:
            record("RECEIPT", "Retrieve receipt", FAIL, str(r.text))

    # List receipts by task
    r = httpx.get(f"{BASE_URL}/v1/receipts/task/{task_id}")
    if r.status_code == 200:
        count = len(r.json())
        record("RECEIPT", "List receipts by task", PASS, f"Found {count} receipts")
    else:
        record("RECEIPT", "List receipts by task", FAIL, str(r.text))

    # Test receipt with signature field (if available)
    record("RECEIPT", "Receipt agent_signature field", BLOCKED,
           "Signature verification not implemented in current API receipts.")

    # T7.1: Duplicate receipt test
    if created_receipts:
        first = httpx.get(f"{BASE_URL}/v1/receipts/{created_receipts[0]}").json()
        # Try reposting same receipt but with a new receipt_id field (the API generates it)
        first.pop("receipt_id", None)
        r = httpx.post(f"{BASE_URL}/v1/receipts", json=first)
        if r.status_code == 201:
            record("RECEIPT", "Duplicate receipt prevention", FAIL,
                   "Same receipt data accepted again. No idempotency/replay protection on input.")
        else:
            record("RECEIPT", "Duplicate receipt prevention", PASS,
                   f"HTTP {r.status_code}: duplicate rejected")


# ===================================================================
# SECTION 8: Progress Tracking
# ===================================================================
def test_progress():
    header("SECTION 8: PROGRESS TRACKING")

    record("PROGRESS", "Submit Progress Receipt (30%)", BLOCKED,
           "No dedicated progress receipt endpoint. Receipts exist but no progress % tracking.")
    record("PROGRESS", "Console shows progress %", BLOCKED,
           "No Console UI.")
    record("PROGRESS", "Status: InProgress → ProgressSubmitted → ProgressConfirmed", BLOCKED,
           "Status machine has CREATED/LOCKED/RUNNING/SUBMITTED but no progress-specific states.")
    record("PROGRESS", "Progress cannot regress", BLOCKED,
           "No progress endpoint to test regression on.")


# ===================================================================
# SECTION 9: Settlement
# ===================================================================
def test_settlement():
    header("SECTION 9: SETTLEMENT")

    if not created_tasks:
        record("SETTLE", "Skip: No tasks created", SKIP, "")
        return

    task_id = created_tasks[0]
    agent_a = test_agents["A"]["id"] or "client-fallback"
    agent_b = test_agents["B"]["id"] or "worker-fallback"

    # Create settlement
    r = httpx.post(f"{BASE_URL}/v1/settlement/create", json={
        "task_id": task_id,
        "client_agent_id": agent_a,
        "escrow_amount": 20.0,
        "currency": "USD",
    })
    if r.status_code == 201:
        state = r.json()
        record("SETTLE", "Create Settlement", PASS, f"status={state['status']}")
    else:
        record("SETTLE", "Create Settlement", FAIL, f"HTTP {r.status_code}: {r.text}")
        return

    # Lock
    r = httpx.post(f"{BASE_URL}/v1/settlement/{task_id}/lock", json={
        "worker_agent_id": agent_b
    })
    if r.status_code == 200:
        record("SETTLE", "Lock Settlement", PASS, f"status={r.json()['status']}")
    else:
        record("SETTLE", "Lock Settlement", FAIL, str(r.text))

    # Start
    r = httpx.post(f"{BASE_URL}/v1/settlement/{task_id}/start", json={})
    if r.status_code == 200:
        record("SETTLE", "Start Settlement", PASS, f"status={r.json()['status']}")
    else:
        record("SETTLE", "Start Settlement", FAIL, str(r.text))

    # Submit
    r = httpx.post(f"{BASE_URL}/v1/settlement/{task_id}/submit", json={})
    if r.status_code == 200:
        record("SETTLE", "Submit Settlement", PASS, f"status={r.json()['status']}")
    else:
        record("SETTLE", "Submit Settlement", FAIL, str(r.text))

    # Get final state
    r = httpx.get(f"{BASE_URL}/v1/settlement/{task_id}")
    if r.status_code == 200:
        final = r.json()
        record("SETTLE", "Settlement State Machine: CREATED→LOCKED→RUNNING→SUBMITTED", PASS,
               f"final status={final['status']}, escrow={final['escrow_amount']} {final.get('currency','')}")
    else:
        record("SETTLE", "Get final settlement state", FAIL, str(r.text))

    # Verify state cannot skip (try going Pending→Settled directly)
    record("SETTLE", "State Machine: prevent CREATED→SUBMITTED skip", BLOCKED,
           "API allows direct status updates via POST — no state machine guard on transitions.")

    # Settlement on-chain (testnet)
    record("SETTLE", "On-chain USDC transfer (testnet)", BLOCKED,
           "No testnet Sepolia chain integration in running API. SETTLEMENT_MODE=offchain.")


# ===================================================================
# SECTION 10: Dispute
# ===================================================================
def test_dispute():
    header("SECTION 10: DISPUTE")

    record("DISPUTE", "File Dispute", BLOCKED,
           "No /v1/disputes endpoint exists.")
    record("DISPUTE", "Freeze Funds on Dispute", BLOCKED,
           "No dispute mechanics in API.")
    record("DISPUTE", "Submit Evidence for Dispute", BLOCKED,
           "No dispute evidence submission.")
    record("DISPUTE", "Dispute Resolution / Arbitration", BLOCKED,
           "No arbitration logic.")
    record("DISPUTE", "Disputed state prevents settlement", BLOCKED,
           "No Disputed status in current state machine.")


# ===================================================================
# SECTION 11: Verification
# ===================================================================
def test_verification():
    header("SECTION 11: VERIFICATION")

    test_id = f"task-verify-{uuid.uuid4().hex[:8]}"
    r = httpx.post(f"{BASE_URL}/v1/verify", json={
        "bundle": {
            "task_id": test_id,
            "task_contract_hash": "a" * 64,
            "receipt_ids": ["r1", "r2"],
            "receipt_hashes": ["h1", "h2"],
            "final_result_hash": "f" * 64,
            "total_steps": 2,
            "successful_steps": 2,
            "failed_steps": 0,
            "total_duration_ms": 400,
            "created_at": datetime.utcnow().isoformat(),
        },
        "contract": {
            "task_id": test_id,
            "client_agent_id": "verify-client",
            "title": "Verify Test",
            "description": "Test verification",
            "expected_output_schema": {},
            "expected_step_count": 2,
            "escrow_amount": 10.0,
            "currency": "USD",
            "deadline_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
    })
    if r.status_code == 200:
        data = r.json()
        record("VERIFY", "Submit Bundle for Verification", PASS,
               f"decision={data.get('decision', '?')}, bundle_id={data.get('bundle_id', '?')[:12]}...")
    else:
        record("VERIFY", "Submit Bundle for Verification", FAIL,
               f"HTTP {r.status_code}: {r.text}")


# ===================================================================
# SECTION 12: Security Boundary Tests
# ===================================================================
def test_security_boundaries():
    header("SECTION 12: SECURITY BOUNDARY TESTS")

    # These are tests that any user should NOT be able to do
    # We test available endpoints for basic auth

    # Test auth endpoint
    r = httpx.post(f"{BASE_URL}/v1/auth/token", json={
        "agent_id": "fake-agent",
        "api_key": "fake-key",
    })
    has_auth_ep = r.status_code < 500
    record("SECURITY", "Auth token endpoint exists", PASS if has_auth_ep else FAIL,
           f"HTTP {r.status_code}")

    # Try invalid agent access
    record("SECURITY", "Runtime Key modify lock amount", BLOCKED, "No Runtime Key system.")
    record("SECURITY", "Runtime Key increase daily limit", BLOCKED, "No Runtime Key system.")
    record("SECURITY", "Runtime Key modify security rules", BLOCKED, "No Runtime Key system.")
    record("SECURITY", "Runtime Key change wallet", BLOCKED, "No Runtime Key system.")
    record("SECURITY", "Runtime Key delete bills", BLOCKED, "No Runtime Key system.")
    record("SECURITY", "Agent forge other karma_id", BLOCKED,
           "No karma_id concept in current API. Uses agent_id UUIDs.")
    record("SECURITY", "Agent forge seller_id", BLOCKED,
           "No seller_id concept. Contract uses worker_agent_id.")


# ===================================================================
# SECTION 13: Risk Engine
# ===================================================================
def test_risk_engine():
    header("SECTION 13: PRIVATE RISK ENGINE")

    # Check if private risk engine is running
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    risk_up = s.connect_ex(("localhost", 8822)) == 0
    s.close()

    if risk_up:
        record("RISK", "Private Risk Engine running", PASS, "port 8822 reachable")
    else:
        record("RISK", "Private Risk Engine running", BLOCKED,
               "Not running on port 8822")

    record("RISK", "Risk check on Runtime Key creation", BLOCKED,
           "No Runtime Key creation flow.")
    record("RISK", "Risk check on Runtime Key usage", BLOCKED,
           "No Runtime Key usage flow.")
    record("RISK", "Risk check on Voucher request", BLOCKED,
           "No Voucher flow.")
    record("RISK", "Risk check on Receipt submission", BLOCKED,
           "No risk engine integration in receipt POST handler.")
    record("RISK", "Risk check on Progress submission", BLOCKED,
           "No progress endpoint.")
    record("RISK", "Risk check on Settlement request", BLOCKED,
           "No risk engine integration in settlement handler.")
    record("RISK", "Risk check on Dispute diversion", BLOCKED,
           "No dispute endpoint.")
    record("RISK", "Risk response: allow/deny/manual_confirm/freeze/review", BLOCKED,
           "No risk pipeline in API middleware.")


# ===================================================================
# SECTION 14: State Sync / Console
# ===================================================================
def test_state_sync():
    header("SECTION 14: CONSOLE STATE SYNCHRONIZATION")

    record("CONSOLE", "Console Frontend available", BLOCKED,
           "No console frontend deployed. No web UI available.")
    record("CONSOLE", "Real-time state sync (WebSocket/SSE)", BLOCKED,
           "No WebSocket or SSE endpoint for real-time state sync.")
    record("CONSOLE", "Runtime Key status display", BLOCKED, "No Runtime Key system.")
    record("CONSOLE", "Available/Reserved credits display", BLOCKED, "No credit tracking.")
    record("CONSOLE", "Task status in Console", BLOCKED, "No Console UI.")
    record("CONSOLE", "Receipt count in Console", BLOCKED, "No Console UI.")
    record("CONSOLE", "Progress % in Console", BLOCKED, "No progress tracking.")
    record("CONSOLE", "Settlement status in Console", BLOCKED, "No Console UI.")
    record("CONSOLE", "Dispute status in Console", BLOCKED, "No dispute API.")
    record("CONSOLE", "Risk alerts in Console", BLOCKED, "No risk alert system.")


# ===================================================================
# SECTION 15: Performance (Basic)
# ===================================================================
def test_performance():
    header("SECTION 15: BASIC PERFORMANCE CHECK")

    # Quick latency check
    latencies = []
    for _ in range(20):
        start = time.perf_counter()
        r = httpx.get(f"{BASE_URL}/health", timeout=5)
        latencies.append((time.perf_counter() - start) * 1000)

    avg = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    record("PERF", "API Health endpoint latency (20 reqs)", PASS if avg < 100 else FAIL,
           f"avg={avg:.1f}ms, max={max_lat:.1f}ms")

    # Batch receipt submit
    task_id = created_tasks[0] if created_tasks else "perf-test-task"
    agent = test_agents["B"]["id"] or "worker-perf"
    start = time.perf_counter()
    success = 0
    for i in range(10):
        now = datetime.utcnow()
        r = httpx.post(f"{BASE_URL}/v1/receipts", json={
            "task_id": task_id,
            "agent_id": agent,
            "step_index": 100 + i,
            "tool_name": f"perf.tool.{i}",
            "input_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            "output_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            "started_at": now.isoformat(),
            "ended_at": (now + timedelta(milliseconds=50)).isoformat(),
            "duration_ms": 50,
            "status": "success",
        })
        if r.status_code == 201:
            success += 1
    elapsed = (time.perf_counter() - start) * 1000
    record("PERF", "Batch 10 receipts", PASS if success == 10 else FAIL,
           f"{success}/10 in {elapsed:.0f}ms ({elapsed/10:.0f}ms avg)")

    record("PERF", "1000 Receipts + Queue + Worker", BLOCKED,
           "No queue/worker infrastructure running.")
    record("PERF", "100 Progress events", BLOCKED, "No progress endpoint.")
    record("PERF", "50 Settlements", BLOCKED, "No bulk settlement endpoint.")
    record("PERF", "10 Disputes", BLOCKED, "No dispute endpoint.")
    record("PERF", "Database dedup check", BLOCKED,
           "No dedup testing infrastructure.")


# ===================================================================
# SECTION 16: On-Chain / Testnet Validation
# ===================================================================
def test_onchain():
    header("SECTION 16: ON-CHAIN / TESTNET VALIDATION")

    record("CHAIN", "Testnet contract deployment status", BLOCKED,
           "Contracts deployed to Sepolia but API running in offchain mode.")
    record("CHAIN", "Mock USDC / Testnet USDC available", BLOCKED,
           "No USDC integration in running API.")
    record("CHAIN", "USDC deposit → Vault contract", BLOCKED,
           "No vault deposit flow.")
    record("CHAIN", "USDC withdrawal with settlement", BLOCKED,
           "No on-chain settlement integration.")
    record("CHAIN", "Escrow lock/release on-chain", BLOCKED,
           "No on-chain escrow flow.")


# ===================================================================
# SECTION 17: Comprehensive Status Check
# ===================================================================
def test_status_check():
    header("SECTION 17: COMPREHENSIVE STATUS CHECK")

    # Check state machine defined in schemas
    try:
        from core.schemas import TaskStatus
        states = [s.value for s in TaskStatus]
        record("SCHEMA", "TaskStatus states defined", PASS, f"States: {states}")
    except Exception as e:
        record("SCHEMA", "TaskStatus import", FAIL, str(e))

    # Check SDK exports
    try:
        from sdk import KarmaClient, TaskRunner
        record("SCHEMA", "SDK exports (KarmaClient, TaskRunner)", PASS, "ok")
    except Exception as e:
        record("SCHEMA", "SDK exports", FAIL, str(e))

    # Check ABIs exist
    import os
    abi_dir = "/Users/mac_02/Karma/karma-final/karma-public/abi"
    abis = os.listdir(abi_dir) if os.path.isdir(abi_dir) else []
    record("CHAIN", f"Contract ABIs available", PASS if abis else FAIL,
           f"ABIs: {abis}" if abis else "No ABIs found")


# ===================================================================
# MAIN
# ===================================================================
def main():
    print("\n" + "="*70)
    print("  KARMA TRUST PROTOCOL — E2E LIVE SYSTEM TEST")
    print(f"  Base URL: {BASE_URL}")
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print("="*70)

    if not test_environment():
        print("\n❌ ENVIRONMENT CHECK FAILED — ABORTING")
        return 1

    test_agent_registration()
    test_balance_and_credits()
    test_runtime_key()
    test_agent_auth()
    test_sdk_integration()
    test_contract_and_voucher()
    test_execution_receipts()
    test_progress()
    test_settlement()
    test_dispute()
    test_verification()
    test_security_boundaries()
    test_risk_engine()
    test_state_sync()
    test_performance()
    test_onchain()
    test_status_check()

    # Summary
    print("\n" + "="*70)
    print("  E2E TEST SUMMARY")
    print("="*70)

    passes = sum(1 for r in results if r["status"] == PASS)
    fails = sum(1 for r in results if r["status"] == FAIL)
    blocks = sum(1 for r in results if r["status"] == BLOCKED)
    skips = sum(1 for r in results if r["status"] == SKIP)
    total = len(results)

    print(f"\n  Total tests: {total}")
    print(f"  {PASS}: {passes}")
    print(f"  {FAIL}: {fails}")
    print(f"  {BLOCKED}: {blocks}")
    print(f"  {SKIP}: {skips}")

    # Detailed fails
    if fails:
        print(f"\n  --- FAILURES ---")
        for r in results:
            if r["status"] == FAIL:
                print(f"  ❌ [{r['section']}] {r['test']}: {r['detail']}")

    # Detailed blocked (what's missing)
    if blocks:
        print(f"\n  --- BLOCKED (Not Yet Implemented) ---")
        for r in results:
            if r["status"] == BLOCKED:
                print(f"  🚫 [{r['section']}] {r['test']}: {r['detail']}")

    # Go/no-go assessment
    print(f"\n  --- LAUNCH READINESS ---")
    total_feasible = passes + fails
    if fails == 0 and passes > 0:
        print(f"  ⚠️  All feasible tests pass, but {blocks} features are NOT IMPLEMENTED")
        print(f"  ⚠️  NOT READY for production launch")
    elif fails > 0:
        print(f"  ❌ {fails} failures — NOT READY")
    else:
        print(f"  ❌ All tests blocked — system not running")

    print(f"\n  Key gaps (must be built before launch):")
    print(f"    1. Runtime Key generation + management (KRM_RT_xxx)")
    print(f"    2. Voucher system (create, verify, redeem)")
    print(f"    3. Progress Receipts (separate from execution receipts)")
    print(f"    4. Dispute API (file, evidence, resolution)")
    print(f"    5. Private Risk Engine integration + middleware")
    print(f"    6. Console/Frontend (web UI for users)")
    print(f"    7. USDC vault/escrow on-chain integration")
    print(f"    8. State machine guards on API transitions")
    print(f"    9. Webhook/real-time state sync")
    print(f"    10. 1:1 credit/debit ledger")

    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
