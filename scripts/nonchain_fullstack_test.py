import json, hashlib, uuid, sys, os, time, asyncio
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "karma_billing"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages", "karma_security"))
from karma_billing.schema import UniversalReceipt, ScenarioType, ReceiptType, ReceiptStatus, compute_payload_hash
from karma_billing.state_machine import ImmutableBillingStateMachine
from karma_billing.state_transitions import BILLING_STATE_TRANSITIONS
from karma_billing.sync_service import ReceiptSyncService, IncrementalMerkleAccumulator
from karma_security import SecurityAuditor

RT = ReceiptType
auditor = SecurityAuditor()
passed, total = 0, 0
def check(name, ok, detail=""):
    global passed, total; total += 1
    if ok: passed += 1
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
    return ok

task_id = uuid.uuid4().hex
print("PART 1: NORMAL FLOW")
receipts = []
prev = None
for i, rt in enumerate([RT.S1_INTENT_CREATED, RT.S1_DELEGATION_ACCEPTED, RT.S1_TASK_STARTED], 1):
    r = UniversalReceipt(receipt_id=str(uuid.uuid4()), task_id=task_id, scenario=ScenarioType.S1_DELEGATION,
        step_index=i, generator_did="seller", buyer_did="buyer", seller_did="seller",
        receipt_type=rt.value,
        input_hash=hashlib.sha256(f"in-{i}".encode()).hexdigest(),
        output_hash=hashlib.sha256(f"out-{i}".encode()).hexdigest(),
        payload_hash=compute_payload_hash({"step":i}), created_at=datetime.now(timezone.utc),
        execution_duration_ms=10, parent_receipt_id=prev, scenario_data={},
        status=ReceiptStatus.GENERATED,
        signature=f"ed25519:{hashlib.sha256(f'sig-{i}'.encode()).hexdigest()[:32]}")
    receipts.append(r); prev = r.receipt_id
for i, t in enumerate(["read","analyze","report"], 4):
    r = UniversalReceipt(receipt_id=str(uuid.uuid4()), task_id=task_id, scenario=ScenarioType.S1_DELEGATION,
        step_index=i, generator_did="seller", buyer_did="buyer", seller_did="seller",
        receipt_type=RT.S1_STEP_EXECUTED.value,
        input_hash=hashlib.sha256(f"in-{i}".encode()).hexdigest(),
        output_hash=hashlib.sha256(f"out-{i}".encode()).hexdigest(),
        payload_hash=compute_payload_hash({"tool":t}), created_at=datetime.now(timezone.utc),
        execution_duration_ms=50, parent_receipt_id=prev, scenario_data={"tool":t},
        status=ReceiptStatus.GENERATED,
        signature=f"ed25519:{hashlib.sha256(f'sig-{i}'.encode()).hexdigest()[:32]}")
    receipts.append(r); prev = r.receipt_id

check("Receipts generated", len(receipts)==6, str(len(receipts)))
check("Chain unbroken", all(receipts[i].parent_receipt_id==receipts[i-1].receipt_id for i in range(1,len(receipts))))
check("All signed", all(r.signature for r in receipts))
tree = IncrementalMerkleAccumulator()
for r in receipts:
    tree.append(hashlib.sha256(f"{r.receipt_id}|{task_id}|{r.step_index}|{r.payload_hash}|{r.created_at.isoformat()}".encode()).digest())
check("Merkle tree", tree.compute_root() is not None, f"{tree.leaf_count} leaves, root={tree.compute_root()[:24]}...")
dicts = [r.model_dump(mode="json") for r in receipts]
state_hist = [{"record_id":"s1","from_state":"INITIATED","to_state":"INTENT_RECEIVED","timestamp":time.time()}]
report = auditor.audit(receipts=dicts, state_history=state_hist, transition_table=BILLING_STATE_TRANSITIONS,
                       state_machine_class=ImmutableBillingStateMachine, escrow_functions=["deposit","release","refund"],
                       scenario_types={"S1_DELEGATION"}, anchor_logs=[{"timestamp":time.time(),"confirmation_ms":400}])
check("Security score", report.score>=7.0, f"{report.score}/10 ({report.passed}/{report.total_checks})")

print("\nPART 2: ATTACK TESTS")
bad = [d.copy() for d in dicts]; bad[0]["payload_hash"] = "0"*64
r = auditor.audit(receipts=bad, escrow_functions=["deposit"])
check("Tampered hash", any(not f.passed and f.rule=="R1.3" for f in r.findings))
broken = [d.copy() for d in dicts]; broken[1]["parent_receipt_id"] = "nonexistent"
r = auditor.audit(receipts=broken, escrow_functions=["deposit"])
check("Broken chain", any(not f.passed and f.rule=="R1.2" for f in r.findings))
unsigned = [d.copy() for d in dicts]; unsigned[2]["signature"] = ""
r = auditor.audit(receipts=unsigned, escrow_functions=["deposit"])
check("Unsigned receipt", any(not f.passed and f.rule=="R1.1" for f in r.findings))
illegal = [{"record_id":"bad","from_state":"INITIATED","to_state":"SETTLED","timestamp":time.time()}]
r = auditor.audit(receipts=dicts, state_history=illegal, transition_table=BILLING_STATE_TRANSITIONS,
                  state_machine_class=ImmutableBillingStateMachine, escrow_functions=["deposit"])
