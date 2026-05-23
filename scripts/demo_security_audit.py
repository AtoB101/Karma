import json
"""
Security Compliance Demo — 运行 7 大安全标准检查并生成评分
"""
import asyncio
import sys, os, hashlib, uuid
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "packages", "karma_billing"))

from karma_billing.schema import (
    UniversalReceipt, ScenarioType, ReceiptType, ReceiptStatus, compute_payload_hash
)
from karma_billing.state_machine import ImmutableBillingStateMachine, InMemoryAuditLog
from karma_billing.state_transitions import BILLING_STATE_TRANSITIONS

sys.path.insert(0, os.path.join(PROJECT_ROOT, "packages", "karma_security"))
from karma_security import SecurityAuditor


def make_receipt(rid, task_id, step, rtype, buyer, seller, parent=None):
    inp = f"input-{rid}"
    out = f"output-{rid}"
    r = UniversalReceipt(
        receipt_id=rid, task_id=task_id, scenario=ScenarioType.S1_DELEGATION,
        step_index=step, generator_did=seller, buyer_did=buyer, seller_did=seller,
        receipt_type=rtype.value,
        input_hash=hashlib.sha256(inp.encode()).hexdigest(),
        output_hash=hashlib.sha256(out.encode()).hexdigest(),
        payload_hash="",
        created_at=datetime.now(timezone.utc),
        execution_duration_ms=50, parent_receipt_id=parent,
        scenario_data={"step": step},
        status=ReceiptStatus.GENERATED,
        signature=f"ed25519:{hashlib.sha256(f'{rid}'.encode()).hexdigest()[:32]}",
    )
    r._auto_compute_payload_hash()
    return r


async def main():
    task_id = "sec-demo-" + str(uuid.uuid4())[:8]
    buyer, seller = "buyer-sec", "seller-sec"

    print("\n" + "=" * 70)
    print("  🛡️  KARMA SECURITY COMPLIANCE AUDITOR")
    print("  7 Standards · 25 Rules · Fully Automated")
    print("=" * 70)

    # ── Generate test data ─────────────────────────────────────────
    receipts = []
    audit = InMemoryAuditLog()
    sm = ImmutableBillingStateMachine(audit_log=audit)

    # S1 flow: 8 receipts
    types = [
        ReceiptType.S1_INTENT_CREATED,
        ReceiptType.S1_DELEGATION_ACCEPTED,
        ReceiptType.S1_TASK_STARTED,
        ReceiptType.S1_STEP_EXECUTED,
        ReceiptType.S1_STEP_EXECUTED,
        ReceiptType.S1_STEP_EXECUTED,
        ReceiptType.S1_TASK_COMPLETED,
        ReceiptType.S1_PAYMENT_SETTLED,
    ]

    prev_id = None
    for i, rt in enumerate(types, 1):
        rid = f"rec-sec-{i}"
        r = make_receipt(rid, task_id, i, rt, buyer, seller, parent=prev_id)
        receipts.append(r.model_dump(mode="json"))
        prev_id = rid

    # State history
    states = ["INITIATED", "INTENT_RECEIVED", "DELEGATION_ACCEPTED",
              "TASK_STARTED", "STEP_IN_PROGRESS", "STEP_COMPLETED",
              "TASK_COMPLETED", "SETTLED"]
    state_history = []
    for i in range(1, len(states)):
        state_history.append({
            "record_id": f"st-{i}",
            "from_state": states[i-1],
            "to_state": states[i],
            "timestamp": datetime.now(timezone.utc).timestamp(),
        })

    # Anchor logs
    now = datetime.now(timezone.utc).timestamp()
    anchor_logs = [
        {"timestamp": now, "confirmation_ms": 400, "tx": "5K1..."},
        {"timestamp": now + 5, "confirmation_ms": 380, "tx": "5K2..."},
        {"timestamp": now + 10, "confirmation_ms": 420, "tx": "5K3..."},
        {"timestamp": now + 15, "confirmation_ms": 390, "tx": "5K4..."},
    ]

    # ── Run audit ──────────────────────────────────────────────────
    auditor = SecurityAuditor()
    report = auditor.audit(
        receipts=receipts,
        state_history=state_history,
        anchor_logs=anchor_logs,
        escrow_functions=["deposit", "release", "refund", "freeze"],
        state_machine_class=ImmutableBillingStateMachine,
        transition_table=BILLING_STATE_TRANSITIONS,
        amount_usdc=50.00,
        verification_count=1,
        scenario_types={"S1_DELEGATION", "S8_DISPUTE"},
    )

    print(report.summary())
    print(f"\n📋 JSON Report: {json.dumps(report.to_dict(), indent=2, default=str)[:500]}...")

    return report


if __name__ == "__main__":
    report = asyncio.run(main())
    if report.criticals > 0:
        sys.exit(1)
    sys.exit(0)
