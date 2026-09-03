"""Karma E2E smoke gate (off-chain, dev mode) against a running API.

One command: python scripts/e2e_smoke.py

Coverage:
  happy path  : contract -> settlement lifecycle -> receipt -> buyer-accept -> settled
  payment code: create
  dispute + arbitration closed loop: capacity lock -> voucher accept -> dispute
                -> pool join x3 -> case create -> assign-auto -> vote x3 -> execute -> refunded

Identities are seeded via /v1/identities/{id}/profile/init, so a fresh DB works.
Two buyers keep capacity state clean: one without capacity (settle happy path),
one with capacity (payment-code + dispute/arbitration).

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


def seed_identity(identity_id: str) -> None:
    """Ensure an identity exists (idempotent; fresh-DB safe)."""
    httpx.post(f"{BASE}/v1/identities/{identity_id}/profile/init", json={}, timeout=15)


def main():
    h = "aa" * 32
    deadline = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()

    seller = "kid_e2e_seller_" + uuid.uuid4().hex[:8]
    seed_identity(seller)

    # ---- Happy path: buyer WITHOUT capacity (buyer-accept short-circuits on no capacity row) ----
    buyer_happy = "kid_e2e_happy_" + uuid.uuid4().hex[:8]
    seed_identity(buyer_happy)
    tid = "e2e-smoke-" + uuid.uuid4().hex[:8]
    step("contract.create", httpx.post(f"{BASE}/v1/contracts", json={
        "task_id": tid, "client_agent_id": buyer_happy, "title": "E2E smoke",
        "description": "x", "expected_output_schema": {}, "expected_step_count": 2,
        "escrow_amount": 5.0, "currency": "USD", "deadline_at": deadline,
    }, timeout=15))
    step("settle.create", httpx.post(f"{BASE}/v1/settlement/create", json={
        "task_id": tid, "client_agent_id": buyer_happy, "escrow_amount": 5.0,
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

    # ---- Buyer WITH capacity (payment-code + dispute/arbitration) ----
    buyer = "kid_e2e_credit_" + uuid.uuid4().hex[:8]
    seed_identity(buyer)
    step("capacity.lock", httpx.post(f"{BASE}/v1/capacity/{buyer}/lock",
         json={"amount": 30.0}, timeout=15))

    # payment code
    step("payment-code.create", httpx.post(f"{BASE}/v1/payment-codes", json={
        "buyer_identity_id": buyer, "seller_identity_id": seller,
        "amount": 2.0, "bill_credit_amount": 2.0, "currency": "USDC",
        "task_type": "api.smoke", "task_description_hash": h,
        "progress_rule_hash": h, "evidence_requirement_hash": h,
        "buyer_signature": "0xtest", "payment_mode": "manual", "ttl_seconds": 3600,
    }, timeout=15))

    # dispute + arbitration closed loop
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

    # arbitration pool: 3 arbitrators join
    arb_ids = [f"arb-{i}-{uuid.uuid4().hex[:4]}" for i in range(3)]
    for a in arb_ids:
        step(f"arb.pool.join.{a[:6]}", httpx.post(f"{BASE}/v1/arbitration/pool/join", json={
            "arbitrator_identity_id": a, "stake_amount": 0.0}, timeout=15))
    case = step("arb.case.create", httpx.post(f"{BASE}/v1/arbitration/cases", json={
        "task_id": tid2, "opened_by": buyer, "reason": "smoke arbitration",
        "required_arbitrators": 3}, timeout=15))
    cid = case.get("case_id") if case else None
    assign = step("arb.assign-auto", httpx.post(f"{BASE}/v1/arbitration/cases/{cid}/assign-auto",
         json={"count": 3}, timeout=15))
    assigned = [a["arbitrator_identity_id"] for a in assign] if isinstance(assign, list) else []
    for a in assigned:
        step(f"arb.vote.{a[:6]}", httpx.post(f"{BASE}/v1/arbitration/cases/{cid}/vote", json={
            "arbitrator_identity_id": a, "decision": "buyer_wins"}, timeout=15))
    execd = step("arb.execute", httpx.post(f"{BASE}/v1/arbitration/cases/{cid}/execute", json={}, timeout=15))
    if execd and execd.get("status") != "refunded":
        FAILURES.append("arb.execute.status")
        print(f"      expected status=refunded, got {execd.get('status')}")

    if FAILURES:
        print(f"\nRESULT: FAIL ({len(FAILURES)} step(s)): {FAILURES}")
        sys.exit(1)
    print("\nRESULT: ALL GREEN — off-chain E2E smoke passed")


if __name__ == "__main__":
    main()
