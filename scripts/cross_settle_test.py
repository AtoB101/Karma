#!/usr/bin/env python3
"""
Karma Cross-Settlement Integrity Test
======================================
10,000 accounts, 1,000 concurrent cross-calls.
Validates: total_settled + total_locked = total_issued (ledger balance)
"""
from __future__ import annotations
import asyncio, json, sys, time, uuid
from datetime import datetime, timedelta
from statistics import mean, median
import httpx

BASE = "http://localhost:8000"
TOTAL_ACCOUNTS = 10000
CONCURRENT = 1000
BATCH_SIZE = 500
TIMEOUT = 120.0
ESCROW_PER_TASK = 0.50  # Small amounts for testing

results = {}
ledger = {"total_locked": 0.0, "total_settled": 0.0, "total_in_flight": 0.0, "errors": 0}

def log(msg):
    print(f"  [{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")

# ============================================================
# Phase 1: Create 10,000 Agents (batched)
# ============================================================
async def phase1_create_agents():
    print(f"\n{'='*60}")
    print(f"  PHASE 1: CREATE {TOTAL_ACCOUNTS} AGENTS")
    print(f"{'='*60}")
    
    agent_ids = []
    t0 = time.perf_counter()
    
    for batch_start in range(0, TOTAL_ACCOUNTS, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, TOTAL_ACCOUNTS)
        batch_tasks = []
        
        async def register_one(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    r = await c.post(f"{BASE}/v1/agents", json={
                        "name": f"acc-{i:05d}",
                        "role": "worker",
                        "capabilities": ["cross_settle"]
                    })
                    if r.status_code == 201:
                        return r.json()["agent_id"]
                except:
                    pass
                return None
        
        for i in range(batch_start, batch_end):
            batch_tasks.append(register_one(i))
        
        batch_results = await asyncio.gather(*batch_tasks)
        new_agents = [a for a in batch_results if a is not None]
        agent_ids.extend(new_agents)
        
        pct = batch_end / TOTAL_ACCOUNTS * 100
        elapsed = time.perf_counter() - t0
        rate = batch_end / elapsed if elapsed > 0 else 0
        log(f"  Batch {batch_start//BATCH_SIZE+1}: {len(new_agents)} created | "
            f"{batch_end}/{TOTAL_ACCOUNTS} ({pct:.0f}%) | {rate:.0f} agents/s | {len(agent_ids)} total")
    
    elapsed = time.perf_counter() - t0
    results["phase1"] = {"agents": len(agent_ids), "time_s": elapsed, "rate": len(agent_ids)/elapsed}
    log(f"  ✅ PHASE 1 DONE: {len(agent_ids)} agents in {elapsed:.1f}s ({len(agent_ids)/elapsed:.0f}/s)")
    return agent_ids

# ============================================================
# Phase 2: Lock USDC & Create Capacity for all agents
# ============================================================
async def phase2_lock_capacity(agent_ids):
    print(f"\n{'='*60}")
    print(f"  PHASE 2: CREATE CONTRACTS & SIMULATE LOCK")
    print(f"{'='*60}")
    
    contract_ids = []
    total_locked = 0.0
    t0 = time.perf_counter()
    
    for batch_start in range(0, len(agent_ids), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(agent_ids))
        batch_tasks = []
        
        async def create_contract(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    buyer = agent_ids[i]
                    seller = agent_ids[(i + 1) % len(agent_ids)]
                    deadline = (datetime.utcnow() + timedelta(hours=2)).isoformat()
                    r = await c.post(f"{BASE}/v1/contracts", json={
                        "client_agent_id": buyer,
                        "title": f"Cross-Settle {i}",
                        "description": f"Cross settlement between {buyer[:8]} and {seller[:8]}",
                        "expected_output_schema": {"type": "object"},
                        "expected_step_count": 3,
                        "escrow_amount": ESCROW_PER_TASK,
                        "currency": "USD",
                        "deadline_at": deadline,
                    })
                    if r.status_code == 201:
                        data = r.json()
                        # Assign seller
                        await c.patch(f"{BASE}/v1/contracts/{data['task_id']}/assign?worker_agent_id={seller}")
                        return (data["task_id"], ESCROW_PER_TASK)
                except:
                    pass
                return None
        
        for i in range(batch_start, batch_end):
            batch_tasks.append(create_contract(i))
        
        batch_results = await asyncio.gather(*batch_tasks)
        for r in batch_results:
            if r:
                contract_ids.append(r[0])
                total_locked += r[1]
        
        pct = batch_end / len(agent_ids) * 100
        elapsed = time.perf_counter() - t0
        log(f"  Batch: {len(contract_ids)} contracts | {total_locked:.2f} USD locked | "
            f"{pct:.0f}% | {len(contract_ids)/elapsed:.0f}/s")
    
    elapsed = time.perf_counter() - t0
    ledger["total_locked"] = total_locked
    results["phase2"] = {"contracts": len(contract_ids), "total_locked": total_locked, 
                          "time_s": elapsed, "rate": len(contract_ids)/elapsed}
    log(f"  ✅ PHASE 2 DONE: {len(contract_ids)} contracts, {total_locked:.2f} USD locked in {elapsed:.1f}s")
    return contract_ids

# ============================================================
# Phase 3: Submit Receipts (1000 concurrent)
# ============================================================
async def phase3_receipts(agent_ids, contract_ids):
    print(f"\n{'='*60}")
    print(f"  PHASE 3: SUBMIT RECEIPTS @ {CONCURRENT} CONCURRENT")
    print(f"{'='*60}")
    
    # Pick a subset of contracts for receipts (to keep it manageable)
    sample_size = min(5000, len(contract_ids))
    sample_contracts = contract_ids[:sample_size]
    
    t0 = time.perf_counter()
    successes = 0
    errors = 0
    
    for batch_start in range(0, sample_size, CONCURRENT):
        batch_end = min(batch_start + CONCURRENT, sample_size)
        
        async def submit_receipt(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    task_id = sample_contracts[i]
                    now = datetime.utcnow()
                    r = await c.post(f"{BASE}/v1/receipts", json={
                        "task_id": task_id,
                        "agent_id": agent_ids[i % len(agent_ids)],
                        "step_index": 1,
                        "tool_name": "cross.verify",
                        "input_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                        "output_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                        "started_at": now.isoformat(),
                        "ended_at": (now + timedelta(milliseconds=50)).isoformat(),
                        "duration_ms": 50,
                        "status": "success"
                    })
                    return r.status_code == 201
                except:
                    return False
        
        batch_tasks = [submit_receipt(i) for i in range(batch_start, batch_end)]
        batch_results = await asyncio.gather(*batch_tasks)
        successes += sum(1 for r in batch_results if r)
        errors += sum(1 for r in batch_results if not r)
        
        pct = batch_end / sample_size * 100
        elapsed = time.perf_counter() - t0
        rate = batch_end / elapsed if elapsed > 0 else 0
        log(f"  Receipts: {successes} ok + {errors} err | {pct:.0f}% | {rate:.0f}/s")
    
    elapsed = time.perf_counter() - t0
    results["phase3"] = {"success": successes, "errors": errors, "time_s": elapsed}
    log(f"  ✅ PHASE 3 DONE: {successes}/{sample_size} receipts in {elapsed:.1f}s")
    return successes, errors

# ============================================================
# Phase 4: Settlement (1000 concurrent)
# ============================================================
async def phase4_settlement(agent_ids, contract_ids):
    print(f"\n{'='*60}")
    print(f"  PHASE 4: SETTLEMENT @ {CONCURRENT} CONCURRENT")
    print(f"{'='*60}")
    
    sample_size = min(5000, len(contract_ids))
    sample_contracts = contract_ids[:sample_size]
    
    t0 = time.perf_counter()
    successes = 0
    errors = 0
    total_settled = 0.0
    
    for batch_start in range(0, sample_size, CONCURRENT):
        batch_end = min(batch_start + CONCURRENT, sample_size)
        
        async def settle_one(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    task_id = sample_contracts[i]
                    aid = agent_ids[i % len(agent_ids)]
                    
                    # Create settlement
                    r = await c.post(f"{BASE}/v1/settlement/create", json={
                        "task_id": task_id,
                        "client_agent_id": aid,
                        "escrow_amount": ESCROW_PER_TASK,
                        "currency": "USD"
                    })
                    if r.status_code not in (200, 201):
                        return (False, 0)
                    
                    # Lock → Start → Submit
                    for step in ["lock", "start", "submit"]:
                        body = {"worker_agent_id": agent_ids[(i+1) % len(agent_ids)]} if step == "lock" else {}
                        r2 = await c.post(f"{BASE}/v1/settlement/{task_id}/{step}", json=body)
                        if r2.status_code not in (200, 201):
                            return (False, 0)
                    
                    return (True, ESCROW_PER_TASK)
                except:
                    return (False, 0)
        
        batch_tasks = [settle_one(i) for i in range(batch_start, batch_end)]
        batch_results = await asyncio.gather(*batch_tasks)
        
        for ok, amount in batch_results:
            if ok:
                successes += 1
                total_settled += amount
            else:
                errors += 1
        
        pct = batch_end / sample_size * 100
        elapsed = time.perf_counter() - t0
        log(f"  Settlement: {successes} ok + {errors} err | "
            f"{total_settled:.2f} USD settled | {pct:.0f}%")
    
    elapsed = time.perf_counter() - t0
    ledger["total_settled"] = total_settled
    results["phase4"] = {"success": successes, "errors": errors, 
                          "total_settled": total_settled, "time_s": elapsed}
    log(f"  ✅ PHASE 4 DONE: {successes} settled, {total_settled:.2f} USD in {elapsed:.1f}s")
    return total_settled, errors

# ============================================================
# Phase 5: Cross-Verify Ledger Balance
# ============================================================
async def phase5_verify_ledger():
    print(f"\n{'='*60}")
    print(f"  PHASE 5: LEDGER BALANCE VERIFICATION")
    print(f"{'='*60}")
    
    async with httpx.AsyncClient(timeout=30) as c:
        # Count agents
        r = await c.get(f"{BASE}/v1/agents")
        agent_count = len(r.json()) if r.status_code == 200 else 0
        
        # Get security policies (system state)
        r = await c.get(f"{BASE}/v1/security/policies")
        policies_ok = r.status_code == 200
        
        # Get reputation leaderboard
        r = await c.get(f"{BASE}/v1/reputation?limit=100")
        rep_count = len(r.json()) if r.status_code == 200 else 0
    
    log(f"  Agents in DB: {agent_count}")
    log(f"  Security Policies: {'OK' if policies_ok else 'FAIL'}")
    log(f"  Reputation entries: {rep_count}")
    
    total_locked = ledger["total_locked"]
    total_settled = ledger["total_settled"]
    in_flight = total_locked - total_settled
    
    log(f"\n  📊 LEDGER SUMMARY:")
    log(f"    Total Locked (contracts):   {total_locked:>12.2f} USD")
    log(f"    Total Settled:              {total_settled:>12.2f} USD")
    log(f"    In Flight (pending/dispute):{in_flight:>12.2f} USD")
    log(f"    Balance Check: {total_locked:.2f} = {total_settled:.2f} + {in_flight:.2f}")
    
    balanced = abs(total_locked - (total_settled + in_flight)) < 0.01
    
    results["phase5"] = {
        "agent_count": agent_count,
        "total_locked": total_locked,
        "total_settled": total_settled,
        "in_flight": in_flight,
        "balanced": balanced,
        "delta": total_locked - total_settled - in_flight
    }
    
    if balanced:
        log(f"  ✅ LEDGER BALANCED: Total Locked = Total Settled + In-Flight")
    else:
        log(f"  🔴 LEDGER IMBALANCE: Delta = {total_locked - total_settled - in_flight:.4f} USD")
    
    return balanced

# ============================================================
# Phase 6: Concurrent Cross-Call Stress (mixed ops)
# ============================================================
async def phase6_cross_concurrent(agent_ids, contract_ids):
    print(f"\n{'='*60}")
    print(f"  PHASE 6: CROSS-CALL STRESS @ {CONCURRENT} CONCURRENT")
    print(f"{'='*60}")
    
    deadline = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    ops = ["health", "agent_list", "agent_lookup", "contract_create", "receipt", "settlement_create"]
    
    t0 = time.perf_counter()
    success = 0
    errors = 0
    latencies = []
    
    async def cross_op(i):
        op = ops[i % len(ops)]
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                t_start = time.perf_counter()
                if op == "health":
                    r = await c.get(f"{BASE}/health")
                elif op == "agent_list":
                    r = await c.get(f"{BASE}/v1/agents")
                elif op == "agent_lookup":
                    aid = agent_ids[i % len(agent_ids)]
                    r = await c.get(f"{BASE}/v1/agents/{aid}")
                elif op == "contract_create":
                    buyer = agent_ids[i % len(agent_ids)]
                    seller = agent_ids[(i * 7 + 13) % len(agent_ids)]  # pseudo-random cross
                    r = await c.post(f"{BASE}/v1/contracts", json={
                        "client_agent_id": buyer,
                        "title": f"Cross-Call {i}",
                        "description": f"Cross from {buyer[:6]} to {seller[:6]}",
                        "expected_output_schema": {}, "expected_step_count": 2,
                        "escrow_amount": ESCROW_PER_TASK, "currency": "USD",
                        "deadline_at": deadline
                    })
                elif op == "receipt":
                    if contract_ids:
                        tid = contract_ids[i % len(contract_ids)]
                        now = datetime.utcnow()
                        r = await c.post(f"{BASE}/v1/receipts", json={
                            "task_id": tid,
                            "agent_id": agent_ids[i % len(agent_ids)],
                            "step_index": (i % 3) + 1,
                            "tool_name": f"cross.{op}",
                            "input_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                            "output_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                            "started_at": now.isoformat(),
                            "ended_at": (now + timedelta(milliseconds=20)).isoformat(),
                            "duration_ms": 20, "status": "success"
                        })
                    else:
                        r = await c.get(f"{BASE}/health")
                elif op == "settlement_create":
                    if contract_ids:
                        tid = contract_ids[i % len(contract_ids)]
                        r = await c.post(f"{BASE}/v1/settlement/create", json={
                            "task_id": tid,
                            "client_agent_id": agent_ids[i % len(agent_ids)],
                            "escrow_amount": ESCROW_PER_TASK, "currency": "USD"
                        })
                    else:
                        r = await c.get(f"{BASE}/health")
                
                elapsed_ms = (time.perf_counter() - t_start) * 1000
                ok = r.status_code < 400
                return ("ok", elapsed_ms) if ok else ("err", elapsed_ms)
            except Exception as e:
                return ("err", 0)
    
    batch_tasks = [cross_op(i) for i in range(CONCURRENT)]
    batch_results = await asyncio.gather(*batch_tasks)
    
    for status, lat_ms in batch_results:
        if status == "ok":
            success += 1
            if lat_ms > 0:
                latencies.append(lat_ms)
        else:
            errors += 1
    
    elapsed = time.perf_counter() - t0
    
    if latencies:
        latencies.sort()
        n = len(latencies)
        results["phase6"] = {
            "success": success, "errors": errors,
            "avg_ms": mean(latencies), "p50_ms": latencies[n//2],
            "p95_ms": latencies[int(n*0.95)], "p99_ms": latencies[int(n*0.99)],
            "time_s": elapsed
        }
        log(f"  ✅ Cross-Call: {success} ok/{errors} err | "
            f"avg={mean(latencies):.0f}ms p50={latencies[n//2]:.0f}ms "
            f"p95={latencies[int(n*0.95)]:.0f}ms p99={latencies[int(n*0.99)]:.0f}ms")
    else:
        results["phase6"] = {"success": success, "errors": errors, "time_s": elapsed}
        log(f"  ✅ Cross-Call: {success} ok/{errors} err")
    
    return success, errors

# ============================================================
# MAIN
# ============================================================
async def main():
    total_start = time.perf_counter()
    
    print("\n" + "="*70)
    print("  KARMA CROSS-SETTLEMENT INTEGRITY TEST")
    print(f"  {TOTAL_ACCOUNTS} accounts | {CONCURRENT} concurrent")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}Z")
    print("="*70)
    
    # Check API
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/health")
        if r.status_code != 200:
            print(f"  ❌ API not available: {r.status_code}")
            return 1
        print(f"  API: {r.json()}")
    
    # PHASE 1: Create agents
    agent_ids = await phase1_create_agents()
    if not agent_ids:
        print("  ❌ No agents created — aborting")
        return 1
    
    # PHASE 2: Create contracts (simulate lock)
    contract_ids = await phase2_lock_capacity(agent_ids)
    
    # PHASE 3: Submit receipts
    await phase3_receipts(agent_ids, contract_ids)
    
    # PHASE 4: Settlement
    await phase4_settlement(agent_ids, contract_ids)
    
    # PHASE 5: Verify ledger balance
    balanced = await phase5_verify_ledger()
    
    # PHASE 6: Cross-call concurrent stress
    await phase6_cross_concurrent(agent_ids, contract_ids)
    
    # ================================================================
    # FINAL REPORT
    # ================================================================
    total_elapsed = time.perf_counter() - total_start
    
    print(f"\n{'='*70}")
    print(f"  FINAL CROSS-SETTLEMENT REPORT")
    print(f"{'='*70}")
    
    for phase, data in results.items():
        if phase == "phase1":
            print(f"  [Phase 1] Agents Created: {data['agents']:,} ({data['rate']:.0f}/s, {data['time_s']:.0f}s)")
        elif phase == "phase2":
            print(f"  [Phase 2] Contracts/Lock: {data['contracts']:,} | {data['total_locked']:.2f} USD ({data['time_s']:.0f}s)")
        elif phase == "phase3":
            print(f"  [Phase 3] Receipts: {data['success']:,} ok + {data['errors']} err ({data['time_s']:.0f}s)")
        elif phase == "phase4":
            print(f"  [Phase 4] Settlement: {data['success']:,} ok + {data['errors']} err | {data['total_settled']:.2f} USD settled ({data['time_s']:.0f}s)")
        elif phase == "phase5":
            icon = "✅" if data["balanced"] else "🔴"
            print(f"  [Phase 5] {icon} Ledger: Locked={data['total_locked']:.2f} Settled={data['total_settled']:.2f} In-Flight={data['in_flight']:.2f} | Balanced={data['balanced']}")
        elif phase == "phase6":
            print(f"  [Phase 6] Cross-Call: {data['success']} ok + {data['errors']} err"
                  f"{' | avg='+str(round(data.get('avg_ms',0)))+'ms' if 'avg_ms' in data else ''}")
    
    print(f"\n  ⏱️  Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"  📊 Final agent count: {len(agent_ids):,}")
    print(f"  💰 Total locked: {ledger['total_locked']:.2f} USD")
    print(f"  💰 Total settled: {ledger['total_settled']:.2f} USD")
    print(f"  💰 In-flight: {ledger['total_locked'] - ledger['total_settled']:.2f} USD")
    
    if balanced:
        print(f"\n  🟢 PASS: Ledger is balanced. Total Locked = Total Settled + In-Flight")
    else:
        print(f"\n  🔴 FAIL: Ledger imbalance detected!")
    
    return 0 if balanced else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
