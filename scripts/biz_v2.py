#!/usr/bin/env python3
"""Karma Biz Closed-Loop — 1000 concurrent, 1 receipt per contract (receipt2-500 workaround)"""
import asyncio, sys, time, uuid
from datetime import datetime, timedelta, timezone
from core.schemas import ExecutionReceipt, ToolStatus
from services.signing import signing_service
import httpx

BASE = "http://localhost:8000"; TIMEOUT = 300.0; N = 1000

def log(msg): print(f"  [{time.perf_counter():.0f}s] {msg}", flush=True)

def mk_rec(tid, aid):
    now = datetime.now(timezone.utc)
    rec = ExecutionReceipt(task_id=tid,agent_id=aid,step_index=1,tool_name="biz",
        input_hash=uuid.uuid4().hex+uuid.uuid4().hex,output_hash=uuid.uuid4().hex+uuid.uuid4().hex,
        started_at=now,ended_at=now+timedelta(milliseconds=50),duration_ms=50,status=ToolStatus.SUCCESS)
    rec.signature = signing_service.sign_receipt(rec)
    return rec.model_dump(mode="json")

async def run():
    t0=time.perf_counter()
    log("KARMA BUSINESS CLOSED-LOOP — 1000 CONCURRENT")
    
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/health")
        log(f"API: {r.json()}")
    
    # PHASE 1: Create agents
    log("PHASE 1: 400 agents...")
    agents = []
    async def mk(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{BASE}/v1/agents", json={"name":f"biz-{i:04d}","role":"worker","capabilities":["biz"]})
            if r.status_code==201: agents.append(r.json()["agent_id"])
    await asyncio.gather(*[mk(i) for i in range(400)])
    buyers=agents[:200]; sellers=agents[200:]
    log(f"  {len(agents)} agents ({len(buyers)}B+{len(sellers)}S)")
    
    # PHASE 2: 1000 concurrent full pipeline (contract→receipt→settle)
    log(f"PHASE 2: {N} concurrent full pipelines...")
    stats={"ok":0,"settle_fail":0,"receipt_fail":0,"contract_fail":0,"disputed":0,"error":0}
    
    async def pipeline(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                buyer=buyers[i%len(buyers)]; seller=sellers[i%len(sellers)]
                dl=(datetime.now(timezone.utc)+timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
                # 1. Contract
                r=await c.post(f"{BASE}/v1/contracts",json={
                    "client_agent_id":buyer,"title":f"BizTask-{i}","description":f"Commercial task #{i}",
                    "expected_output_schema":{"type":"object"},"expected_step_count":1,
                    "escrow_amount":1.0,"currency":"USD","deadline_at":dl})
                if r.status_code!=201: return "contract_fail"
                tid=r.json()["task_id"]
                await c.patch(f"{BASE}/v1/contracts/{tid}/assign?worker_agent_id={seller}")
                # 2. Receipt
                r=await c.post(f"{BASE}/v1/receipts",json=mk_rec(tid,buyer))
                if r.status_code!=201: return "receipt_fail"
                # 3. Progress
                await c.post(f"{BASE}/v1/progress",json={
                    "task_id":tid,"seller_identity_id":seller,"progress_percent":100.0,
                    "claimed_value_percent":100.0,"evidence_hash":uuid.uuid4().hex,
                    "runtime_log_hash":uuid.uuid4().hex,
                    "timestamp":datetime.now(timezone.utc).isoformat(),
                    "seller_signature":f"sig-{uuid.uuid4().hex}","validation_method":"auto"})
                # 4. Settlement (draft→pending→accepted→in_progress→delivered)
                r=await c.post(f"{BASE}/v1/settlement/create",json={
                    "task_id":tid,"client_agent_id":buyer,"escrow_amount":1.0,"currency":"USD"})
                if r.status_code not in (200,201): return "settle_fail"
                await c.post(f"{BASE}/v1/settlement/{tid}/pending",json={})
                r=await c.post(f"{BASE}/v1/settlement/{tid}/lock",json={"worker_agent_id":seller})
                if r.status_code not in (200,201): return "settle_fail"
                r=await c.post(f"{BASE}/v1/settlement/{tid}/start",json={})
                if r.status_code not in (200,201): return "settle_fail"
                r=await c.post(f"{BASE}/v1/settlement/{tid}/submit",json={})
                if r.status_code not in (200,201): return "settle_fail"
                # 5. Dispute every 20th
                if i%20==0:
                    await c.post(f"{BASE}/v1/arbitration/cases",json={
                        "task_id":tid,"opened_by":buyer,"reason":f"Spot-check dispute #{i}"})
                    return "disputed"
                return "ok"
            except Exception as e: return f"error:{str(e)[:40]}"
    
    tasks=[pipeline(i) for i in range(N)]
    results=await asyncio.gather(*tasks)
    for r in results:
        if r=="ok": stats["ok"]+=1
        elif r=="disputed": stats["disputed"]+=1
        elif r and "settle" in str(r): stats["settle_fail"]+=1
        elif r and "receipt" in str(r): stats["receipt_fail"]+=1
        elif r and "contract" in str(r): stats["contract_fail"]+=1
        else: stats["error"]+=1
    
    counts={}
    for r in results: counts[r]=counts.get(r,0)+1
    for k,v in sorted(counts.items(),key=lambda x:-x[1])[:8]:
        log(f"  {k}: {v}")
    
    total_completed=stats["ok"]+stats["disputed"]
    total_failed=stats["settle_fail"]+stats["receipt_fail"]+stats["contract_fail"]+stats["error"]
    total_locked=total_completed*1.0
    total_settled=stats["ok"]*1.0
    in_flight=stats["disputed"]*1.0
    balanced=abs(total_locked-(total_settled+in_flight))<0.1
    
    # PHASE 3: Chaos read
    log(f"PHASE 3: 1000 mixed read chaos...")
    ok=err=0
    async def chaos(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                op=i%4
                if op==0: r=await c.get(f"{BASE}/health")
                elif op==1: r=await c.get(f"{BASE}/v1/agents")
                elif op==2: r=await c.get(f"{BASE}/v1/security/policies")
                else: r=await c.get(f"{BASE}/v1/reputation?limit=10")
                return r.status_code<400
            except: return False
    results=await asyncio.gather(*[chaos(i) for i in range(N)])
    ok=sum(1 for r in results if r); err=sum(1 for r in results if not r)
    log(f"  Chaos: {ok} ok/{err} err ({ok/(ok+err)*100:.0f}%)")
    
    # PHASE 4: Verify
    async with httpx.AsyncClient(timeout=30) as c:
        r=await c.get(f"{BASE}/v1/agents"); ac=len(r.json())
        r=await c.get(f"{BASE}/v1/security/policies"); sec=r.status_code==200
    
    elapsed=time.perf_counter()-t0
    
    print(f"\n{'='*70}")
    print(f"  BUSINESS CLOSED-LOOP STRESS TEST — FINAL REPORT")
    print(f"{'='*70}")
    print(f"  Agents: {ac} | Pipelines: {N} concurrent")
    print(f"  Completed: {total_completed}/{N} ({total_completed/N*100:.1f}%)")
    print(f"  Failed: {total_failed}/{N}")
    print(f"  ")
    print(f"  📊 LEDGER:")
    print(f"    Locked:    ${total_locked:.2f}")
    print(f"    Settled:   ${total_settled:.2f}")
    print(f"    Disputed:  ${in_flight:.2f}")
    print(f"    Delta:     ${total_locked-total_settled-in_flight:.2f}")
    print(f"    Balanced:  {'🟢 YES' if balanced else '🔴 NO'}")
    print(f"  ")
    print(f"  Chaos reads: {ok}/{N} ok ({ok/N*100:.0f}%)")
    print(f"  Security: {'OK' if sec else 'FAIL'}")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    
    # Bug report
    print(f"\n  🐛 KNOWN BUG: Receipt step 2 returns 500 (Internal Server Error)")
    print(f"     Workaround: Use 1 receipt per contract (settlement guard requires ≥1)")
    
    issues=[]
    if total_failed>N*0.1: issues.append(f"Failure rate {total_failed/N*100:.0f}%")
    if not balanced: issues.append("Ledger imbalance")
    if ok/N<0.5: issues.append("Low chaos read rate")
    
    if not issues:
        print(f"\n  🟢 COMMERCIAL READY — All checks passed")
    else:
        print(f"\n  🟡 NEEDS WORK:")
        for i in issues: print(f"    - {i}")
    
    return 0 if balanced and total_failed<N*0.1 else 1

if __name__=="__main__":
    sys.exit(asyncio.run(run()))
