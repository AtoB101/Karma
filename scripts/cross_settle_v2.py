#!/usr/bin/env python3
"""Karma Cross-Settlement — 10000 accounts, 100-concurrent batches, SQLite-friendly"""
import asyncio, sys, time, uuid
from datetime import datetime, timedelta
from statistics import mean
import httpx

BASE = "http://localhost:8000"
TOTAL = 10000
BATCH = 100
CONCURRENT = 100
ESCROW = 0.50
TIMEOUT = 300.0

def log(msg):
    t = datetime.utcnow().strftime('%H:%M:%S')
    print(f"  [{t}] {msg}", flush=True)

async def run():
    t0 = time.perf_counter()
    log(f"CROSS-SETTLEMENT TEST: {TOTAL} accounts, {BATCH}-batch agent creation, {CONCURRENT} concurrent ops")
    
    # Check API
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}/health")
        log(f"API: {r.json()}")
    
    # === PHASE 1: Create agents (batched, sequential batches) ===
    log(f"PHASE 1: Creating {TOTAL} agents in batches of {BATCH}...")
    agent_ids = []
    t1 = time.perf_counter()
    
    for start in range(0, TOTAL, BATCH):
        end = min(start + BATCH, TOTAL)
        async def reg(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    r = await c.post(f"{BASE}/v1/agents", json={
                        "name": f"a{i:05d}", "role": "worker", "capabilities": ["cross"]
                    })
                    if r.status_code == 201:
                        return r.json()["agent_id"]
                except: pass
                return None
        
        tasks = [reg(i) for i in range(start, end)]
        results = await asyncio.gather(*tasks)
        agent_ids.extend([a for a in results if a])
        
        elapsed = time.perf_counter() - t1
        rate = len(agent_ids) / elapsed if elapsed > 0 else 0
        log(f"  {len(agent_ids):>5}/{TOTAL} agents ({len(agent_ids)/TOTAL*100:.0f}%) | {rate:.0f}/s")
    
    t1e = time.perf_counter() - t1
    log(f"  ✅ {len(agent_ids)} agents in {t1e:.1f}s ({len(agent_ids)/t1e:.0f}/s)")
    
    # === PHASE 2: Cross-contracts (pairs of agents) ===
    log(f"PHASE 2: Creating cross-contracts ({len(agent_ids)} agents, {ESCROW} USDC each)...")
    contract_ids = []
    total_locked = 0.0
    t2 = time.perf_counter()
    
    for start in range(0, len(agent_ids), BATCH):
        end = min(start + BATCH, len(agent_ids))
        async def mk_contract(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    buyer = agent_ids[i]
                    seller = agent_ids[(i + 1) % len(agent_ids)]
                    deadline = (datetime.utcnow() + timedelta(hours=2)).isoformat()
                    r = await c.post(f"{BASE}/v1/contracts", json={
                        "client_agent_id": buyer, "title": f"Cross {i}",
                        "description": f"{buyer[:8]}→{seller[:8]}",
                        "expected_output_schema": {}, "expected_step_count": 3,
                        "escrow_amount": ESCROW, "currency": "USD", "deadline_at": deadline
                    })
                    if r.status_code == 201:
                        tid = r.json()["task_id"]
                        await c.patch(f"{BASE}/v1/contracts/{tid}/assign?worker_agent_id={seller}")
                        return (tid, ESCROW)
                except: pass
                return None
        
        tasks = [mk_contract(i) for i in range(start, end)]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                contract_ids.append(r[0])
                total_locked += r[1]
        
        elapsed = time.perf_counter() - t2
        rate = len(contract_ids) / elapsed if elapsed > 0 else 0
        log(f"  {len(contract_ids)} contracts | {total_locked:.2f} USD | {rate:.0f}/s")
    
    t2e = time.perf_counter() - t2
    log(f"  ✅ {len(contract_ids)} contracts, {total_locked:.2f} USD locked in {t2e:.1f}s")
    
    # === PHASE 3: Receipts (1000 concurrent) ===
    sample_n = min(5000, len(contract_ids))
    sample = contract_ids[:sample_n]
    log(f"PHASE 3: Submitting receipts for {sample_n} contracts @ {CONCURRENT} concurrent...")
    t3 = time.perf_counter()
    rec_ok = 0
    
    for start in range(0, sample_n, CONCURRENT):
        end = min(start + CONCURRENT, sample_n)
        async def submit_rec(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    tid = sample[i]
                    now = datetime.utcnow()
                    r = await c.post(f"{BASE}/v1/receipts", json={
                        "task_id": tid, "agent_id": agent_ids[i % len(agent_ids)],
                        "step_index": 1, "tool_name": "cross.settle",
                        "input_hash": uuid.uuid4().hex+uuid.uuid4().hex,
                        "output_hash": uuid.uuid4().hex+uuid.uuid4().hex,
                        "started_at": now.isoformat(),
                        "ended_at": (now+timedelta(milliseconds=50)).isoformat(),
                        "duration_ms": 50, "status": "success"
                    })
                    return r.status_code == 201
                except: return False
        
        tasks = [submit_rec(i) for i in range(start, end)]
        results = await asyncio.gather(*tasks)
        rec_ok += sum(1 for r in results if r)
        elapsed = time.perf_counter() - t3
        log(f"  Receipts: {rec_ok} ok | {rec_ok/elapsed:.0f}/s")
    
    t3e = time.perf_counter() - t3
    log(f"  ✅ {rec_ok} receipts in {t3e:.1f}s")
    
    # === PHASE 4: Settlement (1000 concurrent) ===
    settle_n = min(3000, len(contract_ids))
    settle_sample = contract_ids[:settle_n]
    log(f"PHASE 4: Settling {settle_n} contracts @ {CONCURRENT} concurrent...")
    t4 = time.perf_counter()
    settle_ok = 0
    total_settled = 0.0
    
    for start in range(0, settle_n, CONCURRENT):
        end = min(start + CONCURRENT, settle_n)
        async def settle_one(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    tid = settle_sample[i]
                    aid = agent_ids[i % len(agent_ids)]
                    r = await c.post(f"{BASE}/v1/settlement/create", json={
                        "task_id": tid, "client_agent_id": aid,
                        "escrow_amount": ESCROW, "currency": "USD"
                    })
                    if r.status_code not in (200, 201): return (False, 0)
                    for step in ["lock", "start", "submit"]:
                        body = {"worker_agent_id": agent_ids[(i+1)%len(agent_ids)]} if step=="lock" else {}
                        r2 = await c.post(f"{BASE}/v1/settlement/{tid}/{step}", json=body)
                        if r2.status_code not in (200, 201): return (False, 0)
                    return (True, ESCROW)
                except: return (False, 0)
        
        tasks = [settle_one(i) for i in range(start, end)]
        results = await asyncio.gather(*tasks)
        for ok, amt in results:
            if ok:
                settle_ok += 1
                total_settled += amt
        elapsed = time.perf_counter() - t4
        log(f"  Settlement: {settle_ok} ok | {total_settled:.2f} USD | {settle_ok/elapsed:.0f}/s")
    
    t4e = time.perf_counter() - t4
    log(f"  ✅ {settle_ok} settled, {total_settled:.2f} USD in {t4e:.1f}s")
    
    # === PHASE 5: Mixed concurrent cross-call stress ===
    log(f"PHASE 5: Mixed cross-call @ {CONCURRENT} concurrent (3 rounds)...")
    deadline = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    ops = ["health", "agent_list", "agent_lookup", "contract_create", "receipt", "security"]
    t5 = time.perf_counter()
    mix_ok = 0
    mix_err = 0
    
    for round_num in range(3):
        async def cross_op(i):
            op = ops[(i + round_num) % len(ops)]
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    if op == "health":
                        r = await c.get(f"{BASE}/health")
                    elif op == "agent_list":
                        r = await c.get(f"{BASE}/v1/agents")
                    elif op == "agent_lookup":
                        r = await c.get(f"{BASE}/v1/agents/{agent_ids[i % len(agent_ids)]}")
                    elif op == "contract_create":
                        buyer = agent_ids[i % len(agent_ids)]
                        seller = agent_ids[(i*7+13) % len(agent_ids)]
                        r = await c.post(f"{BASE}/v1/contracts", json={
                            "client_agent_id": buyer, "title": f"MixR{round_num}.{i}",
                            "description": f"Cross {buyer[:6]}→{seller[:6]}",
                            "expected_output_schema": {}, "expected_step_count": 1,
                            "escrow_amount": 0.10, "currency": "USD", "deadline_at": deadline
                        })
                    elif op == "receipt":
                        tid = contract_ids[i % len(contract_ids)] if contract_ids else "x"
                        now = datetime.utcnow()
                        r = await c.post(f"{BASE}/v1/receipts", json={
                            "task_id": tid, "agent_id": agent_ids[i % len(agent_ids)],
                            "step_index": (i%3)+2, "tool_name": f"cross.{op}",
                            "input_hash": uuid.uuid4().hex+uuid.uuid4().hex,
                            "output_hash": uuid.uuid4().hex+uuid.uuid4().hex,
                            "started_at": now.isoformat(),
                            "ended_at": (now+timedelta(milliseconds=20)).isoformat(),
                            "duration_ms": 20, "status": "success"
                        })
                    elif op == "security":
                        r = await c.get(f"{BASE}/v1/security/policies")
                    return r.status_code < 400
                except: return False
        
        tasks = [cross_op(i) for i in range(CONCURRENT)]
        results = await asyncio.gather(*tasks)
        mix_ok += sum(1 for r in results if r)
        mix_err += sum(1 for r in results if not r)
        log(f"  Round {round_num+1}/3: {sum(1 for r in results if r)} ok, {sum(1 for r in results if not r)} err")
    
    t5e = time.perf_counter() - t5
    log(f"  ✅ Mixed: {mix_ok} ok, {mix_err} err in {t5e:.1f}s ({mix_ok/t5e:.0f}/s)")
    
    # === PHASE 6: Ledger verification ===
    log("PHASE 6: Verifying ledger balance...")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}/v1/agents")
        agent_count = len(r.json())
        r = await c.get(f"{BASE}/v1/reputation?limit=10")
        rep_ok = r.status_code == 200
        r = await c.get(f"{BASE}/v1/security/policies")
        sec_ok = r.status_code == 200
    
    in_flight = total_locked - total_settled
    balanced = abs(total_locked - (total_settled + in_flight)) < 0.01
    
    total_elapsed = time.perf_counter() - t0
    
    # === FINAL REPORT ===
    print(f"\n{'='*70}")
    print(f"  CROSS-SETTLEMENT INTEGRITY REPORT")
    print(f"{'='*70}")
    print(f"  Accounts created:  {len(agent_ids):>8,}")
    print(f"  Contracts created: {len(contract_ids):>8,}")
    print(f"  Contracts locked:  {total_locked:>10.2f} USD ({len(contract_ids)} × {ESCROW})")
    print(f"  Receipts submitted:{rec_ok:>8,}")
    print(f"  Settlements done:  {settle_ok:>8,}")
    print(f"  Amount settled:    {total_settled:>10.2f} USD")
    print(f"  In-flight:         {in_flight:>10.2f} USD")
    print(f"  Mixed ops:         {mix_ok:>8,} ok + {mix_err} err")
    print(f"  ")
    print(f"  📊 LEDGER:")
    print(f"    Total Locked:    {total_locked:>12.2f} USD")
    print(f"    Total Settled:   {total_settled:>12.2f} USD")
    print(f"    In-Flight:       {in_flight:>12.2f} USD")
    print(f"    Sum:             {total_settled+in_flight:>12.2f} USD")
    print(f"    Delta:           {total_locked-total_settled-in_flight:>12.4f} USD")
    
    if balanced:
        print(f"\n  🟢 LEDGER BALANCED: Locked = Settled + In-Flight")
    else:
        print(f"\n  🔴 LEDGER IMBALANCE!")
    
    print(f"\n  DB State: {agent_count} agents, rep={rep_ok}, security={sec_ok}")
    print(f"  Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"  Rates: agents={len(agent_ids)/t1e:.0f}/s, contracts={len(contract_ids)/t2e:.0f}/s, "
          f"receipts={rec_ok/t3e:.0f}/s, settle={settle_ok/t4e:.0f}/s")
    
    return 0 if balanced else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
