#!/usr/bin/env python3
"""
Karma Trust Protocol — Full Scenario Stress Test (500 Concurrent)
=================================================================
Simulates 500 concurrent agents executing the full Karma lifecycle:

Scenarios:
  1. Agent Registration (500 workers + 100 clients = 600 agents)
  2. Contract Creation (500 contracts)
  3. Receipt Submission (500×6 = 3000 receipts)
  4. Evidence Bundle Submission (500 bundles)
  5. Settlement Lifecycle (lock → submit → verify → release/refund/dispute)
  6. Reputation Query (500 concurrent reads)
  7. Private Risk Engine stress (500 risk checks)
  8. Mixed concurrent load (all endpoints simultaneously)

Metrics collected:
  - Latency (p50, p95, p99, max)
  - Throughput (req/s)
  - Error rate
  - Concurrent connection handling
"""

from __future__ import annotations

import asyncio
import json
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "http://localhost:8000"
RISK_ENGINE_BASE = "http://localhost:8822"
RISK_ENGINE_TOKEN = "private-dev-token"

CONCURRENCY = 500
TOTAL_AGENTS = 600  # 500 workers + 100 clients
TOTAL_CONTRACTS = 500
RECEIPTS_PER_TASK = 6
TOTAL_RECEIPTS = TOTAL_CONTRACTS * RECEIPTS_PER_TASK

# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_s(self) -> float:
        return self.end_time - self.start_time

    @property
    def throughput(self) -> float:
        return self.total_requests / max(self.duration_s, 0.001)

    @property
    def error_rate(self) -> float:
        return self.failed / max(self.total_requests, 1) * 100

    @property
    def p50(self) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        return s[len(s) // 2]

    @property
    def p95(self) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.95)]

    @property
    def p99(self) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        return s[int(len(s) * 0.99)]

    @property
    def max_latency(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0

    @property
    def avg_latency(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0

    def summary(self) -> dict:
        return {
            "scenario": self.name,
            "total_requests": self.total_requests,
            "successful": self.successful,
            "failed": self.failed,
            "error_rate_pct": round(self.error_rate, 2),
            "duration_s": round(self.duration_s, 2),
            "throughput_rps": round(self.throughput, 1),
            "latency_ms": {
                "avg": round(self.avg_latency, 1),
                "p50": round(self.p50, 1),
                "p95": round(self.p95, 1),
                "p99": round(self.p99, 1),
                "max": round(self.max_latency, 1),
            },
            "sample_errors": self.errors[:5],
        }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def timed_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    result: ScenarioResult,
    **kwargs,
) -> httpx.Response | None:
    t0 = time.perf_counter()
    try:
        resp = await client.request(method, url, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        result.latencies_ms.append(elapsed)
        result.total_requests += 1
        if resp.status_code < 400:
            result.successful += 1
        else:
            result.failed += 1
            if len(result.errors) < 20:
                result.errors.append(f"{resp.status_code}: {resp.text[:100]}")
        return resp
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        result.latencies_ms.append(elapsed)
        result.total_requests += 1
        result.failed += 1
        if len(result.errors) < 20:
            result.errors.append(f"Exception: {str(exc)[:100]}")
        return None


# ---------------------------------------------------------------------------
# Scenario 1: Agent Registration
# ---------------------------------------------------------------------------

async def scenario_register_agents(client: httpx.AsyncClient) -> tuple[ScenarioResult, list[str], list[str]]:
    result = ScenarioResult(name="1_agent_registration")
    worker_ids = []
    client_ids = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async def register_one(role: str, idx: int):
        async with sem:
            body = {
                "name": f"stress-{role}-{idx:04d}",
                "role": role,
                "endpoint_url": f"http://agent-{idx}.local:8080",
                "capabilities": ["caption", "translation", "qc"],
            }
            resp = await timed_request(client, "POST", f"{API_BASE}/v1/agents", result, json=body)
            if resp and resp.status_code == 201:
                data = resp.json()
                return data.get("agent_id")
            return None

    result.start_time = time.perf_counter()

    # Register 500 workers
    worker_tasks = [register_one("worker", i) for i in range(500)]
    # Register 100 clients
    client_tasks = [register_one("client", i) for i in range(100)]

    worker_results = await asyncio.gather(*worker_tasks)
    client_results = await asyncio.gather(*client_tasks)

    worker_ids = [r for r in worker_results if r]
    client_ids = [r for r in client_results if r]

    result.end_time = time.perf_counter()
    return result, worker_ids, client_ids


# ---------------------------------------------------------------------------
# Scenario 2: Contract Creation
# ---------------------------------------------------------------------------

async def scenario_create_contracts(
    client: httpx.AsyncClient,
    worker_ids: list[str],
    client_ids: list[str],
) -> tuple[ScenarioResult, list[str]]:
    result = ScenarioResult(name="2_contract_creation")
    task_ids = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async def create_one(idx: int):
        async with sem:
            deadline = (datetime.utcnow() + timedelta(hours=random.randint(1, 72))).isoformat()
            body = {
                "client_agent_id": random.choice(client_ids),
                "title": f"Stress Task #{idx:04d} - Caption Generation",
                "description": f"Generate captions for batch {idx} images",
                "expected_output_schema": {"type": "object"},
                "expected_step_count": RECEIPTS_PER_TASK,
                "escrow_amount": round(random.uniform(5.0, 500.0), 2),
                "currency": "USD",
                "deadline_at": deadline,
            }
            resp = await timed_request(client, "POST", f"{API_BASE}/v1/contracts", result, json=body)
            if resp and resp.status_code == 201:
                data = resp.json()
                return data.get("task_id")
            return None

    result.start_time = time.perf_counter()
    tasks = [create_one(i) for i in range(TOTAL_CONTRACTS)]
    results_list = await asyncio.gather(*tasks)
    task_ids = [r for r in results_list if r]
    result.end_time = time.perf_counter()
    return result, task_ids


# ---------------------------------------------------------------------------
# Scenario 3: Receipt Submission (bulk)
# ---------------------------------------------------------------------------

async def scenario_submit_receipts(
    client: httpx.AsyncClient,
    task_ids: list[str],
    worker_ids: list[str],
) -> ScenarioResult:
    result = ScenarioResult(name="3_receipt_submission")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def submit_one(task_id: str, step: int):
        async with sem:
            started = datetime.utcnow()
            duration = random.randint(50, 2000)
            ended = started + timedelta(milliseconds=duration)
            body = {
                "task_id": task_id,
                "agent_id": random.choice(worker_ids),
                "step_index": step,
                "tool_name": random.choice(["caption.generate", "caption.qc", "translate.run"]),
                "input_hash": uuid.uuid4().hex + uuid.uuid4().hex[:32],
                "output_hash": uuid.uuid4().hex + uuid.uuid4().hex[:32],
                "started_at": started.isoformat(),
                "ended_at": ended.isoformat(),
                "duration_ms": duration,
                "status": random.choices(["success", "failure", "timeout"], weights=[90, 8, 2])[0],
            }
            await timed_request(client, "POST", f"{API_BASE}/v1/receipts", result, json=body)

    result.start_time = time.perf_counter()
    all_tasks = []
    for task_id in task_ids:
        for step in range(1, RECEIPTS_PER_TASK + 1):
            all_tasks.append(submit_one(task_id, step))
    await asyncio.gather(*all_tasks)
    result.end_time = time.perf_counter()
    return result


# ---------------------------------------------------------------------------
# Scenario 4: Bundle Submission
# ---------------------------------------------------------------------------

async def scenario_submit_bundles(
    client: httpx.AsyncClient,
    task_ids: list[str],
) -> ScenarioResult:
    result = ScenarioResult(name="4_bundle_submission")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def submit_bundle(task_id: str):
        async with sem:
            num_steps = RECEIPTS_PER_TASK
            body = {
                "task_id": task_id,
                "task_contract_hash": uuid.uuid4().hex + uuid.uuid4().hex[:32],
                "receipt_ids": [str(uuid.uuid4()) for _ in range(num_steps)],
                "receipt_hashes": [uuid.uuid4().hex + uuid.uuid4().hex[:32] for _ in range(num_steps)],
                "final_result_hash": uuid.uuid4().hex + uuid.uuid4().hex[:32],
                "total_steps": num_steps,
                "successful_steps": num_steps - 1,
                "failed_steps": 1,
                "total_duration_ms": random.randint(500, 5000),
            }
            await timed_request(client, "POST", f"{API_BASE}/v1/bundles", result, json=body)

    result.start_time = time.perf_counter()
    tasks = [submit_bundle(tid) for tid in task_ids]
    await asyncio.gather(*tasks)
    result.end_time = time.perf_counter()
    return result


# ---------------------------------------------------------------------------
# Scenario 5: Settlement Lifecycle
# ---------------------------------------------------------------------------

async def scenario_settlement_lifecycle(
    client: httpx.AsyncClient,
    task_ids: list[str],
    client_ids: list[str],
    worker_ids: list[str],
) -> ScenarioResult:
    result = ScenarioResult(name="5_settlement_lifecycle")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def settle_one(task_id: str):
        async with sem:
            # Create settlement
            create_body = {
                "task_id": task_id,
                "client_agent_id": random.choice(client_ids),
                "escrow_amount": round(random.uniform(5.0, 500.0), 2),
                "currency": "USD",
            }
            await timed_request(
                client, "POST", f"{API_BASE}/v1/settlement/create", result, json=create_body
            )
            # Lock
            lock_body = {"worker_agent_id": random.choice(worker_ids)}
            await timed_request(
                client, "POST", f"{API_BASE}/v1/settlement/{task_id}/lock", result, json=lock_body
            )
            # Start
            await timed_request(
                client, "POST", f"{API_BASE}/v1/settlement/{task_id}/start", result
            )
            # Submit
            await timed_request(
                client, "POST", f"{API_BASE}/v1/settlement/{task_id}/submit", result
            )

    result.start_time = time.perf_counter()
    tasks = [settle_one(tid) for tid in task_ids]
    await asyncio.gather(*tasks)
    result.end_time = time.perf_counter()
    return result


# ---------------------------------------------------------------------------
# Scenario 6: Reputation Queries (read-heavy)
# ---------------------------------------------------------------------------

async def scenario_reputation_queries(
    client: httpx.AsyncClient,
    worker_ids: list[str],
) -> ScenarioResult:
    result = ScenarioResult(name="6_reputation_queries")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def query_one(agent_id: str):
        async with sem:
            await timed_request(client, "GET", f"{API_BASE}/v1/reputation/{agent_id}", result)

    result.start_time = time.perf_counter()
    # Query each worker's reputation (500 queries)
    tasks = [query_one(wid) for wid in worker_ids[:500]]
    await asyncio.gather(*tasks)

    # Also query leaderboard 100 times concurrently
    leaderboard_tasks = [
        timed_request(client, "GET", f"{API_BASE}/v1/reputation/leaderboard?limit=20", result)
        for _ in range(100)
    ]
    await asyncio.gather(*leaderboard_tasks)
    result.end_time = time.perf_counter()
    return result


# ---------------------------------------------------------------------------
# Scenario 7: Private Risk Engine Stress
# ---------------------------------------------------------------------------

async def scenario_risk_engine_stress(client: httpx.AsyncClient) -> ScenarioResult:
    result = ScenarioResult(name="7_risk_engine_stress")
    sem = asyncio.Semaphore(CONCURRENCY)
    headers = {"Authorization": f"Bearer {RISK_ENGINE_TOKEN}", "Content-Type": "application/json"}

    endpoints = [
        ("/risk/check", lambda: {
            "order": {
                "order_id": f"ord-{uuid.uuid4().hex[:8]}",
                "amount": round(random.uniform(1, 5000), 2),
                "currency": "USD",
                "seller_wallet": f"0x{uuid.uuid4().hex[:40]}",
                "buyer_wallet": f"0x{uuid.uuid4().hex[:40]}",
            },
            "evidence_bundle": {"steps": random.randint(1, 10)},
            "seller_stats": {"completed": random.randint(0, 200), "disputed": random.randint(0, 10)},
            "buyer_history": [],
        }),
        ("/score/seller", lambda: {
            "seller_wallet": f"0x{uuid.uuid4().hex[:40]}",
            "seller_stats": {
                "completed_bills": random.randint(1, 200),
                "timeout_rate": round(random.uniform(0, 0.1), 3),
                "dispute_rate": round(random.uniform(0, 0.05), 3),
            },
            "order_history": [{"amount": random.randint(10, 1000)} for _ in range(random.randint(1, 10))],
            "dispute_history": [],
            "evidence_quality": {"completeness": round(random.uniform(0.7, 1.0), 2)},
        }),
        ("/risk/buyer", lambda: {
            "buyer_wallet": f"0x{uuid.uuid4().hex[:40]}",
            "buyer_order_history": [{"amount": random.randint(5, 500)} for _ in range(random.randint(0, 20))],
            "buyer_dispute_history": [],
        }),
        ("/fraud/check", lambda: {
            "order": {
                "order_id": f"ord-{uuid.uuid4().hex[:8]}",
                "amount": round(random.uniform(1, 10000), 2),
                "seller_wallet": f"0x{uuid.uuid4().hex[:40]}",
                "buyer_wallet": f"0x{uuid.uuid4().hex[:40]}",
            },
            "evidence_bundle": {},
            "related_history": [],
        }),
    ]

    async def call_risk(endpoint: str, body_gen):
        async with sem:
            body = body_gen()
            await timed_request(
                client, "POST", f"{RISK_ENGINE_BASE}{endpoint}", result,
                json=body, headers=headers,
            )

    result.start_time = time.perf_counter()
    tasks = []
    for _ in range(500):
        ep, gen = random.choice(endpoints)
        tasks.append(call_risk(ep, gen))
    await asyncio.gather(*tasks)
    result.end_time = time.perf_counter()
    return result


# ---------------------------------------------------------------------------
# Scenario 8: Mixed Concurrent Load
# ---------------------------------------------------------------------------

async def scenario_mixed_load(
    client: httpx.AsyncClient,
    worker_ids: list[str],
    client_ids: list[str],
) -> ScenarioResult:
    result = ScenarioResult(name="8_mixed_concurrent_load")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def random_operation():
        async with sem:
            op = random.choice(["health", "list_agents", "register", "info", "leaderboard"])
            if op == "health":
                await timed_request(client, "GET", f"{API_BASE}/health", result)
            elif op == "list_agents":
                await timed_request(client, "GET", f"{API_BASE}/v1/agents", result)
            elif op == "register":
                body = {
                    "name": f"mixed-agent-{uuid.uuid4().hex[:8]}",
                    "role": random.choice(["worker", "client"]),
                    "capabilities": ["test"],
                }
                await timed_request(client, "POST", f"{API_BASE}/v1/agents", result, json=body)
            elif op == "info":
                await timed_request(client, "GET", f"{API_BASE}/v1/info", result)
            elif op == "leaderboard":
                await timed_request(client, "GET", f"{API_BASE}/v1/reputation/leaderboard?limit=10", result)

    result.start_time = time.perf_counter()
    tasks = [random_operation() for _ in range(1000)]
    await asyncio.gather(*tasks)
    result.end_time = time.perf_counter()
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 70)
    print("  KARMA TRUST PROTOCOL — FULL SCENARIO STRESS TEST")
    print(f"  Concurrency: {CONCURRENCY} | Target: {API_BASE}")
    print(f"  Started: {datetime.now().isoformat()}")
    print("=" * 70)

    limits = httpx.Limits(max_connections=600, max_keepalive_connections=200)
    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        all_results: list[ScenarioResult] = []

        # Scenario 1: Agent Registration
        print("\n[1/8] Agent Registration (600 agents, 500 concurrent)...")
        r1, worker_ids, client_ids = await scenario_register_agents(client)
        all_results.append(r1)
        print(f"  ✓ {r1.successful}/{r1.total_requests} OK | {r1.throughput:.0f} req/s | p95={r1.p95:.0f}ms")

        if not worker_ids or not client_ids:
            print("  ✗ FATAL: No agents registered, cannot continue")
            return

        # Scenario 2: Contract Creation
        print(f"\n[2/8] Contract Creation ({TOTAL_CONTRACTS} contracts, 500 concurrent)...")
        r2, task_ids = await scenario_create_contracts(client, worker_ids, client_ids)
        all_results.append(r2)
        print(f"  ✓ {r2.successful}/{r2.total_requests} OK | {r2.throughput:.0f} req/s | p95={r2.p95:.0f}ms")

        if not task_ids:
            print("  ✗ FATAL: No contracts created, cannot continue")
            return

        # Scenario 3: Receipt Submission
        print(f"\n[3/8] Receipt Submission ({len(task_ids)}×{RECEIPTS_PER_TASK} = {len(task_ids)*RECEIPTS_PER_TASK} receipts)...")
        r3 = await scenario_submit_receipts(client, task_ids, worker_ids)
        all_results.append(r3)
        print(f"  ✓ {r3.successful}/{r3.total_requests} OK | {r3.throughput:.0f} req/s | p95={r3.p95:.0f}ms")

        # Scenario 4: Bundle Submission
        print(f"\n[4/8] Bundle Submission ({len(task_ids)} bundles)...")
        r4 = await scenario_submit_bundles(client, task_ids)
        all_results.append(r4)
        print(f"  ✓ {r4.successful}/{r4.total_requests} OK | {r4.throughput:.0f} req/s | p95={r4.p95:.0f}ms")

        # Scenario 5: Settlement Lifecycle
        print(f"\n[5/8] Settlement Lifecycle ({len(task_ids)} full cycles)...")
        r5 = await scenario_settlement_lifecycle(client, task_ids, client_ids, worker_ids)
        all_results.append(r5)
        print(f"  ✓ {r5.successful}/{r5.total_requests} OK | {r5.throughput:.0f} req/s | p95={r5.p95:.0f}ms")

        # Scenario 6: Reputation Queries
        print("\n[6/8] Reputation Queries (600 reads, 500 concurrent)...")
        r6 = await scenario_reputation_queries(client, worker_ids)
        all_results.append(r6)
        print(f"  ✓ {r6.successful}/{r6.total_requests} OK | {r6.throughput:.0f} req/s | p95={r6.p95:.0f}ms")

        # Scenario 7: Risk Engine Stress
        print("\n[7/8] Private Risk Engine (500 risk checks, 500 concurrent)...")
        r7 = await scenario_risk_engine_stress(client)
        all_results.append(r7)
        print(f"  ✓ {r7.successful}/{r7.total_requests} OK | {r7.throughput:.0f} req/s | p95={r7.p95:.0f}ms")

        # Scenario 8: Mixed Load
        print("\n[8/8] Mixed Concurrent Load (1000 random ops, 500 concurrent)...")
        r8 = await scenario_mixed_load(client, worker_ids, client_ids)
        all_results.append(r8)
        print(f"  ✓ {r8.successful}/{r8.total_requests} OK | {r8.throughput:.0f} req/s | p95={r8.p95:.0f}ms")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  STRESS TEST SUMMARY")
    print("=" * 70)

    total_reqs = sum(r.total_requests for r in all_results)
    total_ok = sum(r.successful for r in all_results)
    total_fail = sum(r.failed for r in all_results)
    total_time = sum(r.duration_s for r in all_results)
    all_latencies = []
    for r in all_results:
        all_latencies.extend(r.latencies_ms)

    print(f"\n  Total Requests:     {total_reqs:,}")
    print(f"  Successful:         {total_ok:,} ({total_ok/max(total_reqs,1)*100:.1f}%)")
    print(f"  Failed:             {total_fail:,} ({total_fail/max(total_reqs,1)*100:.1f}%)")
    print(f"  Total Duration:     {total_time:.1f}s")
    print(f"  Avg Throughput:     {total_reqs/max(total_time,0.1):.0f} req/s")
    if all_latencies:
        all_latencies.sort()
        print(f"  Global Latency:")
        print(f"    avg:  {statistics.mean(all_latencies):.1f}ms")
        print(f"    p50:  {all_latencies[len(all_latencies)//2]:.1f}ms")
        print(f"    p95:  {all_latencies[int(len(all_latencies)*0.95)]:.1f}ms")
        print(f"    p99:  {all_latencies[int(len(all_latencies)*0.99)]:.1f}ms")
        print(f"    max:  {all_latencies[-1]:.1f}ms")

    print("\n  Per-Scenario Breakdown:")
    print(f"  {'Scenario':<30} {'Reqs':>6} {'OK%':>6} {'RPS':>8} {'p50':>7} {'p95':>7} {'p99':>7}")
    print(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7}")
    for r in all_results:
        ok_pct = r.successful / max(r.total_requests, 1) * 100
        print(f"  {r.name:<30} {r.total_requests:>6} {ok_pct:>5.1f}% {r.throughput:>7.0f} {r.p50:>6.0f}ms {r.p95:>6.0f}ms {r.p99:>6.0f}ms")

    # Write JSON report
    report = {
        "test_name": "karma_full_scenario_stress_test",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "concurrency": CONCURRENCY,
            "total_agents": TOTAL_AGENTS,
            "total_contracts": TOTAL_CONTRACTS,
            "receipts_per_task": RECEIPTS_PER_TASK,
            "api_base": API_BASE,
            "risk_engine_base": RISK_ENGINE_BASE,
        },
        "summary": {
            "total_requests": total_reqs,
            "successful": total_ok,
            "failed": total_fail,
            "success_rate_pct": round(total_ok / max(total_reqs, 1) * 100, 2),
            "total_duration_s": round(total_time, 2),
            "avg_throughput_rps": round(total_reqs / max(total_time, 0.1), 1),
            "global_latency_ms": {
                "avg": round(statistics.mean(all_latencies), 1) if all_latencies else 0,
                "p50": round(all_latencies[len(all_latencies)//2], 1) if all_latencies else 0,
                "p95": round(all_latencies[int(len(all_latencies)*0.95)], 1) if all_latencies else 0,
                "p99": round(all_latencies[int(len(all_latencies)*0.99)], 1) if all_latencies else 0,
                "max": round(all_latencies[-1], 1) if all_latencies else 0,
            },
        },
        "scenarios": [r.summary() for r in all_results],
        "verdict": "PASS" if total_fail / max(total_reqs, 1) < 0.05 else "FAIL",
    }

    report_path = "/Users/mac_02/.openclaw/workspaces/security-sentinel/reports/stress-test-500-result.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Report saved: {report_path}")

    verdict = "✅ PASS" if report["verdict"] == "PASS" else "❌ FAIL"
    print(f"\n  VERDICT: {verdict} (error threshold: <5%)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
