"""Karma E2E smoke gate (off-chain, dev mode) against a running API.

One command: python scripts/e2e_smoke.py

Happy path (no capacity enforcement): contract -> settlement lifecycle -> receipt -> buyer-accept -> settled.
Dispute path (capacity + voucher): capacity lock -> contract -> voucher accept -> settle -> dispute -> disputed.

Exit 0 = all green; exit 1 = failure (prints which step).
"""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

BASE = "http://127.0.0.1:8000"
FAILURES = []


def step(name, r, want=(200, 201)):
    ok = r.status_code in want
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    if not ok:
        FAILURES.append(name)
        print(f"[FAIL] {name}: HTTP {r.status_code}  {json.dumps(body, ensure_ascii=False)[:400]}")
    else:
        print(f"[PASS] {name}: HTTP {r.status_code}")
    return body if ok else None


def main():
    buyer = "kid_6458cbab317b7835417ab371"
    seller = "kid_1c9ed7fab7d8affdb41b8b47"
    h = "aa" * 32
    deadline = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()

    # ---- Happy path: settlement full lifecycle (no capacity row -> dev leniency) ----
    tid = "e2e-smoke-" + uuid.uuid4().hex[:8]
    step("contract.create", httpx.post(f"{BASE}/v1/contracts", json={
        "task_id": tid, "client_agent_id": buyer, "title": "E2E smoke",
        "description": "x", "expected_output_schema": {}, "expected_step_count": 2,
        "escrow_amount": 5.0, "currency": "USD", "deadline_at": deadline,
    }, timeout=15))
    step("settle.create", httpx.post(f"{BASE}/v1/settlement/create", json={
        "task_id": tid, "client_agent_id": buyer, "escrow_amount": 5.0,
        "currency": "USD", "worker_agent_id": seller,
    }, timeout=15))
    step("settle.pending", httpx.post(f"{BASE}/v1/settlement/{tid}/pending", json={}, timeout=15))
    step("settle.lock", httpx.post(f"{BASE}/v1/settlement/{tid}/lock",
         json={"worker_agent_id": seller}, timeout=15))
    step("settle.start", httpx.post(f"{BASE}/v1/settlement/{tid}/start", json={}, timeout=15))
    step("settle.submit", httpx.post(f"{BASE}/v1/settlement/{tid}/submit", json={}, timeout=15))

    from core.schemas import ExecutionReceipt, ToolStatus
    from services.signing import signing_service
    now = datetime.now(timezone.utc)
    rc = ExecutionReceipt(task_id=tid, agent_id=seller, step_index=1, tool_name="smoke.step",
                          input_hash="a" * 64, output_hash="b" * 64,
                          started_at=now, ended_at=now + timedelta(milliseconds=50),
                          duration_ms=50, status=ToolStatus.SUCCESS)
    rc.signature = signing_service.sign_receipt(rc)
    step("receipt.create", httpx.post(f"{BASE}/v1/receipts", json=rc.model_dump(mode="json"), timeout=15))

    settled = step("settle.buyer-accept", httpx.post(f"{BASE}/v1/settlement/{tid}/buyer-accept", json={}, timeout=15))
    if settled and settled.get("status") != "settled":
        FAILURES.append("settle.buyer-accept.status")
        print(f"      expected status=settled, got {settled.get('status')}")

    # ---- Payment code ----
    step("payment-code.create", httpx.post(f"{BASE}/v1/payment-codes", json={
        "buyer_identity_id": buyer, "seller_identity_id": seller,
        "amount": 2.0, "bill_credit_amount": 2.0, "currency": "USDC",
        "task_type": "api.smoke", "task_description_hash": h,
        "progress_rule_hash": h, "evidence_requirement_hash": h,
        "buyer_signature": "0xtest", "payment_mode": "manual", "ttl_seconds": 3600,
    }, timeout=15))

    # ---- Dispute path (capacity + voucher) ----
    step("capacity.lock", httpx.post(f"{BASE}/v1/capacity/{buyer}/lock",
         json={"amount": 30.0}, timeout=15))
    tid2 = "e2e-smoke-disp-" + uuid.uuid4().hex[:8]
    step("dispute.contract", httpx.post(f"{BASE}/v1/contracts", json={
        "task_id": tid2, "client_agent_id": buyer, "title": "smoke dispute",
        "description": "x", "expected_output_schema": {}, "expected_step_count": 3,
        "escrow_amount": 8.0, "currency": "USD", "deadline_at": deadline,
    }, timeout=15))
    vbody = {
        "buyer_identity_id": buyer, "seller_identity_id": seller, "amount": 8.0,
        "bill_credit_amount": 8.0, "task_type": "smoke.dispute",
        "task_description_hash": h, "progress_rule_hash": h, "evidence_requirement_hash": h,
        "expiry_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "nonce": "smoke-d-" + uuid.uuid4().hex[:6], "buyer_signature": "0x" + "11" * 65,
        "currency": "USDC",
    }
    vres = step("dispute.voucher", httpx.post(f"{BASE}/v1/vouchers", json=vbody, timeout=15))
    vid = vres.get("voucher_id") if vres else None
    step("dispute.voucher.accept", httpx.post(f"{BASE}/v1/vouchers/{vid}/accept",
         json={"seller_identity_id": seller}, timeout=15))
    step("dispute.settle.create", httpx.post(f"{BASE}/v1/settlement/create", json={
        "task_id": tid2, "client_agent_id": buyer, "escrow_amount": 8.0,
        "currency": "USD", "voucher_id": vid,
    }, timeout=15))
    step("dispute.settle.lock", httpx.post(f"{BASE}/v1/settlement/{tid2}/lock",
         json={"worker_agent_id": seller}, timeout=15))
    disp = step("dispute.open", httpx.post(f"{BASE}/v1/settlement/{tid2}/dispute", json={
        "reason": "smoke dispute", "reason_code": "QUALITY_OBJECTIVE_FAIL",
    }, timeout=15))
    if disp and disp.get("status") != "disputed":
        FAILURES.append("dispute.open.status")
        print(f"      expected status=disputed, got {disp.get('status')}")

    step("arbitration.pool", httpx.get(f"{BASE}/v1/arbitration/pool", timeout=15))

    if FAILURES:
        print(f"\nRESULT: FAIL ({len(FAILURES)} step(s)): {FAILURES}")
        sys.exit(1)
    print("\nRESULT: ALL GREEN — off-chain E2E smoke passed")


if __name__ == "__main__":
    main()
