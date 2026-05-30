#!/usr/bin/env python3
"""
Karma Stress Test — 500 Concurrent Requests Per Scenario
========================================================
Tests API under high concurrency across all major endpoints.
"""
from __future__ import annotations
import asyncio, json, sys, time, uuid
from datetime import datetime, timedelta
from statistics import mean, median, stdev
import httpx

BASE = "http://localhost:8000"
CONCURRENT = 500
TIMEOUT = 30.0

results = {}

def header(text):
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}")

# ============================================================
# Stress harness
# ============================================================
async def stress(name: str, tasks: list, label: str = ""):
    """Run N concurrent tasks and report stats."""
    t0 = time.perf_counter()
    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.perf_counter() - t0
    
    latencies = []
    errors = 0
    codes = {}
    for r in gathered:
        if isinstance(r, Exception):
            errors += 1
        elif hasattr(r, 'elapsed'):
            latencies.append(r.elapsed.total_seconds() * 1000)
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
            if r.status_code >= 400:
                errors += 1
        elif isinstance(r, dict) and "error" in r:
            errors += 1
    
    if not latencies:
        results[name] = {"ops": 0, "errors": errors, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0}
        print(f"  ❌ {name}: ALL FAILED ({errors} errors)")
        return

    latencies.sort()
    n = len(latencies)
    p50 = latencies[n//2]
    p95 = latencies[int(n*0.95)]
    p99 = latencies[int(n*0.99)]
    avg = mean(latencies)
    throughput = n / elapsed
    success = n - sum(1 for c in codes if c >= 400)
    
    results[name] = {
        "ops": success, "errors": errors, "avg_ms": avg, "p50_ms": p50,
        "p95_ms": p95, "p99_ms": p99,
        "min_ms": latencies[0], "max_ms": latencies[-1],
        "throughput": throughput, "elapsed_s": elapsed,
        "codes": codes
    }
    
    print(f"  ✅ {name}: {success}/{n} ok, {errors} errors, "
          f"avg={avg:.1f}ms p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms "
          f"throughput={throughput:.0f} req/s")

# ============================================================
# Setup: create test identities
# ============================================================
async def setup():
    """Create test data: identities, agents, capacity."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Create identities
        ids = []
        for i in range(20):
            r = await c.post(f"{BASE}/v1/identities", json={
                "display_id": f"stress-user-{i}",
                "legal_identity_status": "self_attested"
            })
            if r.status_code in (200, 201):
                ids.append(r.json().get("identity_id", f"id-{i}"))
        if not ids:
            # Fallback: use agents directly
            print("  ⚠️ Identity creation failed, using agent fallback")
            return [], []
        
        # Create agents
        agents = []
        for i in range(min(20, len(ids))):
            r = await c.post(f"{BASE}/v1/agents", json={
                "name": f"stress-agent-{i}", "role": "worker",
                "capabilities": ["stress_test"]
            })
            if r.status_code == 201:
                agents.append(r.json()["agent_id"])
        
        print(f"  Setup: {len(ids)} identities, {len(agents)} agents")
        return ids, agents

# ============================================================
# SCENARIO 1: Health Check (baseline)
# ============================================================
async def stress_health():
    header("SCENARIO 1: HEALTH CHECK (500 concurrent)")
    async def one():
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            return await c.get(f"{BASE}/health")
    tasks = [one() for _ in range(CONCURRENT)]
    await stress("1. Health Check", tasks)

# ============================================================
# SCENARIO 2: Agent Registration (500 concurrent)
# ============================================================
async def stress_agent_register():
    header("SCENARIO 2: AGENT REGISTRATION (500 concurrent)")
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            return await c.post(f"{BASE}/v1/agents", json={
                "name": f"stress-{uuid.uuid4().hex[:8]}",
                "role": "worker",
                "capabilities": ["stress"]
            })
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("2. Agent Registration", tasks)

# ============================================================
# SCENARIO 3: Contract Creation (500 concurrent)
# ============================================================
async def stress_contracts(agent_ids):
    header("SCENARIO 3: CONTRACT CREATION (500 concurrent)")
    deadline = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            client_id = agent_ids[i % len(agent_ids)] if agent_ids else "any"
            return await c.post(f"{BASE}/v1/contracts", json={
                "client_agent_id": client_id,
                "title": f"Stress Task {i}",
                "description": "Concurrent contract stress test",
                "expected_output_schema": {},
                "expected_step_count": 3,
                "escrow_amount": 10.0,
                "currency": "USD",
                "deadline_at": deadline
            })
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("3. Contract Creation", tasks)

# ============================================================
# SCENARIO 4: Receipt Submission (500 concurrent, single task)
# ============================================================
async def stress_receipts(agent_ids):
    header("SCENARIO 4: RECEIPT SUBMISSION (500 concurrent)")
    # First create a task
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/agents", json={"name": "receipt-worker","role": "worker"})
        agent = r.json()["agent_id"]
        r = await c.post(f"{BASE}/v1/contracts", json={
            "client_agent_id": agent, "title":"Receipt Stress","description":"test",
            "expected_output_schema":{},"expected_step_count":CONCURRENT,
            "escrow_amount":1000.0,"currency":"USD",
            "deadline_at":(datetime.utcnow()+timedelta(hours=1)).isoformat()
        })
        task_id = r.json()["task_id"]
    
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c2:
            now = datetime.utcnow()
            return await c2.post(f"{BASE}/v1/receipts", json={
                "task_id": task_id, "agent_id": agent,
                "step_index": i, "tool_name": f"tool.step{i}",
                "input_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                "output_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                "started_at": now.isoformat(),
                "ended_at": (now + timedelta(milliseconds=50)).isoformat(),
                "duration_ms": 50, "status": "success"
            })
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("4. Receipt Submission", tasks)

# ============================================================
# SCENARIO 5: Receipt Retrieval (500 concurrent reads)
# ============================================================
async def stress_receipt_reads(agent_ids):
    header("SCENARIO 5: RECEIPT LIST (500 concurrent reads)")
    # Get a task that has receipts
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{BASE}/v1/agents")
        agents = r.json()
        if agents:
            agent_id = agents[0]["agent_id"]
            r = await c.post(f"{BASE}/v1/contracts", json={
                "client_agent_id":agent_id,"title":"Read Stress","description":"t",
                "expected_output_schema":{},"expected_step_count":5,
                "escrow_amount":10.0,"currency":"USD",
                "deadline_at":(datetime.utcnow()+timedelta(hours=1)).isoformat()
            })
            tid = r.json()["task_id"]
            # Submit a few receipts
            for i in range(5):
                now = datetime.utcnow()
                await c.post(f"{BASE}/v1/receipts", json={
                    "task_id":tid,"agent_id":agent_id,"step_index":i,
                    "tool_name":f"r{i}","input_hash":"a"*64,"output_hash":"b"*64,
                    "started_at":now.isoformat(),"ended_at":now.isoformat(),
                    "duration_ms":10,"status":"success"
                })
        else:
            tid = "unknown"
    
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c2:
            return await c2.get(f"{BASE}/v1/receipts/task/{tid}")
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("5. Receipt Retrieval", tasks)

# ============================================================
# SCENARIO 6: Agent List (500 concurrent reads)
# ============================================================
async def stress_agent_list():
    header("SCENARIO 6: AGENT LIST (500 concurrent reads)")
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            return await c.get(f"{BASE}/v1/agents")
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("6. Agent List", tasks)

# ============================================================
# SCENARIO 7: Security Policies (500 concurrent reads)
# ============================================================
async def stress_security_policies():
    header("SCENARIO 7: SECURITY POLICIES (500 concurrent reads)")
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            return await c.get(f"{BASE}/v1/security/policies")
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("7. Security Policies", tasks)

# ============================================================
# SCENARIO 8: Mixed Full Pipeline (500 concurrent mixed ops)
# ============================================================
async def stress_mixed_pipeline(agent_ids):
    header("SCENARIO 8: MIXED FULL PIPELINE (500 concurrent)")
    deadline = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    ops = ["health", "agent_list", "create_contract", "agent_register"]
    
    async def one(i):
        op = ops[i % len(ops)]
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            if op == "health":
                return await c.get(f"{BASE}/health")
            elif op == "agent_list":
                return await c.get(f"{BASE}/v1/agents")
            elif op == "create_contract":
                aid = agent_ids[i % len(agent_ids)] if agent_ids else "any"
                return await c.post(f"{BASE}/v1/contracts", json={
                    "client_agent_id": aid, "title":f"Mixed {i}",
                    "description":"mixed stress","expected_output_schema":{},
                    "expected_step_count":2,"escrow_amount":5.0,
                    "currency":"USD","deadline_at":deadline
                })
            elif op == "agent_register":
                return await c.post(f"{BASE}/v1/agents", json={
                    "name":f"mixed-{uuid.uuid4().hex[:6]}",
                    "role":"worker","capabilities":["mixed"]
                })
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("8. Mixed Pipeline", tasks)

# ============================================================
# SCENARIO 9: Settlement Create (500 concurrent)
# ============================================================
async def stress_settlement_create(agent_ids):
    header("SCENARIO 9: SETTLEMENT CREATE (500 concurrent)")
    # Pre-create tasks
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        task_ids = []
        aid = agent_ids[0] if agent_ids else "default-agent"
        for i in range(min(50, CONCURRENT)):
            r = await c.post(f"{BASE}/v1/contracts", json={
                "client_agent_id": aid, "title":f"Settle {i}",
                "description":"settlement stress","expected_output_schema":{},
                "expected_step_count":2,"escrow_amount":5.0,
                "currency":"USD",
                "deadline_at":(datetime.utcnow()+timedelta(hours=1)).isoformat()
            })
            if r.status_code == 201:
                task_ids.append(r.json()["task_id"])
    
    async def one(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c2:
            tid = task_ids[i % len(task_ids)] if task_ids else f"task-{i}"
            a = agent_ids[i % len(agent_ids)] if agent_ids else "any"
            return await c2.post(f"{BASE}/v1/settlement/create", json={
                "task_id": tid, "client_agent_id": a,
                "escrow_amount": 5.0, "currency": "USD"
            })
    tasks = [one(i) for i in range(CONCURRENT)]
    await stress("9. Settlement Create", tasks)

# ============================================================
# SCENARIO 10: Rapid Sequential Pipeline (burst test)
# ============================================================
async def stress_rapid_burst():
    header("SCENARIO 10: RAPID BURST PIPELINE (100 batches × 5 concurrent)")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        total_ok = 0
        total_err = 0
        t0 = time.perf_counter()
        
        for batch in range(100):
            tasks = [c.get(f"{BASE}/health") for _ in range(5)]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            for r in gathered:
                if isinstance(r, Exception):
                    total_err += 1
                elif r.status_code == 200:
                    total_ok += 1
                else:
                    total_err += 1
        
        elapsed = time.perf_counter() - t0
        throughput = (total_ok + total_err) / elapsed
    
    results["10. Rapid Burst"] = {
        "ops": total_ok, "errors": total_err,
        "throughput": throughput, "elapsed_s": elapsed,
        "batches": 100, "per_batch": 5
    }
    print(f"  ✅ 10. Rapid Burst: {total_ok} ok / {total_err} err, "
          f"throughput={throughput:.0f} req/s, {elapsed:.1f}s")

# ============================================================
# MAIN
# ============================================================
async def main():
    print("\n" + "="*70)
    print(f"  KARMA STRESS TEST — {CONCURRENT} CONCURRENT PER SCENARIO")
    print(f"  Base URL: {BASE}")
    print(f"  Time: {datetime.utcnow().isoformat()}Z")
    print("="*70)
    
    # Check API
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE}/health")
        print(f"\n  API Status: {r.json()}")
    
    # Setup
    print(f"\n  Setting up test data...")
    ids, agents = await setup()
    
    # Run scenarios
    await stress_health()
    await stress_agent_register()
    await stress_agent_list()
    await stress_security_policies()
    
    if agents:
        await stress_contracts(agents)
        await stress_receipts(agents)
        await stress_receipt_reads(agents)
        await stress_mixed_pipeline(agents)
        await stress_settlement_create(agents)
    else:
        print("  ⚠️ Skipping agent-dependent scenarios (no agents)")
    
    await stress_rapid_burst()
    
    # ================================================================
    # FINAL REPORT
    # ================================================================
    print("\n" + "="*70)
    print(f"  STRESS TEST REPORT — FINAL")
    print("="*70)
    
    total_ops = sum(r.get("ops", 0) for r in results.values())
    total_err = sum(r.get("errors", 0) for r in results.values())
    
    print(f"\n  {'Scenario':<35} {'Success':>8} {'Errors':>8} {'Avg':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'RPS':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    
    for name, r in results.items():
        ops = r.get("ops", 0)
        errs = r.get("errors", 0)
        avg = r.get("avg_ms", 0)
        p50 = r.get("p50_ms", 0)
        p95 = r.get("p95_ms", 0)
        p99 = r.get("p99_ms", 0)
        tput = r.get("throughput", 0)
        print(f"  {name:<35} {ops:>8} {errs:>8} {avg:>7.1f}ms {p50:>7.1f}ms {p95:>7.1f}ms {p99:>7.1f}ms {tput:>7.0f}/s")
    
    print(f"\n  {'─'*60}")
    print(f"  TOTAL: {total_ops:,} successful, {total_err:,} errors across {len(results)} scenarios")
    
    # Stability assessment
    error_rate = total_err / max(total_ops + total_err, 1) * 100
    if error_rate < 1:
        print(f"  🟢 STABLE — Error rate: {error_rate:.2f}%")
    elif error_rate < 5:
        print(f"  🟡 DEGRADED — Error rate: {error_rate:.2f}%")
    else:
        print(f"  🔴 UNSTABLE — Error rate: {error_rate:.2f}%")
    
    # Check DB integrity
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{BASE}/v1/agents")
        agent_count = len(r.json()) if r.status_code == 200 else 0
        print(f"  📊 DB Final State: {agent_count} agents in database")
    
    print(f"\n  Test configuration:")
    print(f"    Concurrency: {CONCURRENT} per scenario")
    print(f"    Database: SQLite (WAL mode)")
    print(f"    API Workers: 1 (uvicorn)")
    print(f"    Timeout: {TIMEOUT}s per request")
    
    return 0 if error_rate < 5 else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