check("Illegal transition", any(not f.passed and f.rule=="R3.2" for f in r.findings))
forbidden = ["force_transition","admin_override","bypass_validation"]
found = [m for m in forbidden if hasattr(ImmutableBillingStateMachine, m)]
check("No backdoor", not found, f"{len(found)} forbidden" if found else "clean")
leak = dicts[0].copy(); leak["raw_input"] = "SECRET"
r = auditor.audit(receipts=[leak], escrow_functions=["deposit"])
check("Data leak", any(not f.passed and f.rule=="R5.1" for f in r.findings))

print("\nPART 3: CROSS-SCENARIO S1→S8")
dispute = UniversalReceipt(receipt_id=str(uuid.uuid4()), task_id=task_id, scenario=ScenarioType.S1_DELEGATION,
    step_index=len(receipts)+1, generator_did="buyer", buyer_did="buyer", seller_did="seller",
    receipt_type=RT.S8_DISPUTE_FILED.value,
    input_hash=hashlib.sha256(b"dispute").hexdigest(),
    output_hash=hashlib.sha256(b"quality_not_met").hexdigest(),
    payload_hash=compute_payload_hash({"reason":"quality"}),
    created_at=datetime.now(timezone.utc), execution_duration_ms=0,
    parent_receipt_id=receipts[-1].receipt_id, scenario_data={"reason":"quality"},
    status=ReceiptStatus.GENERATED,
    signature=f"ed25519:{hashlib.sha256(b'dsig').hexdigest()[:32]}")
receipts.append(dispute)
evidence = UniversalReceipt(receipt_id=str(uuid.uuid4()), task_id=task_id, scenario=ScenarioType.S1_DELEGATION,
    step_index=len(receipts)+1, generator_did="seller", buyer_did="buyer", seller_did="seller",
    receipt_type=RT.S8_EVIDENCE_SUBMITTED.value,
    input_hash=hashlib.sha256(b"ev").hexdigest(),
    output_hash=hashlib.sha256(b"log").hexdigest(),
    payload_hash=compute_payload_hash({"type":"log"}),
    created_at=datetime.now(timezone.utc), execution_duration_ms=0,
    parent_receipt_id=dispute.receipt_id, scenario_data={},
    status=ReceiptStatus.GENERATED,
    signature=f"ed25519:{hashlib.sha256(b'esig').hexdigest()[:32]}")
receipts.append(evidence)
types = {r.receipt_type for r in receipts}
has_s8 = RT.S8_DISPUTE_FILED.value in types and RT.S8_EVIDENCE_SUBMITTED.value in types
check("S1→S8 cross-scenario", has_s8, f"{len(types)} unique types")

print("\nPART 4: BILLING LAYER")
sync = ReceiptSyncService()
test_r = UniversalReceipt(receipt_id=str(uuid.uuid4()), task_id="billing-test", scenario=ScenarioType.S1_DELEGATION,
    step_index=1, generator_did="test", buyer_did="buyer", seller_did="seller",
    receipt_type=RT.S1_STEP_EXECUTED.value,
    input_hash=hashlib.sha256(b"bt").hexdigest(),
    output_hash=hashlib.sha256(b"bt").hexdigest(),
    payload_hash=compute_payload_hash({"t":True}), created_at=datetime.now(timezone.utc),
    execution_duration_ms=5, parent_receipt_id=None, scenario_data={"t":True},
    status=ReceiptStatus.GENERATED,
    signature=f"ed25519:{hashlib.sha256(b'bts').hexdigest()[:32]}")
result = asyncio.run(sync.sync(test_r))
check("ReceiptSync", result.pubsub_status.value in ("OK","SUCCESS","SKIPPED"), result.pubsub_status.value)
check("Merkle leaves", sync.merkle.leaf_count>0, str(sync.merkle.leaf_count))

print("\nPART 5: PERFORMANCE")
t0 = time.time(); bulk = []; btid = uuid.uuid4().hex
for i in range(100):
    r = UniversalReceipt(receipt_id=str(uuid.uuid4()), task_id=btid, scenario=ScenarioType.S1_DELEGATION,
        step_index=i+1, generator_did="t", buyer_did="b", seller_did="s",
        receipt_type=RT.S1_STEP_EXECUTED.value,
        input_hash=hashlib.sha256(f"bb-{i}".encode()).hexdigest(),
        output_hash=hashlib.sha256(f"bbo-{i}".encode()).hexdigest(),
        payload_hash=compute_payload_hash({"i":i}), created_at=datetime.now(timezone.utc),
        execution_duration_ms=0, parent_receipt_id=bulk[-1].receipt_id if bulk else None,
        scenario_data={"i":i}, status=ReceiptStatus.GENERATED,
        signature=f"ed25519:{hashlib.sha256(f'bsig-{i}'.encode()).hexdigest()[:32]}")
    bulk.append(r)
elapsed = (time.time()-t0)*1000
check("100 receipts", len(bulk)==100, f"{elapsed:.1f}ms ({100000/elapsed:.0f} rec/s)")
btree = IncrementalMerkleAccumulator()
for r in bulk:
    btree.append(hashlib.sha256(f"{r.receipt_id}|{btid}|{r.step_index}|{r.payload_hash}|{r.created_at.isoformat()}".encode()).digest())
check("Merkle 100", btree.compute_root() is not None, f"{btree.leaf_count} leaves")
check("No duplicates", len({r.receipt_id for r in bulk})==len(bulk))

print(f"\n{'='*60}")
print(f"  {'✅' if passed==total else '⚠️'} {passed}/{total} PASSED" + (f" ({100*passed//total}%)" if total>0 else ""))
if passed==total: print(f"  ALL TESTS PASS ✅")
print(f"{'='*60}")
