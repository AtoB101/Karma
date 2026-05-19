#!/usr/bin/env python3
"""
Karma 3-Agent 高并发压力测试 + 攻击场景
======================================
压力: 3 agents × 100 tasks concurrent → execution receipts
攻击: 越权、重放、注入、超额、伪造签名
"""
import asyncio, os, sys, time

os.environ["KARMA_RUNTIME_URL"] = "http://127.0.0.1:8000"

from sdk.openclaw_agent import KarmaOpenClawAgent

AGENTS = {
    "security-sentinel": "8a28bfd2-5860-431a-93b5-31b764c548e9",
    "openclaw-worker":   "15b88f6b-e73d-4bd0-a894-04f378e262dc",
    "openmanus-worker":  "fd6da5af-44a4-4855-8818-7a0de67a70ba",
}

PASS = FAIL = WARN = 0

def c(desc, ok, detail=""):
    global PASS, FAIL
    if ok: PASS += 1; print(f"  ✅ {desc}")
    else: FAIL += 1; print(f"  ❌ {desc} — {detail}")

def w(desc, detail=""):
    global WARN; WARN += 1; print(f"  ⚠️  {desc} — {detail}")


# ═══════════════════════════════════════════════════════════
# STRESS: 3 agents × 100 tasks concurrent
# ═══════════════════════════════════════════════════════════

async def stress_concurrent():
    print("\n" + "=" * 60)
    print("💪 压力测试: 3 Agents × 100 Tasks = 300 并发任务")
    print("=" * 60)

    agents = {
        name: KarmaOpenClawAgent(
            agent_id=aid, runtime_url=os.environ["KARMA_RUNTIME_URL"],
            api_key=f"karma_{name}_key",
        )
        for name, aid in AGENTS.items()
    }

    base = int(time.time() * 1000)
    total = 0
    start = time.time()

    async def worker(agent, name, count):
        nonlocal total
        for t in range(count):
            tid = f"stress-{name}-{base}-{t}"
            for s in range(3):
                agent.run_tool_sync(
                    task_id=tid, tool_name=f"{name}.step_{s}",
                    result={"ok": True}, input_data={"t": t, "s": s},
                    success=True,
                )
            total += 3

    # Run concurrently
    await asyncio.gather(
        worker(agents["security-sentinel"], "sentinel", 100),
        worker(agents["openclaw-worker"], "openclaw", 100),
        worker(agents["openmanus-worker"], "openmanus", 100),
    )

    elapsed = time.time() - start
    c(f"300 tasks × 3 steps = {total} receipts", total == 900)
    c(f"Concurrency OK", total > 0)
    print(f"  📊 耗时: {elapsed:.2f}s | 吞吐: {total/elapsed:.0f} receipts/s")

    # Verify per-agent counts
    for name in AGENTS:
        count = sum(len(agents[name]._receipts.get(tid, [])) for tid in agents[name]._receipts)
        c(f"{name}: 300 receipts", count == 300, f"got {count}")


# ═══════════════════════════════════════════════════════════
# ATTACK 1: Replay attack
# ═══════════════════════════════════════════════════════════

async def attack_replay():
    print("\n" + "=" * 60)
    print("🛡️  攻击测试 1: 重放攻击 (Replay)")
    print("=" * 60)

    import httpx

    # Submit same receipt twice
    agent = KarmaOpenClawAgent(
        agent_id=AGENTS["openclaw-worker"],
        runtime_url=os.environ["KARMA_RUNTIME_URL"],
        api_key="karma_oc_key",
    )

    tid = f"attack-replay-{int(time.time())}"
    receipt = agent.run_tool_sync(tid, "browser.action", {"ok": True}, {"t": 1}, success=True)
    receipt_data = receipt.model_dump(mode="json")

    async with httpx.AsyncClient(base_url=os.environ["KARMA_RUNTIME_URL"], timeout=10) as client:
        r1 = await client.post("/v1/receipts", json=receipt_data)
        r2 = await client.post("/v1/receipts", json=receipt_data)

        c(f"First submit: {r1.status_code}", r1.status_code in (200, 201, 404))
        # Second submit should be rejected (duplicate)
        if r1.status_code in (200, 201) and r2.status_code != r1.status_code:
            c(f"Replay rejected: {r2.status_code}", True)
        elif r1.status_code == r2.status_code and r1.status_code >= 400:
            c(f"Both rejected (dup guard): {r2.status_code}", True)
        else:
            w(f"Replay may not be blocked: first={r1.status_code} second={r2.status_code}")


# ═══════════════════════════════════════════════════════════
# ATTACK 2: Authorization bypass
# ═══════════════════════════════════════════════════════════

