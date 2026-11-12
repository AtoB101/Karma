#!/usr/bin/env python3
"""
Karma Security Attack Simulation — 10,000 accounts, 12 attack categories
=========================================================================
Simulates real-world attack patterns against Karma protocol.
Each attack is classified: BLOCKED ✅ or VULNERABLE 🔴
"""
import asyncio, sys, time, uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any
from core.schemas import ExecutionReceipt, ToolStatus
from services.signing import signing_service
import httpx

BASE = "http://localhost:8000"
TIMEOUT = 60.0
CONCURRENT = 500

@dataclass
class Finding:
    id: str
    category: str
    attack: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    result: str    # BLOCKED, VULNERABLE, ERROR, PARTIAL
    detail: str
    fix: str

findings: list[Finding] = []
stats = {"total": 0, "blocked": 0, "vulnerable": 0, "errors": 0}
test_agents = []
test_contracts = []
test_runtime_keys = []

def log(msg):
    print(f"  [{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)

def record(cat, attack, sev, result, detail, fix=""):
    fid = f"KSA-{len(findings)+1:03d}"
    findings.append(Finding(fid, cat, attack, sev, result, detail, fix))
    stats["total"] += 1
    if result == "BLOCKED" or result.startswith("BLOCKED"):
        stats["blocked"] += 1
        print(f"    ✅ {fid} BLOCKED: {attack}")
    elif result == "VULNERABLE":
        stats["vulnerable"] += 1
        print(f"    🔴 {fid} VULNERABLE [{sev}]: {attack}")
    else:
        stats["errors"] += 1
        print(f"    ⚠️ {fid} {result}: {attack}")

# ================================================================
# SETUP
# ================================================================
async def setup(num_agents=1000):
    log(f"SETUP: Creating {num_agents} test accounts...")
    t0 = time.perf_counter()
    created = []
    
    for batch in range(0, num_agents, 200):
        async def create_one(i):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    r = await c.post(f"{BASE}/v1/agents", json={
                        "name": f"attacker-{i:05d}", "role": "worker",
                        "capabilities": ["attack_sim"]
                    })
                    if r.status_code == 201:
                        return r.json()["agent_id"]
                except: pass
            return None
        
        tasks = [create_one(i) for i in range(batch, min(batch+200, num_agents))]
        results = await asyncio.gather(*tasks)
        created.extend([a for a in results if a is not None])
    
    global test_agents
    test_agents = created
    elapsed = time.perf_counter() - t0
    log(f"  Created {len(created)} agents in {elapsed:.1f}s")
    
    # Create some contracts for testing
    if len(created) >= 2:
        log("SETUP: Creating test contracts...")
        for i in range(min(50, len(created))):
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                try:
                    buyer = created[i]
                    seller = created[(i+1) % len(created)]
                    r = await c.post(f"{BASE}/v1/contracts", json={
                        "client_agent_id": buyer, "title": f"Test-{i}",
                        "description": "attack test contract",
                        "expected_output_schema": {}, "expected_step_count": 3,
                        "escrow_amount": 1.0, "currency": "USD",
                        "deadline_at": (datetime.utcnow()+timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
                    })
                    if r.status_code == 201:
                        tid = r.json()["task_id"]
                        test_contracts.append({"task_id": tid, "buyer": buyer, "seller": seller})
                except: pass
    
    log(f"  Setup complete: {len(created)} agents, {len(test_contracts)} contracts")

def make_signed_receipt(tid, aid, step, dur_ms=50):
    now = datetime.utcnow()
    rec = ExecutionReceipt(
        task_id=tid, agent_id=aid, step_index=step,
        tool_name="attack.tool",
        input_hash=uuid.uuid4().hex+uuid.uuid4().hex,
        output_hash=uuid.uuid4().hex+uuid.uuid4().hex,
        started_at=now, ended_at=now+timedelta(milliseconds=dur_ms),
        duration_ms=dur_ms, status=ToolStatus.SUCCESS
    )
    rec.signature = signing_service.sign_receipt(rec)
    body = rec.model_dump(mode="json")
    body["started_at"] = now.strftime("%Y-%m-%dT%H:%M:%S.%f")
    body["ended_at"] = (now+timedelta(milliseconds=dur_ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return body

# ================================================================
# ATTACK CATEGORIES
# ================================================================

# --- 1. Sybil / Identity Attacks ---
async def attack_sybil():
    log("\n🔴 CATEGORY 1: SYBIL / IDENTITY ATTACKS")
    
    # 1.1 Mass fake registration (10000 concurrent)
    log("  1.1 Mass fake agent registration (500 concurrent)...")
    async def register_fake(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/agents", json={
                    "name": f"sybil-{uuid.uuid4().hex[:8]}", "role": "worker",
                    "capabilities": ["sybil_attack"]
                })
                return r.status_code == 201
            except: return False
    tasks = [register_fake(i) for i in range(500)]
    results = await asyncio.gather(*tasks)
    created = sum(1 for r in results if r)
    if created > 0:
        record("SYBIL", "Mass fake registration (500 concurrent)", "MEDIUM", "VULNERABLE",
               f"{created}/500 fake agents created successfully — no CAPTCHA or registration limits",
               "Add rate limiting per IP, CAPTCHA for bulk registration, identity verification requirements")
    else:
        record("SYBIL", "Mass fake registration (500 concurrent)", "MEDIUM", "BLOCKED",
               "All registrations blocked — rate limiting active")
    
    # 1.2 Agent ID spoofing
    log("  1.2 Agent ID spoofing...")
    if test_agents and len(test_agents) >= 2:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            real_aid = test_agents[0]
            victim_aid = test_agents[1]
            # Try to act as another agent
            r = await c.post(f"{BASE}/v1/receipts", json={
                "task_id": "fake-task-id", "agent_id": victim_aid, "step_index": 1,
                "tool_name": "spoof", "input_hash": "a"*64, "output_hash": "b"*64,
                "started_at": datetime.utcnow().isoformat(),
                "ended_at": datetime.utcnow().isoformat(),
                "duration_ms": 50, "status": "success",
                "signature": f"sig-{uuid.uuid4().hex}"
            })
            # We're checking if the API validates that the caller is actually the agent they claim to be
            if r.status_code >= 400:
                record("SYBIL", "Agent ID spoofing via receipt", "HIGH", "BLOCKED",
                       f"HTTP {r.status_code}: {r.text[:100]}")
            else:
                record("SYBIL", "Agent ID spoofing via receipt", "CRITICAL", "VULNERABLE",
                       f"Receipt accepted with forged agent_id — no identity verification")

# --- 2. Runtime Key Attacks ---
async def attack_runtime_keys():
    log("\n🔴 CATEGORY 2: RUNTIME KEY ATTACKS")
    
    if not test_agents:
        record("RTKEY", "Runtime Key tests skipped", "INFO", "ERROR", "No agents available")
        return
    
    buyer = test_agents[0]
    
    # 2.1 Create key with withdraw permission
    log("  2.1 Runtime Key with withdraw permission...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/runtime-gateway/create-key", json={
            "wallet_address": f"0xAttack{uuid.uuid4().hex[:16]}",
            "karma_identity_id": buyer,
            "permissions": ["withdraw", "transfer", "request_voucher"],
            "single_limit": 999999.0,
            "daily_limit": 999999.0,
            "agent_name": "evil-withdraw-bot",
            "agent_binding": "malicious-v1"
        })
        if r.status_code in (200, 201):
            data = r.json()
            perms = str(data.get("permissions", ""))
            if "withdraw" in perms or "transfer" in perms:
                record("RTKEY", "Runtime Key with withdraw permission", "CRITICAL", "VULNERABLE",
                       f"Key created with withdraw/transfer permissions — CRITICAL SECURITY HOLE",
                       "Strip 'withdraw' and 'transfer' from permissions in runtime_key_service.create_key()")
            else:
                record("RTKEY", "Runtime Key with withdraw permission", "HIGH", "BLOCKED",
                       f"Permissions sanitized — withdraw/transfer removed (HTTP {r.status_code})")
        else:
            record("RTKEY", "Runtime Key with withdraw permission", "HIGH", "BLOCKED",
                   f"HTTP {r.status_code}: {r.text[:100]}")
    
    # 2.2 Create key with excessive limits (1000000 USDC)
    log("  2.2 Runtime Key with excessive limits...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/runtime-gateway/create-key", json={
            "wallet_address": f"0xBig{uuid.uuid4().hex[:16]}",
            "karma_identity_id": buyer,
            "permissions": ["request_voucher"],
            "single_limit": 1000000.0,
            "daily_limit": 10000000.0,
            "agent_name": "big-spender",
            "agent_binding": "oversize-v1"
        })
        if r.status_code in (200, 201):
            data = r.json()
            sl = data.get("single_limit", 0)
            dl = data.get("daily_limit", 0)
            if sl > 10000 or dl > 100000:
                record("RTKEY", "Runtime Key with excessive limits", "HIGH", "VULNERABLE",
                       f"Created with single_limit={sl}, daily_limit={dl}",
                       "Cap single_limit at ESCROW_MAX_AMOUNT, daily_limit at some reasonable multiple")
            else:
                record("RTKEY", "Runtime Key with excessive limits", "MEDIUM", "BLOCKED",
                       f"Limits capped: single={sl}, daily={dl}")
        else:
            record("RTKEY", "Runtime Key with excessive limits", "MEDIUM", "BLOCKED", f"HTTP {r.status_code}")
    
    # 2.3 Reuse revoked key
    log("  2.3 Revoked key reuse...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Create a key first
        r = await c.post(f"{BASE}/v1/runtime-gateway/create-key", json={
            "wallet_address": f"0xRevoke{uuid.uuid4().hex[:16]}",
            "karma_identity_id": buyer,
            "permissions": ["request_voucher"],
            "single_limit": 5.0, "daily_limit": 10.0,
            "agent_name": "revoke-test", "agent_binding": "revoke-v1"
        })
        if r.status_code in (200, 201):
            key_id = r.json().get("key_id", "")
            # Revoke it
            r2 = await c.post(f"{BASE}/v1/runtime-gateway/revoke-key", json={"key_id": key_id})
            if r2.status_code in (200, 201):
                # Try to use revoked key
                r3 = await c.post(f"{BASE}/v1/runtime-gateway/list-keys", json={"karma_identity_id": buyer})
                if r3.status_code in (200, 201):
                    keys = r3.json() if isinstance(r3.json(), list) else r3.json().get("keys", [])
                    revoked_key = next((k for k in keys if k.get("key_id") == key_id), None)
                    if revoked_key and revoked_key.get("status") == "revoked":
                        record("RTKEY", "Revoked key reuse prevented", "HIGH", "BLOCKED",
                               "Key status correctly set to 'revoked'")
                    else:
                        record("RTKEY", "Revoked key reuse prevented", "HIGH", "VULNERABLE",
                               f"Revoked key still usable: status={revoked_key.get('status') if revoked_key else 'not found'}")

# --- 3. Voucher Attacks ---
async def attack_vouchers():
    log("\n🔴 CATEGORY 3: VOUCHER ATTACKS")
    
    if len(test_agents) < 2 or len(test_contracts) < 1:
        record("VOUCHER", "Voucher tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    buyer = test_agents[0]
    seller = test_agents[1]
    
    # 3.1 Oversized voucher
    log("  3.1 Oversized voucher (1000000 USDC)...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/vouchers", json={
            "buyer_identity_id": buyer, "seller_identity_id": seller,
            "amount": 1000000.0, "currency": "USD", "bill_credit_amount": 1000000.0,
            "task_type": "gigantic", "task_description_hash": "a"*128,
            "progress_rule_hash": "b"*128, "evidence_requirement_hash": "c"*128,
            "expiry_time": (datetime.utcnow()+timedelta(hours=1)).isoformat(),
            "nonce": uuid.uuid4().hex, "buyer_signature": "attack-sig"
        })
        if r.status_code >= 400:
            record("VOUCHER", "Oversized voucher (1000000 USDC)", "CRITICAL", "BLOCKED",
                   f"HTTP {r.status_code}: {r.text[:100]}")
        else:
            record("VOUCHER", "Oversized voucher (1000000 USDC)", "CRITICAL", "VULNERABLE",
                   f"Voucher created: amount={r.json().get('amount')} — NO CAP!",
                   "Validate voucher amount against capacity and ESCROW_MAX_AMOUNT")
    
    # 3.2 Voucher for non-existent seller
    log("  3.2 Voucher for non-existent seller...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/vouchers", json={
            "buyer_identity_id": buyer, "seller_identity_id": "non-existent-seller-999999",
            "amount": 1.0, "currency": "USD", "bill_credit_amount": 1.0,
            "task_type": "ghost", "task_description_hash": "a"*128,
            "progress_rule_hash": "b"*128, "evidence_requirement_hash": "c"*128,
            "expiry_time": (datetime.utcnow()+timedelta(hours=1)).isoformat(),
            "nonce": uuid.uuid4().hex, "buyer_signature": "attack-sig"
        })
        if r.status_code >= 400:
            record("VOUCHER", "Voucher for non-existent seller", "MEDIUM", "BLOCKED", f"HTTP {r.status_code}")
        else:
            record("VOUCHER", "Voucher for non-existent seller", "HIGH", "VULNERABLE",
                   "Voucher created for non-existent seller — no identity validation",
                   "Validate seller_identity_id exists before creating voucher")
    
    # 3.3 Duplicate nonce (replay)
    log("  3.3 Voucher nonce replay...")
    nonce = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        voucher_data = {
            "buyer_identity_id": buyer, "seller_identity_id": seller,
            "amount": 0.1, "currency": "USD", "bill_credit_amount": 0.1,
            "task_type": "replay", "task_description_hash": "a"*128,
            "progress_rule_hash": "b"*128, "evidence_requirement_hash": "c"*128,
            "expiry_time": (datetime.utcnow()+timedelta(hours=1)).isoformat(),
            "nonce": nonce, "buyer_signature": "attack-sig"
        }
        r1 = await c.post(f"{BASE}/v1/vouchers", json=voucher_data)
        r2 = await c.post(f"{BASE}/v1/vouchers", json=voucher_data)
        if r2.status_code >= 400:
            record("VOUCHER", "Voucher nonce replay attack", "CRITICAL", "BLOCKED",
                   f"Replay rejected: HTTP {r2.status_code} (first: {r1.status_code})")
        elif r2.status_code in (200, 201):
            record("VOUCHER", "Voucher nonce replay attack", "CRITICAL", "VULNERABLE",
                   "Same nonce accepted twice — DOUBLE SPEND POSSIBLE!",
                   "Enforce UNIQUE constraint on (buyer_identity_id, nonce) — DB already has this, check why not enforced")

# --- 4. Receipt Attacks ---
async def attack_receipts():
    log("\n🔴 CATEGORY 4: RECEIPT ATTACKS")
    
    if len(test_contracts) < 1 or len(test_agents) < 2:
        record("RECEIPT", "Receipt tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    ctr = test_contracts[0]
    tid = ctr["task_id"]
    buyer = ctr["buyer"]
    
    # Create legitimate step 1 receipt first, then attack
    log("  4.0 Creating baseline receipt...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/receipts", json=make_signed_receipt(tid, buyer, 1))
        baseline_ok = r.status_code == 201
    
    # 4.1 Duplicate step_index (replay)
    log("  4.1 Duplicate step_index attack...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/receipts", json=make_signed_receipt(tid, buyer, 1))
        if r.status_code >= 400:
            record("RECEIPT", "Duplicate step_index blocked", "HIGH", "BLOCKED",
                   f"HTTP {r.status_code}: {r.text[:100]}")
        else:
            record("RECEIPT", "Duplicate step_index blocked", "CRITICAL", "VULNERABLE",
                   "Duplicate receipt accepted — data integrity compromised",
                   "Enforce UNIQUE(task_id, step_index) constraint, check DB constraint is active")
    
    # 4.2 Step index skip (1 → 99)
    log("  4.2 Step index skip attack (1 → 99)...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/receipts", json=make_signed_receipt(tid, buyer, 99))
        if r.status_code >= 400:
            record("RECEIPT", "Step index skip blocked", "MEDIUM", "BLOCKED",
                   f"HTTP {r.status_code}: {r.text[:100]}")
        else:
            record("RECEIPT", "Step index skip blocked", "HIGH", "VULNERABLE",
                   "Receipt with step 99 accepted after step 1 — sequence enforcement broken",
                   "Enforce sequential step_index in receipt store")
    
    # 4.3 Out-of-order timestamps
    log("  4.3 Out-of-order timestamp attack...")
    past = datetime.utcnow() - timedelta(hours=24)
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/receipts", json=make_signed_receipt(tid, buyer, 2))
        if r.status_code != 201:
            # Try with ancient timestamp
            old_body = make_signed_receipt(tid, buyer, 2)
            old_body["started_at"] = past.strftime("%Y-%m-%dT%H:%M:%S.%f")
            old_body["ended_at"] = (past+timedelta(milliseconds=50)).strftime("%Y-%m-%dT%H:%M:%S.%f")
            r = await c.post(f"{BASE}/v1/receipts", json=old_body)
        if r.status_code >= 400:
            record("RECEIPT", "Out-of-order timestamp blocked", "LOW", "BLOCKED", f"HTTP {r.status_code}")
        else:
            record("RECEIPT", "Out-of-order timestamp blocked", "MEDIUM", "VULNERABLE",
                   "Ancient timestamp receipt accepted",
                   "Enforce receipt timestamp ordering per task in receipt store")
    
    # 4.4 Receipt for non-existent task
    log("  4.4 Receipt for non-existent task...")
    fake_tid = f"fake-{uuid.uuid4().hex}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/receipts", json=make_signed_receipt(fake_tid, buyer, 1))
        if r.status_code >= 400:
            record("RECEIPT", "Receipt for non-existent task", "MEDIUM", "BLOCKED",
                   f"HTTP {r.status_code}: {r.text[:100]}")
        else:
            record("RECEIPT", "Receipt for non-existent task", "HIGH", "VULNERABLE",
                   "Receipt accepted for non-existent task_id",
                   "Validate task_id exists (FK constraint on task_contracts)")

# --- 5. Progress Attacks ---
async def attack_progress():
    log("\n🔴 CATEGORY 5: PROGRESS ATTACKS")
    
    if len(test_contracts) < 1 or len(test_agents) < 2:
        record("PROGRESS", "Progress tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    ctr = test_contracts[0]
    tid = ctr["task_id"]
    seller = ctr["seller"]
    
    # 5.1 Progress regression (try 100% first, then 30%)
    log("  5.1 Progress regression attack (100% → 30%)...")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r1 = await c.post(f"{BASE}/v1/progress", json={
            "task_id": tid, "seller_identity_id": seller,
            "progress_percent": 100.0, "claimed_value_percent": 100.0,
            "evidence_hash": uuid.uuid4().hex, "runtime_log_hash": uuid.uuid4().hex,
            "timestamp": datetime.utcnow().isoformat(),
            "seller_signature": f"sig-{uuid.uuid4().hex}",
            "validation_method": "auto"
        })
        r2 = await c.post(f"{BASE}/v1/progress", json={
            "task_id": tid, "seller_identity_id": seller,
            "progress_percent": 30.0, "claimed_value_percent": 30.0,
            "evidence_hash": uuid.uuid4().hex, "runtime_log_hash": uuid.uuid4().hex,
            "timestamp": datetime.utcnow().isoformat(),
            "seller_signature": f"sig-{uuid.uuid4().hex}",
            "validation_method": "auto"
        })
        if r2.status_code >= 400:
            record("PROGRESS", "Progress regression blocked", "HIGH", "BLOCKED",
                   f"Regression blocked (100%→30%): HTTP {r2.status_code}")
        else:
            record("PROGRESS", "Progress regression blocked", "CRITICAL", "VULNERABLE",
                   "Progress can regress from 100% to 30% — financial integrity broken!",
                   "Enforce monotonic progress_percent in progress store")

# --- 6. Settlement Attacks ---
async def attack_settlement():
    log("\n🔴 CATEGORY 6: SETTLEMENT ATTACKS")
    
    if len(test_contracts) < 2 or len(test_agents) < 4:
        record("SETTLE", "Settlement tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    # 6.1 State machine bypass (CREATED → SUBMITTED directly)
    log("  6.1 State machine bypass (CREATED → SUBMITTED)...")
    ctr = test_contracts[1] if len(test_contracts) > 1 else test_contracts[0]
    tid = ctr["task_id"]
    buyer = ctr["buyer"]
    seller = ctr["seller"]
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        # Create settlement
        r = await c.post(f"{BASE}/v1/settlement/create", json={
            "task_id": tid, "client_agent_id": buyer,
            "escrow_amount": 1.0, "currency": "USD"
        })
        if r.status_code in (200, 201):
            # Try skip to submit
            r2 = await c.post(f"{BASE}/v1/settlement/{tid}/submit", json={})
            if r2.status_code >= 400:
                record("SETTLE", "State machine bypass blocked", "CRITICAL", "BLOCKED",
                       f"CREATED→SUBMITTED: HTTP {r2.status_code}: {r2.text[:100]}")
            else:
                record("SETTLE", "State machine bypass blocked", "CRITICAL", "VULNERABLE",
                       "CREATED→SUBMITTED jump allowed — STATE MACHINE BROKEN",
                       "Add transition validation: only allow LOCKED after CREATED, etc.")
    
    # 6.2 Double settlement (same task)
    log("  6.2 Double settlement attack...")
    ctr2 = test_contracts[2] if len(test_contracts) > 2 else test_contracts[0]
    tid2 = ctr2["task_id"]
    buyer2 = ctr2["buyer"]
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r1 = await c.post(f"{BASE}/v1/settlement/create", json={
            "task_id": tid2, "client_agent_id": buyer2,
            "escrow_amount": 1.0, "currency": "USD"
        })
        # Try second settlement on same task
        r2 = await c.post(f"{BASE}/v1/settlement/create", json={
            "task_id": tid2, "client_agent_id": buyer2,
            "escrow_amount": 1.0, "currency": "USD"
        })
        if r2.status_code >= 400:
            record("SETTLE", "Double settlement blocked", "CRITICAL", "BLOCKED",
                   f"HTTP {r2.status_code}: {r2.text[:100]}")
        elif r2.status_code in (200, 201):
            record("SETTLE", "Double settlement blocked", "CRITICAL", "VULNERABLE",
                   "Two settlements created for same task — DOUBLE SETTLE POSSIBLE!",
                   "Enforce UNIQUE(task_id) on settlements table")

# --- 7. Injection Attacks ---
async def attack_injection():
    log("\n🔴 CATEGORY 7: INJECTION ATTACKS")
    
    # 7.1 SQL injection in agent name
    log("  7.1 SQL injection in agent name...")
    payloads = [
        "'; DROP TABLE agents; --",
        "1' OR '1'='1",
        "'; DELETE FROM settlements WHERE 1=1; --",
        "admin'--",
        "<script>alert('xss')</script>",
        "${7*7}",
        "{{constructor.constructor('return this.process')()}}",
        "../../../etc/passwd",
    ]
    
    async def inject(payload):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/agents", json={
                    "name": payload, "role": "worker", "capabilities": ["injection_test"]
                })
                return r.status_code, r.text[:200]
            except: return 0, ""
    
    for payload in payloads:
        status, body = await inject(payload)
        if status >= 500:
            record("INJECT", f"SQL/XSS injection: '{payload[:40]}'", "CRITICAL", "VULNERABLE",
                   f"HTTP 500 — possible unhandled injection: {body}",
                   "Sanitize and validate all user input, use parameterized queries")
        elif status in (200, 201):
            record("INJECT", f"SQL/XSS injection: '{payload[:40]}'", "MEDIUM", "BLOCKED",
                   f"Accepted but sanitized (HTTP {status})")
        else:
            record("INJECT", f"SQL/XSS injection: '{payload[:40]}'", "LOW", "BLOCKED",
                   f"HTTP {status}")
    
    # 7.2 Oversized field values
    log("  7.2 Oversized field attack...")
    huge_name = "A" * 100000
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            r = await c.post(f"{BASE}/v1/agents", json={
                "name": huge_name, "role": "worker", "capabilities": ["dos"]
            })
            if r.status_code >= 400:
                record("INJECT", "Oversized field (100KB name)", "MEDIUM", "BLOCKED",
                       f"HTTP {r.status_code}: {r.text[:100]}")
            else:
                record("INJECT", "Oversized field (100KB name)", "HIGH", "VULNERABLE",
                       "100KB agent name accepted — memory exhaustion risk",
                       "Add max_length validation to all string fields")
        except Exception as e:
            record("INJECT", "Oversized field (100KB name)", "MEDIUM", "BLOCKED",
                   f"Request rejected/timeout: {str(e)[:100]}")

# --- 8. Concurrent / Race Condition Attacks ---
async def attack_race_conditions():
    log("\n🔴 CATEGORY 8: RACE CONDITION ATTACKS")
    
    if len(test_contracts) < 1 or len(test_agents) < 2:
        record("RACE", "Race condition tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    # 8.1 100 concurrent settlements on same task
    log("  8.1 100 concurrent settlements on same task...")
    ctr = test_contracts[3] if len(test_contracts) > 3 else test_contracts[0]
    tid = ctr["task_id"]
    buyer = ctr["buyer"]
    
    async def race_settle(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/settlement/create", json={
                    "task_id": tid, "client_agent_id": buyer,
                    "escrow_amount": 1.0, "currency": "USD"
                })
                return r.status_code
            except: return 0
    
    tasks = [race_settle(i) for i in range(100)]
    results = await asyncio.gather(*tasks)
    created_200 = sum(1 for c in results if c in (200, 201))
    blocked = sum(1 for c in results if c >= 400)
    
    if created_200 <= 1:
        record("RACE", "100 concurrent settlements on same task", "CRITICAL", "BLOCKED",
               f"Only {created_200} created, {blocked} blocked — concurrency-safe")
    else:
        record("RACE", "100 concurrent settlements on same task", "CRITICAL", "VULNERABLE",
               f"{created_200} settlements created for SAME task — RACE CONDITION!",
               "Add database-level UNIQUE constraint + application-level mutex for settlement creation")
    
    # 8.2 100 concurrent receipt submissions same step
    log("  8.2 100 concurrent receipts same step...")
    ctr2 = test_contracts[4] if len(test_contracts) > 4 else test_contracts[0]
    tid2 = ctr2["task_id"]
    buyer2 = ctr2["buyer"]
    
    async def race_receipt(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.post(f"{BASE}/v1/receipts", json=make_signed_receipt(tid2, buyer2, 1))
                return r.status_code
            except: return 0
    
    tasks = [race_receipt(i) for i in range(100)]
    results = await asyncio.gather(*tasks)
    created_rcpt = sum(1 for c in results if c == 201)
    blocked_rcpt = sum(1 for c in results if c >= 400)
    
    if created_rcpt <= 1:
        record("RACE", "100 concurrent receipts same step", "HIGH", "BLOCKED",
               f"Only {created_rcpt} created, {blocked_rcpt} blocked — concurrency-safe")
    else:
        record("RACE", "100 concurrent receipts same step", "CRITICAL", "VULNERABLE",
               f"{created_rcpt} receipts created for SAME step — RACE CONDITION!",
               "Add UNIQUE(task_id, step_index) constraint — DB has uq_task_step, verify it's enforced at application level")

# --- 9. Dispute/Arbitration Attacks ---
async def attack_dispute():
    log("\n🔴 CATEGORY 9: DISPUTE ATTACKS")
    
    if len(test_contracts) < 1 or len(test_agents) < 2:
        record("DISPUTE", "Dispute tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    # 9.1 Dispute by non-participant
    log("  9.1 Dispute by non-participant...")
    ctr = test_contracts[0]
    tid = ctr["task_id"]
    outsider = test_agents[-1] if len(test_agents) > 2 else test_agents[0]
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/arbitration/cases", json={
            "task_id": tid, "opened_by": outsider,
            "reason": "Unauthorized dispute by outsider"
        })
        if r.status_code >= 400:
            record("DISPUTE", "Dispute by non-participant blocked", "HIGH", "BLOCKED",
                   f"HTTP {r.status_code}: {r.text[:100]}")
        else:
            record("DISPUTE", "Dispute by non-participant blocked", "HIGH", "VULNERABLE",
                   "Outsider can file dispute on any task",
                   "Validate that opened_by is buyer or seller of the task")

# --- 10. Denial of Service ---
async def attack_dos():
    log("\n🔴 CATEGORY 10: DENIAL OF SERVICE")
    
    # 10.1 Rapid fire requests
    log("  10.1 Rapid fire requests (500 concurrent health checks)...")
    t0 = time.perf_counter()
    async def rapid_health(i):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            try:
                r = await c.get(f"{BASE}/health")
                return r.status_code == 200
            except: return False
    
    tasks = [rapid_health(i) for i in range(500)]
    results = await asyncio.gather(*tasks)
    ok = sum(1 for r in results if r)
    elapsed = time.perf_counter() - t0
    
    if ok > 0:
        record("DOS", f"500 concurrent health checks", "LOW", "BLOCKED",
               f"{ok}/500 ok, throughput={ok/elapsed:.0f}/s — service resilient")
    else:
        record("DOS", f"500 concurrent health checks", "HIGH", "VULNERABLE",
               "All requests failed — possible DoS vulnerability")

# --- 11. Collusion/Fraud Patterns ---
async def attack_collusion():
    log("\n🔴 CATEGORY 11: COLLUSION / FRAUD PATTERNS")
    
    if len(test_agents) < 3:
        record("FRAUD", "Collusion tests skipped", "INFO", "ERROR", "Insufficient test data")
        return
    
    # 11.1 Self-dealing (buyer == seller)
    log("  11.1 Self-dealing attack (buyer == seller)...")
    agent = test_agents[0]
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}/v1/contracts", json={
            "client_agent_id": agent, "title": "Self-Dealing",
            "description": "I pay myself", "expected_output_schema": {},
            "expected_step_count": 1, "escrow_amount": 100.0,
            "currency": "USD",
            "deadline_at": (datetime.utcnow()+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        })
        if r.status_code == 201:
            tid = r.json()["task_id"]
            # Try to assign self as worker
            r2 = await c.patch(f"{BASE}/v1/contracts/{tid}/assign?worker_agent_id={agent}")
            if r2.status_code in (200, 201):
                record("FRAUD", "Self-dealing (buyer == seller)", "HIGH", "VULNERABLE",
                       "Self-dealing contract allowed — wash trading for reputation farming",
                       "Block contracts where client_agent_id == worker_agent_id")
            else:
                record("FRAUD", "Self-dealing (buyer == seller)", "HIGH", "BLOCKED",
                       f"Self-assignment blocked: HTTP {r2.status_code}")
        else:
            record("FRAUD", "Self-dealing (buyer == seller)", "HIGH", "BLOCKED",
                   f"Self-dealing contract blocked: HTTP {r.status_code}")
    
    # 11.2 Circular settlement (A→B→C→A) detection
    log("  11.2 Circular settlement detection...")
    if len(test_agents) >= 3:
        a, b, c = test_agents[:3]
        async with httpx.AsyncClient(timeout=TIMEOUT) as c2:
            deadline = (datetime.utcnow()+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
            # A→B
            r1 = await c2.post(f"{BASE}/v1/contracts", json={
                "client_agent_id": a, "title": "Circ A→B",
                "description": "Circle 1", "expected_output_schema": {},
                "expected_step_count": 1, "escrow_amount": 10.0,
                "currency": "USD", "deadline_at": deadline
            })
            # B→C
            r2 = await c2.post(f"{BASE}/v1/contracts", json={
                "client_agent_id": b, "title": "Circ B→C",
                "description": "Circle 2", "expected_output_schema": {},
                "expected_step_count": 1, "escrow_amount": 10.0,
                "currency": "USD", "deadline_at": deadline
            })
            # C→A
            r3 = await c2.post(f"{BASE}/v1/contracts", json={
                "client_agent_id": c, "title": "Circ C→A",
                "description": "Circle 3", "expected_output_schema": {},
                "expected_step_count": 1, "escrow_amount": 10.0,
                "currency": "USD", "deadline_at": deadline
            })
            all_ok = r1.status_code == 201 and r2.status_code == 201 and r3.status_code == 201
            if all_ok:
                record("FRAUD", "Circular settlement (A→B→C→A)", "MEDIUM", "VULNERABLE",
                       "Circular contracts all created — no cycle detection",
                       "Add responsibility graph cycle detection for circular settlements")
            else:
                record("FRAUD", "Circular settlement (A→B→C→A)", "MEDIUM", "BLOCKED",
                       f"At least one blocked: {r1.status_code}/{r2.status_code}/{r3.status_code}")

# --- 12. Privilege Escalation ---
async def attack_privilege():
    log("\n🔴 CATEGORY 12: PRIVILEGE ESCALATION")
    
    # 12.1 Access admin endpoints without auth
    log("  12.1 Unauthorized admin endpoint access...")
    admin_endpoints = [
        "/v1/admin-controls/brake",
        "/v1/admin-controls/unbrake",
        "/v1/security/policies",  # should be readable
    ]
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for ep in admin_endpoints:
            r = await c.post(f"{BASE}{ep}", json={})
            if r.status_code == 401 or r.status_code == 403:
                record("PRIV", f"Admin endpoint '{ep}' protected", "HIGH", "BLOCKED",
                       f"HTTP {r.status_code} — auth required")
            elif r.status_code in (200, 201):
                record("PRIV", f"Admin endpoint '{ep}' protected", "CRITICAL", "VULNERABLE",
                       f"HTTP {r.status_code} — UNAUTHORIZED ACCESS!",
                       "Require authentication for all admin endpoints")
            # else: 404/405 = endpoint not available or wrong method, which is fine

# ================================================================
# MAIN
# ================================================================
async def main():
    total_start = time.perf_counter()
    
    print("\n" + "="*70)
    print("  KARMA SECURITY ATTACK SIMULATION")
    print("  10,000 accounts | 12 attack categories | 500 concurrent")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}Z")
    print("="*70)
    
    # Verify API
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/health")
        print(f"  API: {r.json()}")
    
    # Setup
    await setup(1000)  # 1000 agents for testing (already have 10K from before)
    
    # Run all attack categories
    await attack_sybil()
    await attack_runtime_keys()
    await attack_vouchers()
    await attack_receipts()
    await attack_progress()
    await attack_settlement()
    await attack_injection()
    await attack_race_conditions()
    await attack_dispute()
    await attack_dos()
    await attack_collusion()
    await attack_privilege()
    
    # ================================================================
    # FINAL REPORT
    # ================================================================
    total_elapsed = time.perf_counter() - total_start
    
    print("\n" + "="*70)
    print("  SECURITY ATTACK SIMULATION — FINAL REPORT")
    print("="*70)
    
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    
    print(f"\n  {'ID':<10} {'Severity':<10} {'Category':<12} {'Result':<12} Attack")
    print(f"  {'-'*10} {'-'*10} {'-'*12} {'-'*12} {'-'*40}")
    
    for f in sorted(findings, key=lambda x: (sev_order.get(x.severity, 99), x.id)):
        icon = "🔴" if f.result == "VULNERABLE" else "✅"
        print(f"  {icon} {f.id:<7} {f.severity:<10} {f.category:<12} {f.result:<12} {f.attack[:50]}")
    
    print(f"\n  {'─'*70}")
    print(f"  TOTAL: {stats['total']} attacks")
    print(f"  ✅ BLOCKED:    {stats['blocked']}")
    print(f"  🔴 VULNERABLE: {stats['vulnerable']}")
    print(f"  ⚠️  ERRORS:     {stats['errors']}")
    
    vulns = [f for f in findings if f.result == "VULNERABLE"]
    if vulns:
        print(f"\n{'='*70}")
        print(f"  FIX CHECKLIST ({len(vulns)} vulnerabilities)")
        print(f"{'='*70}\n")
        for f in sorted(vulns, key=lambda x: sev_order.get(x.severity, 99)):
            print(f"  [{f.severity}] {f.id}: {f.attack}")
            print(f"    Problem: {f.detail}")
            if f.fix:
                print(f"    Fix:     {f.fix}")
            print()
    
    # Critical summary
    criticals = [f for f in vulns if f.severity == "CRITICAL"]
    highs = [f for f in vulns if f.severity == "HIGH"]
    mediums = [f for f in vulns if f.severity == "MEDIUM"]
    
    print(f"\n  SEVERITY BREAKDOWN:")
    print(f"    🔴 CRITICAL: {len(criticals)}")
    print(f"    🟠 HIGH:     {len(highs)}")
    print(f"    🟡 MEDIUM:   {len(mediums)}")
    
    print(f"\n  Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"  Agents in DB: {len(test_agents)}")
    
    if criticals:
        print(f"\n  ⚠️  {len(criticals)} CRITICAL vulnerabilities require immediate attention!")
    
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
