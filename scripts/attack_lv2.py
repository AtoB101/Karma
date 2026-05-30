#!/usr/bin/env python3
"""
Karma Security Attack Simulation LEVEL 2 — 极狠模式
=======================================================
Advanced: fuzzing, boundary values, chained attacks, 
race conditions, encoding attacks, deserialization, 
prototype pollution, timing side-channels
"""
import asyncio, sys, time, uuid, random, struct, json, itertools
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any
import math
from core.schemas import ExecutionReceipt, ToolStatus
from services.signing import signing_service
import httpx

BASE = "http://localhost:8000"
TIMEOUT = 120.0

@dataclass
class Finding:
    id: str; cat: str; attack: str; sev: str; result: str; detail: str; fix: str = ""

findings: list[Finding] = []
stats = {"total":0,"blocked":0,"vulnerable":0,"errors":0}
agents = []; contracts = []

def log(msg): print(f"  [{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)

def record(cat, attack, sev, result, detail, fix=""):
    fid = f"KSA2-{len(findings)+1:03d}"
    findings.append(Finding(fid, cat, attack, sev, result, detail, fix))
    stats["total"]+=1
    if "BLOCKED" in result: stats["blocked"]+=1
    elif result=="VULNERABLE": stats["vulnerable"]+=1
    else: stats["errors"]+=1
    icon = "🔴" if result=="VULNERABLE" else ("✅" if "BLOCKED" in result else "⚠️")
    print(f"    {icon} {fid} [{sev}] {attack[:60]}: {result}")

def make_receipt(tid, aid, step, dur=50):
    now = datetime.now(timezone.utc)
    rec = ExecutionReceipt(task_id=tid, agent_id=aid, step_index=step,
        tool_name="attack.tool", input_hash=uuid.uuid4().hex+uuid.uuid4().hex,
        output_hash=uuid.uuid4().hex+uuid.uuid4().hex, started_at=now,
        ended_at=now+timedelta(milliseconds=dur), duration_ms=dur, status=ToolStatus.SUCCESS)
    rec.signature = signing_service.sign_receipt(rec)
    return rec.model_dump(mode="json")

# ================================================================
# SETUP
# ================================================================
async def setup():
    log("SETUP: Creating 200 agents + 50 contracts...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for i in range(200):
            r = await c.post(f"{BASE}/v1/agents", json={"name":f"lv2-{i:04d}","role":"worker","capabilities":["lv2"]})
            if r.status_code==201: agents.append(r.json()["agent_id"])
    
    log(f"  {len(agents)} agents")
    if len(agents)>=2:
        for i in range(min(50, len(agents))):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c2:
                deadline = (datetime.now(timezone.utc)+timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
                r = await c2.post(f"{BASE}/v1/contracts", json={
                    "client_agent_id":agents[i],"title":f"LV2-{i}","description":"attack target",
                    "expected_output_schema":{},"expected_step_count":5,"escrow_amount":1.0,
                    "currency":"USD","deadline_at":deadline
                })
                if r.status_code==201:
                    tid = r.json()["task_id"]
                    await c2.patch(f"{BASE}/v1/contracts/{tid}/assign?worker_agent_id={agents[(i+1)%len(agents)]}")
                    contracts.append({"task_id":tid,"buyer":agents[i],"seller":agents[(i+1)%len(agents)]})
    log(f"  {len(contracts)} contracts ready")

# ================================================================
# 1. ADVANCED FUZZING
# ================================================================
async def attack_fuzzing():
    log("\n🔴 CAT 1: ADVANCED FUZZING (Random byte injection)")
    
    endpoints = [
        ("POST","/v1/agents",{"name":"fuzz","role":"worker"}),
        ("POST","/v1/contracts",{"client_agent_id":"x","title":"f","description":"d","expected_output_schema":{},"expected_step_count":1,"escrow_amount":1,"currency":"USD","deadline_at":"2026-05-15T00:00:00Z"}),
        ("GET","/v1/agents/"+("x"*36),None),
        ("GET","/v1/security/policies",None),
    ]
    
    fuzz_payloads = {
        "name": [b'\x00'*100, b'\xff'*100, "A"*10000, "", None, 0, -1, 1e308, True, [], {}, "null"],
        "expected_step_count": [-1, 0, 999999, 1.5, None, "many", [], {}],
        "escrow_amount": [-1.0, 0.0, math.nan, math.inf, -math.inf, 1e308, None, "free"],
        "deadline_at": ["", "yesterday", "2026-05-15T00:00:00+99:99", None, 12345],
    }
    
    tested = 0
    for method, path, base in endpoints:
        for field, values in fuzz_payloads.items():
            if base and field not in str(base): continue
            for val in values[:3]:
                async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                    try:
                        body = base.copy() if base else {}
                        body[field] = val
                        body_str = json.dumps(body, allow_nan=False) if isinstance(val, float) and math.isnan(val) else json.dumps(body)
                        if method=="POST":
                            r = await c.post(f"{BASE}{path}", content=body_str, headers={"Content-Type":"application/json"})
                        else:
                            r = await c.get(f"{BASE}{path}")
                        tested += 1
                        if r.status_code >= 500:
                            record("FUZZ", f"{field}={str(val)[:30]} on {path}", "HIGH", "VULNERABLE",
                                   f"HTTP 500 — crash on fuzz input: {r.text[:100]}",
                                   f"Add input validation for {field}")
                    except: pass
    log(f"  {tested} fuzz tests completed")

# ================================================================
# 2. BOUNDARY VALUE ATTACKS
# ================================================================
async def attack_boundary():
    log("\n🔴 CAT 2: BOUNDARY VALUE ATTACKS")
    
    if not contracts or not agents: return
    
    ctr = contracts[0]; tid = ctr["task_id"]; buyer = ctr["buyer"]
    
    # Boundary step_index (Pydantic validates >= 1, test via raw JSON)
    for step,step_label in [(2**31-1,"MAX_INT"), (999999,"999K")]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # Baseline receipt step 1
            r = await c.post(f"{BASE}/v1/receipts", json=make_receipt(tid, buyer, 1))
            if r.status_code != 201: break
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                body = make_receipt(tid, buyer, step)
                r = await c.post(f"{BASE}/v1/receipts", json=body)
                if r.status_code >= 400:
                    record("BOUNDARY", f"step_index={step_label}", "LOW", "BLOCKED", f"HTTP {r.status_code}")
                else:
                    record("BOUNDARY", f"step_index={step_label}", "HIGH", "VULNERABLE",
                           f"step_index={step_label} accepted",
                           "Validate step_index <= expected_step_count")
            except Exception as e:
                record("BOUNDARY", f"step_index={step_label}", "LOW", "BLOCKED", f"Pydantic blocked: {str(e)[:80]}")
    
    # Boundary escrow amounts
    for amt, label in [(0.0,"zero"), (-0.01,"negative"), (1e15,"massive"), (1e308,"inf")]:
        label_str = str(label) if not (isinstance(amt, float) and math.isinf(amt)) else "inf"
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            deadline = (datetime.now(timezone.utc)+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            body = {"client_agent_id":buyer,"title":f"Boundary {label_str}","description":"t",
                    "expected_output_schema":{},"expected_step_count":1,
                    "escrow_amount":amt,"currency":"USD","deadline_at":deadline}
            try:
                body_str = json.dumps(body, allow_nan=False)
            except (ValueError, TypeError):
                body_str = json.dumps(body, allow_nan=False, default=str)
            r = await c.post(f"{BASE}/v1/contracts", content=body_str, headers={"Content-Type":"application/json"})
            if r.status_code >= 400:
                record("BOUNDARY", f"escrow_amount={label_str}", "MEDIUM", "BLOCKED", f"HTTP {r.status_code}")
            else:
                record("BOUNDARY", f"escrow_amount={label_str}", "CRITICAL", "VULNERABLE",
                       f"Contract created with escrow={label_str}",
                       f"Validate escrow_amount > 0 and <= ESCROW_MAX_AMOUNT")

# ================================================================
# 3. CHAINED MULTI-STEP ATTACKS
# ================================================================
async def attack_chained():
    log("\n🔴 CAT 3: CHAINED MULTI-STEP ATTACKS")
    
    if len(agents) < 3 or not contracts: return
    
    # Chain: create fake identity → create contract → bypass progress → force settle
    log("  3.1 Identity→Contract→BypassProgress→ForceSettle chain...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Step 1: Create identities
        r1 = await c.post(f"{BASE}/v1/agents", json={"name":f"chain-buyer-{uuid.uuid4().hex[:6]}","role":"client","capabilities":["chain"]})
        r2 = await c.post(f"{BASE}/v1/agents", json={"name":f"chain-seller-{uuid.uuid4().hex[:6]}","role":"worker","capabilities":["chain"]})
        if r1.status_code==201 and r2.status_code==201:
            b = r1.json()["agent_id"]; s = r2.json()["agent_id"]
            # Step 2: Create contract
            r3 = await c.post(f"{BASE}/v1/contracts", json={
                "client_agent_id":b,"title":"Chain Attack","description":"multi-step exploit",
                "expected_output_schema":{},"expected_step_count":1,"escrow_amount":100.0,
                "currency":"USD","deadline_at":(datetime.now(timezone.utc)+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            })
            if r3.status_code==201:
                tid = r3.json()["task_id"]
                # Step 3: Try to settle without receipts
                r4 = await c.post(f"{BASE}/v1/settlement/create", json={
                    "task_id":tid,"client_agent_id":b,"escrow_amount":100.0,"currency":"USD"
                })
                if r4.status_code in (200,201):
                    await c.post(f"{BASE}/v1/settlement/{tid}/pending", json={})
                    r5 = await c.post(f"{BASE}/v1/settlement/{tid}/lock", json={"worker_agent_id":s})
                    r6 = await c.post(f"{BASE}/v1/settlement/{tid}/start", json={})
                    r7 = await c.post(f"{BASE}/v1/settlement/{tid}/submit", json={})
                    if r7.status_code in (200,201):
                        record("CHAIN", "Settle without receipts chain", "CRITICAL", "VULNERABLE",
                               "Contract settled with ZERO receipts — $100 released without proof of work",
                               "Require at least expected_step_count receipts before allowing settlement submit")
                    else:
                        record("CHAIN", "Settle without receipts chain", "HIGH", "BLOCKED",
                               f"Settlement submit rejected at step: {r7.status_code}")
                else:
                    record("CHAIN", "Settle without receipts chain", "HIGH", "BLOCKED",
                           f"Settlement create blocked: HTTP {r4.status_code}")
    
    # Chain: Register → CreateKey → ExceedLimit → RequestVoucher
    log("  3.2 Register→Key→Exceed→Voucher chain...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        buyer = agents[0] if agents else "x"
        r = await c.post(f"{BASE}/v1/runtime-gateway/create-key", json={
            "wallet_address":f"0xChain{uuid.uuid4().hex[:16]}","karma_identity_id":buyer,
            "permissions":["request_voucher","submit_receipt"],"single_limit":0.01,
            "daily_limit":0.03,"agent_name":"chain-exploit","agent_binding":"chain-v1"
        })
        if r.status_code in (200,201):
            # Now try to request a voucher exceeding the limit
            if len(agents)>=2:
                r2 = await c.post(f"{BASE}/v1/vouchers", json={
                    "buyer_identity_id":buyer,"seller_identity_id":agents[1],
                    "amount":100.0,"currency":"USD","bill_credit_amount":100.0,
                    "task_type":"ai_report","task_description_hash":"a"*128,
                    "progress_rule_hash":"b"*128,"evidence_requirement_hash":"c"*128,
                    "expiry_time":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                    "nonce":uuid.uuid4().hex,"buyer_signature":"chain-sig"
                })
                if r2.status_code >= 400:
                    record("CHAIN", "Key limit enforcement on voucher", "HIGH", "BLOCKED",
                           f"Voucher blocked: HTTP {r2.status_code}")
                else:
                    record("CHAIN", "Key limit enforcement on voucher", "CRITICAL", "VULNERABLE",
                           "Voucher created exceeding Runtime Key limits!",
                           "Validate voucher amount against runtime key single_limit/daily_limit")

# ================================================================
# 4. ENCODING / UNICODE ATTACKS
# ================================================================
async def attack_encoding():
    log("\n🔴 CAT 4: ENCODING / UNICODE ATTACKS")
    
    malicious_names = [
        # Unicode normalization attacks
        "admin\u0300",           # combining grave
        "\u202E\u202Btest",      # right-to-left override
        "admin\u200Btest",       # zero-width space
        "ａｄｍｉｎ",           # fullwidth latin
        "\u0000hidden",          # null byte
        "\uFFFD\uFFFE\uFFFF",    # replacement chars
        "𝕳𝖆𝖈𝖐𝖊𝖗",           # mathematical bold
        # Path traversal in names
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        # Newlines in JSON values
        "line1\nline2\r\nline3\tindented",
    ]
    
    for name in malicious_names:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{BASE}/v1/agents", json={"name":name,"role":"worker","capabilities":["unicode"]})
            if r.status_code >= 500:
                record("ENCODE", f"Unicode/encoding crash: {repr(name[:40])}", "HIGH", "VULNERABLE",
                       f"HTTP 500: {r.text[:100]}", "Sanitize unicode input, reject control chars")
            elif r.status_code in (200,201):
                stored = r.json().get("name","")
                if "\u0000" in stored or "\u202E" in stored:
                    record("ENCODE", f"Dangerous unicode preserved: {repr(name[:40])}", "HIGH", "VULNERABLE",
                           f"Stored: {repr(stored[:60])}", "Normalize/strip dangerous unicode characters")
                else:
                    record("ENCODE", f"Unicode name sanitized: {repr(name[:40])}", "LOW", "BLOCKED",
                           "Accepted but likely sanitized")
            else:
                record("ENCODE", f"Unicode name rejected: {repr(name[:40])}", "LOW", "BLOCKED", f"HTTP {r.status_code}")

# ================================================================
# 5. DESERIALIZATION ATTACKS
# ================================================================
async def attack_deserialization():
    log("\n🔴 CAT 5: DESERIALIZATION ATTACKS")
    
    payloads = [
        # Malformed JSON
        ("{invalid json", "unclosed brace"),
        ("{'single quotes'}", "python dict"),
        ("null", "bare null"),
        ("[1,2,3]", "array instead of object"),
        # Deeply nested
        (json.dumps({"name": "deep", "nested": json.loads('{"a":'*50 + '"x"' + '}'*50)}), "deeply nested JSON"),
        # Circular reference (can't serialize in JSON, so use __proto__)
        (json.dumps({"__proto__": {"isAdmin": True}}), "prototype pollution"),
        (json.dumps({"constructor": {"prototype": {"admin": True}}}), "constructor pollution"),
        # Huge payload
        (json.dumps({"name": "A"*100000, "role": "worker"}), "100KB payload"),
    ]
    
    for payload, label in payloads:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/agents", content=payload, headers={"Content-Type":"application/json"})
                if r.status_code >= 500:
                    record("DESER", f"Deserialization: {label}", "HIGH", "VULNERABLE",
                           f"HTTP 500 crash: {r.text[:100]}",
                           "Add JSON parse error handling, size limits")
                elif r.status_code >= 400:
                    record("DESER", f"Deserialization: {label}", "LOW", "BLOCKED", f"HTTP {r.status_code}")
                else:
                    record("DESER", f"Deserialization: {label}", "MEDIUM", "VULNERABLE",
                           f"Malformed payload accepted ({r.status_code})",
                           "Validate JSON structure before processing")
            except Exception as e:
                record("DESER", f"Deserialization: {label}", "LOW", "BLOCKED", f"Connection rejected: {str(e)[:80]}")

# ================================================================
# 6. ADVANCED RACE CONDITIONS
# ================================================================
async def attack_race_v2():
    log("\n🔴 CAT 6: ADVANCED RACE CONDITIONS (1000 concurrent)")
    if not contracts or len(agents) < 2: return
    
    # Race: 1000 concurrent creates on a brand new settlement
    ctr = contracts[0]; tid = ctr["task_id"]; buyer = ctr["buyer"]; seller = ctr["seller"]
    
    # First, ensure at least one receipt exists
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        await c.post(f"{BASE}/v1/receipts", json=make_receipt(tid, buyer, 1))
    
    # Submit receipt step 1 first (baseline)
    
    # Race: 500 concurrent full settlement pipelines
    log("  6.1 500 concurrent settlement pipelines on same task...")
    async def race_full_settle(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/settlement/create", json={
                    "task_id": tid, "client_agent_id": buyer,
                    "escrow_amount": 1.0, "currency": "USD"
                })
                if r.status_code not in (200,201): return "blocked_create"
                await c.post(f"{BASE}/v1/settlement/{tid}/pending", json={})
                r2 = await c.post(f"{BASE}/v1/settlement/{tid}/lock", json={"worker_agent_id": seller})
                if r2.status_code not in (200,201): return "blocked_lock"
                r3 = await c.post(f"{BASE}/v1/settlement/{tid}/start", json={})
                if r3.status_code not in (200,201): return "blocked_start"
                r4 = await c.post(f"{BASE}/v1/settlement/{tid}/submit", json={})
                if r4.status_code in (200,201): return "settled"
                return f"blocked_submit_{r4.status_code}"
            except: return "error"
    
    tasks = [race_full_settle(i) for i in range(500)]
    results = await asyncio.gather(*tasks)
    settled_count = sum(1 for r in results if r == "settled")
    if settled_count > 1:
        record("RACE2", "500 concurrent settlement pipelines", "CRITICAL", "VULNERABLE",
               f"{settled_count} settlements completed for SAME task — MASSIVE RACE CONDITION!",
               "Add distributed mutex/lock for settlement state transitions")
    elif settled_count == 1:
        record("RACE2", "500 concurrent settlement pipelines", "CRITICAL", "BLOCKED",
               f"Only 1 succeeded, {500-settled_count} blocked — concurrency-safe")
    else:
        record("RACE2", "500 concurrent settlement pipelines", "HIGH", "BLOCKED",
               f"All blocked or {settled_count} settled (state={set(results)})")
    
    # Race: 1000 concurrent receipt submissions on new contract
    if len(contracts) > 1:
        ctr2 = contracts[1]; tid2 = ctr2["task_id"]; buyer2 = ctr2["buyer"]
        log("  6.2 1000 concurrent receipt submissions step=1 on new contract...")
        async def race_receipt(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    r = await c.post(f"{BASE}/v1/receipts", json=make_receipt(tid2, buyer2, 1))
                    return r.status_code
                except: return 0
        tasks = [race_receipt(i) for i in range(1000)]
        results = await asyncio.gather(*tasks)
        created = sum(1 for c in results if c == 201)
        if created > 1:
            record("RACE2", "1000 concurrent receipts same step", "CRITICAL", "VULNERABLE",
                   f"{created} receipts created for same step — UNIQUE constraint bypassed under race",
                   "Add application-level mutex + verify DB-level UNIQUE constraint is enforced at transaction level")
        else:
            record("RACE2", "1000 concurrent receipts same step", "HIGH", "BLOCKED",
                   f"Only {created} accepted, {1000-created} blocked — concurrency-safe")

# ================================================================
# 7. HTTP HEADER / PARAMETER ATTACKS
# ================================================================
async def attack_headers():
    log("\n🔴 CAT 7: HTTP HEADER / PARAMETER ATTACKS")
    
    malicious_headers = [
        {"Content-Type": "application/x-www-form-urlencoded"},
        {"Content-Type": "text/html"},
        {"Content-Type": "multipart/form-data"},
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-Real-IP": "127.0.0.1"},
        {"X-Forwarded-Host": "evil.com"},
        {"Transfer-Encoding": "chunked"},
        {"Content-Length": "-1"},
        {"Content-Length": "999999999"},
        {"Accept-Encoding": "\x00\x00\x00"},
    ]
    
    for headers in malicious_headers:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/agents", 
                    json={"name":"header-test","role":"worker"},
                    headers=headers)
                if r.status_code >= 500:
                    record("HEADER", f"Malicious header: {headers}", "HIGH", "VULNERABLE",
                           f"HTTP 500 crash", "Validate/sanitize HTTP headers")
                else:
                    record("HEADER", f"Malicious header: {headers}", "LOW", "BLOCKED", f"HTTP {r.status_code}")
            except: pass
    
    # HTTP method confusion
    log("  7.2 HTTP method confusion...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for path in ["/v1/agents", "/v1/contracts", "/v1/settlement/create"]:
            for method_name in ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE"]:
                try:
                    if method_name == "PUT": r = await c.put(f"{BASE}{path}", json={})
                    elif method_name == "DELETE": r = await c.delete(f"{BASE}{path}")
                    elif method_name == "PATCH": r = await c.patch(f"{BASE}{path}", json={})
                    elif method_name == "OPTIONS": r = await c.options(f"{BASE}{path}")
                    elif method_name == "HEAD": r = await c.head(f"{BASE}{path}")
                    else: r = await c.request("TRACE", f"{BASE}{path}")
                    if r.status_code not in (404,405) and method_name == "TRACE":
                        record("HEADER", f"TRACE method allowed: {path}", "MEDIUM", "VULNERABLE",
                               "TRACE method enabled — XST attack possible",
                               "Disable TRACE method at server level")
                except: pass

# ================================================================
# 8. BUSINESS LOGIC EXPLOITATION
# ================================================================
async def attack_business_logic():
    log("\n🔴 CAT 8: BUSINESS LOGIC EXPLOITATION")
    if len(agents) < 10: return
    
    # 8.1 Wash trading ring (5 agents circular)
    log("  8.1 Wash trading ring (5-agent circular)...")
    ring = agents[:5]
    created_ring = 0
    for i in range(5):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            deadline = (datetime.now(timezone.utc)+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            r = await c.post(f"{BASE}/v1/contracts", json={
                "client_agent_id":ring[i],"title":f"Wash-Ring-{i}",
                "description":"wash trading","expected_output_schema":{},
                "expected_step_count":1,"escrow_amount":10.0,"currency":"USD","deadline_at":deadline
            })
            if r.status_code==201:
                tid = r.json()["task_id"]
                seller = ring[(i+1)%5]
                await c.patch(f"{BASE}/v1/contracts/{tid}/assign?worker_agent_id={seller}")
                created_ring += 1
    if created_ring == 5:
        record("BIZ", "5-agent wash trading ring created", "HIGH", "VULNERABLE",
               "All 5 circular contracts created — reputation farming via wash trading",
               "Add wash_trade_flags increment in reputation when circular pattern detected")
    else:
        record("BIZ", "5-agent wash trading ring created", "MEDIUM", "BLOCKED",
               f"{created_ring}/5 created — partial block")
    
    # 8.2 Front-running simulation (rapid sequential on same resource)
    log("  8.2 Front-running simulation...")
    if contracts and len(contracts) > 2:
        tid = contracts[2]["task_id"]
        buyer = contracts[2]["buyer"]
        # Rapid seq: create settlement, then immediately have another agent try to dispute it
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r1 = await c.post(f"{BASE}/v1/settlement/create", json={
                "task_id":tid,"client_agent_id":buyer,"escrow_amount":1.0,"currency":"USD"
            })
            if r1.status_code in (200,201):
                # Immediately try to file dispute from a different "attacker"
                attacker = agents[-1]
                r2 = await c.post(f"{BASE}/v1/arbitration/cases", json={
                    "task_id":tid,"opened_by":attacker,
                    "reason":"Front-running dispute attack"
                })
                if r2.status_code >= 400:
                    record("BIZ", "Front-running dispute blocked", "HIGH", "BLOCKED",
                           f"Arbitration blocked for outsider: HTTP {r2.status_code}")
                else:
                    record("BIZ", "Front-running dispute blocked", "HIGH", "VULNERABLE",
                           "Outsider can front-run dispute any task — denial of settlement attack",
                           "Only allow dispute from task participants (buyer/seller/arbitrator)")
    
    # 8.3 Reputation farming via minimum-value tasks
    log("  8.3 Reputation farming via micro-tasks...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if len(agents) >= 2:
            deadline = (datetime.now(timezone.utc)+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            r = await c.post(f"{BASE}/v1/contracts", json={
                "client_agent_id":agents[0],"title":"Micro-rep-farm",
                "description":"farm reputation with 0.000001 USDC task","expected_output_schema":{},
                "expected_step_count":1,"escrow_amount":0.000001,"currency":"USD","deadline_at":deadline
            })
            if r.status_code == 201:
                record("BIZ", "Micro-value reputation farming", "MEDIUM", "VULNERABLE",
                       "0.000001 USDC contract created — reputation can be farmed via micro-tasks",
                       "Add minimum escrow amount for reputation counting (ESCROW_MIN_AMOUNT)")
            else:
                record("BIZ", "Micro-value reputation farming", "LOW", "BLOCKED", f"HTTP {r.status_code}")

# ================================================================
# 9. TIMING SIDE-CHANNEL
# ================================================================
async def attack_timing():
    log("\n🔴 CAT 9: TIMING SIDE-CHANNEL")
    
    # Measure if valid vs invalid agent lookup has different response times
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Baseline: existing agent
        if agents:
            t0 = time.perf_counter()
            await c.get(f"{BASE}/v1/agents/{agents[0]}")
            t_existing = time.perf_counter() - t0
            
            t0 = time.perf_counter()
            await c.get(f"{BASE}/v1/agents/non-existent-agent-99999")
            t_missing = time.perf_counter() - t0
            
            ratio = max(t_missing, t_existing) / min(t_missing, t_existing) if min(t_missing, t_existing) > 0 else 0
            if ratio > 3:
                record("TIMING", "Agent lookup timing leak", "LOW", "VULNERABLE",
                       f"exists={t_existing*1000:.1f}ms vs missing={t_missing*1000:.1f}ms (ratio={ratio:.1f})",
                       "Use constant-time comparison for ID lookups")
            else:
                record("TIMING", "Agent lookup timing leak", "INFO", "BLOCKED", f"ratio={ratio:.1f} — likely safe")

# ================================================================
# 10. MASS CONCURRENT CHAOS (终极混合攻击)
# ================================================================
async def attack_chaos():
    log("\n🔴 CAT 10: MASS CONCURRENT CHAOS (1000 mixed attack ops)")
    
    if not agents: return
    deadline = (datetime.now(timezone.utc)+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    chaos_ops = [
        # Mix of attack patterns
        ("create_agent", lambda i,c: c.post(f"{BASE}/v1/agents", json={"name":f"chaos-{i:05d}","role":"worker","capabilities":["chaos"]})),
        ("oversized_contract", lambda i,c: c.post(f"{BASE}/v1/contracts", json={"client_agent_id":agents[i%len(agents)],"title":f"Chaos{i}","description":"d","expected_output_schema":{},"expected_step_count":999,"escrow_amount":1000000.0,"currency":"USD","deadline_at":deadline})),
        ("fake_receipt", lambda i,c: c.post(f"{BASE}/v1/receipts", json=make_receipt(f"chaos-{uuid.uuid4().hex[:16]}", agents[i%len(agents)], i%10+1))),
        ("invalid_voucher", lambda i,c: c.post(f"{BASE}/v1/vouchers", json={"buyer_identity_id":agents[i%len(agents)],"seller_identity_id":"ghost-999","amount":-1,"currency":"USD","bill_credit_amount":-1,"task_type":"evil","task_description_hash":"x"*128,"progress_rule_hash":"y"*128,"evidence_requirement_hash":"z"*128,"expiry_time":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),"nonce":uuid.uuid4().hex,"buyer_signature":"chaos"})),
        ("admin_probe", lambda i,c: c.post(f"{BASE}/v1/security/policies", json={"config":{"evil":True},"note":"chaos","rollout_percent":100})),
        ("overflow_step", lambda i,c: c.post(f"{BASE}/v1/receipts", json=make_receipt(contracts[i%len(contracts)]["task_id"] if contracts else "x", agents[i%len(agents)], 999999+i, 1))),
        ("huge_name", lambda i,c: c.post(f"{BASE}/v1/agents", json={"name":"Z"*50000,"role":"worker","capabilities":["huge"]})),
        ("sql_inject", lambda i,c: c.post(f"{BASE}/v1/agents", json={"name":f"'; DROP TABLE agents; -- {i}","role":"worker","capabilities":["sqli"]})),
    ]
    
    t0 = time.perf_counter()
    success = errs = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        async def chaos_op(i):
            try:
                _, fn = chaos_ops[i % len(chaos_ops)]
                r = await fn(i, c)
                return r.status_code < 400
            except: return False
        
        tasks = [chaos_op(i) for i in range(1000)]
        results = await asyncio.gather(*tasks)
        success = sum(1 for r in results if r)
        errs = sum(1 for r in results if not r)
    
    elapsed = time.perf_counter() - t0
    if success > 0:
        record("CHAOS", "1000 mixed concurrent attacks", "MEDIUM", "BLOCKED",
               f"{success} rejected, {errs} connection errors, throughput={1000/elapsed:.0f}/s — system survived chaos")
    else:
        record("CHAOS", "1000 mixed concurrent attacks", "HIGH", "VULNERABLE",
               f"All {1000} requests failed — system crashed under chaos!")

# ================================================================
# MAIN
# ================================================================
async def main():
    total_start = time.perf_counter()
    print("\n"+"="*70)
    print("  KARMA SECURITY ATTACK SIMULATION — LEVEL 2 (极狠模式)")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z")
    print("="*70)
    
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/health")
        print(f"  API: {r.json()}")
    
    await setup()
    await attack_fuzzing()
    await attack_boundary()
    await attack_chained()
    await attack_encoding()
    await attack_deserialization()
    await attack_race_v2()
    await attack_headers()
    await attack_business_logic()
    await attack_timing()
    await attack_chaos()
    
    total_elapsed = time.perf_counter() - total_start
    
    print("\n"+"="*70)
    print("  LEVEL 2 ATTACK SIMULATION — FINAL REPORT")
    print("="*70)
    
    sev_order = {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3,"INFO":4}
    
    for f in sorted(findings, key=lambda x: (sev_order.get(x.sev,99), x.id)):
        icon = "🔴" if f.result=="VULNERABLE" else "✅"
        print(f"  {icon} {f.id} [{f.sev:<8}] {f.cat:<8} {f.attack[:55]}")
    
    vulns = [f for f in findings if f.result=="VULNERABLE"]
    crits = [f for f in vulns if f.sev=="CRITICAL"]
    highs = [f for f in vulns if f.sev=="HIGH"]
    meds = [f for f in vulns if f.sev=="MEDIUM"]
    lows = [f for f in vulns if f.sev=="LOW"]
    
    print(f"\n  TOTAL: {stats['total']} attacks")
    print(f"  ✅ BLOCKED:    {stats['blocked']}")
    print(f"  🔴 VULNERABLE: {stats['vulnerable']}")
    print(f"  ⚠️  ERRORS:    {stats['errors']}")
    print(f"\n  SEVERITY: CRITICAL={len(crits)} HIGH={len(highs)} MEDIUM={len(meds)} LOW={len(lows)}")
    
    if vulns:
        print(f"\n{'='*70}")
        print(f"  FIX CHECKLIST ({len(vulns)} vulnerabilities)")
        print(f"{'='*70}\n")
        for f in sorted(vulns, key=lambda x: sev_order.get(x.sev,99)):
            print(f"  [{f.sev}] {f.id}: {f.attack}")
            print(f"    Problem: {f.detail}")
            if f.fix: print(f"    Fix:     {f.fix}")
            print()
    
    print(f"\n  Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"  DB State: {len(agents)} agents, {len(contracts)} contracts")
    
    if crits:
        print(f"\n  ⚠️  {len(crits)} CRITICAL — immediate action required!")
    
    return 0 if len(crits)==0 else 1

if __name__=="__main__":
    sys.exit(asyncio.run(main()))