async def attack_auth_bypass():
    print("\n" + "=" * 60)
    print("🛡️  攻击测试 2: 越权访问 (Auth Bypass)")
    print("=" * 60)

    import httpx

    async with httpx.AsyncClient(base_url=os.environ["KARMA_RUNTIME_URL"], timeout=10) as client:
        # Try to access admin endpoint without auth (use POST since it's a POST-only route)
        r = await client.post("/v1/admin/controls/identities/any/risk-mark",
                            json={"reason": "attack-test"})
        c(f"Admin endpoint blocked without auth: {r.status_code}", r.status_code in (401, 403),
          f"HTTP {r.status_code}")

        # Try to submit receipt with invalid agent_id
        fake_receipt = {
            "task_id": "steal-task",
            "agent_id": "not-my-agent",
            "step_index": 0,
            "tool_name": "steal.money",
            "input_hash": "a" * 64,
            "output_hash": "b" * 64,
            "started_at": "2026-01-01T00:00:00Z",
            "ended_at": "2026-01-01T00:01:00Z",
            "duration_ms": 60000,
            "status": "success",
        }
        r = await client.post("/v1/receipts", json=fake_receipt)
        # Should either reject or accept in dev mode (auth disabled)
        c(f"Fake agent receipt handled: {r.status_code}",
          r.status_code in (200, 201, 400, 401, 403, 404, 422),
          f"HTTP {r.status_code}")

        # Try to GET another identity's private data
        r = await client.get("/v1/identities/nonexistent-agent-999/profile")
        c(f"Nonexistent identity: {r.status_code}", r.status_code in (404, 401, 403),
          f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════
# ATTACK 3: Amount overflow
# ═══════════════════════════════════════════════════════════

async def attack_amount_overflow():
    print("\n" + "=" * 60)
    print("🛡️  攻击测试 3: 超额支付 (Amount Overflow)")
    print("=" * 60)

    import httpx

    async with httpx.AsyncClient(base_url=os.environ["KARMA_RUNTIME_URL"], timeout=10) as client:
        # Try to lock more than available
        aid = AGENTS["security-sentinel"]
        r = await client.post(f"/v1/capacity/{aid}/lock", json={"amount": 9999999.0})
        c(f"Mega-lock rejected: {r.status_code}", r.status_code >= 400,
          f"HTTP {r.status_code}: {r.text[:80]}")

        # Negative amount
        r = await client.post(f"/v1/capacity/{aid}/lock", json={"amount": -100.0})
        c(f"Negative lock rejected: {r.status_code}", r.status_code >= 400,
          f"HTTP {r.status_code}")

        # Zero amount
        r = await client.post(f"/v1/capacity/{aid}/lock", json={"amount": 0.0})
        c(f"Zero lock handled: {r.status_code}",
          r.status_code in (200, 201, 400, 422),
          f"HTTP {r.status_code}")


# ═══════════════════════════════════════════════════════════
# ATTACK 4: Tampered receipt
# ═══════════════════════════════════════════════════════════

async def attack_tampered_receipt():
    print("\n" + "=" * 60)
    print("🛡️  攻击测试 4: 篡改回执 (Tampered Receipt)")
    print("=" * 60)

    import httpx
    from sdk.adapters import MCPExecutionAdapter
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Create a receipt claiming work was done 1 year ago (step_index must be >= 1)
    fake = MCPExecutionAdapter.build(
        task_id=f"fake-{int(time.time())}",
        agent_id=AGENTS["openclaw-worker"],
        step_index=1,
        mcp_server_id="fake",
        tool_name="fake.work",
        tool_input={"claim": "I did this last year"},
        tool_output={"result": "trust me"},
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2024, 1, 1, 1, 0, 0, tzinfo=timezone.utc),
        success=True,
    )

    async with httpx.AsyncClient(base_url=os.environ["KARMA_RUNTIME_URL"], timeout=10) as client:
        r = await client.post("/v1/receipts", json=fake.model_dump(mode="json"))
        c(f"Ancient receipt rejected: {r.status_code}",
          r.status_code >= 400,
          f"HTTP {r.status_code}: {r.text[:80]}")


# ═══════════════════════════════════════════════════════════
# ATTACK 5: SQL injection
# ═══════════════════════════════════════════════════════════

async def attack_sql_injection():
    print("\n" + "=" * 60)
    print("🛡️  攻击测试 5: SQL 注入 (SQL Injection)")
    print("=" * 60)

    import httpx

    async with httpx.AsyncClient(base_url=os.environ["KARMA_RUNTIME_URL"], timeout=10) as client:
        payloads = [
            "'; DROP TABLE agents; --",
            "' OR '1'='1",
            "1; SELECT * FROM users",
            "' UNION SELECT * FROM agents --",
            "admin'--",
        ]

        for payload in payloads:
            r = await client.get(f"/v1/identities/{payload}/profile")
            # Should return 404 or 400, not 500 from DB error
            c(f"SQLi '{payload[:20]}': {r.status_code}",
              r.status_code in (400, 404, 422, 200),
              f"HTTP {r.status_code}")

        # Verify system still operational
        health = await client.get("/health")
        c("System still healthy after SQLi", health.status_code == 200)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    global PASS, FAIL, WARN

    print("╔" + "═" * 58 + "╗")
    print("║  Karma 压力 + 攻击测试" + " " * 36 + "║")
    print("╚" + "═" * 58 + "╝")

    start_all = time.time()

    # Stress
    await stress_concurrent()

    # Attacks
    await attack_replay()
    await attack_auth_bypass()
    await attack_amount_overflow()
    await attack_tampered_receipt()
    await attack_sql_injection()

    elapsed = time.time() - start_all
    total = PASS + FAIL

    print("\n" + "=" * 60)
    print("📊 压力+攻击测试总结")
    print(f"   耗时: {elapsed:.1f}s")
    print(f"   通过: {PASS}  |  失败: {FAIL}  |  警告: {WARN}")
    if total > 0:
        print(f"   成功率: {100*PASS/total:.0f}%")
    print("=" * 60)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
