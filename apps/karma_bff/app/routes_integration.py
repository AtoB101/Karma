"""HMAC-protected integration API for OpenManus / orchestrators."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException

from apps.karma_bff.app import config, services
from apps.karma_bff.app.deps import read_hmac_json

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from trusted_agent_runtime.demo_payload import build_demo_offchain_bundle
from trusted_agent_runtime.evidence_adapter import EvidenceAdapter
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import ExecutionReceipt, TaskContract
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.verification import verify_evidence_bundle_structural

router = APIRouter(prefix="/v1/integration", tags=["integration"])


def _conn():
    import sqlite3

    from apps.karma_bff.app.db import connect, init_schema

    c = connect(config.database_path())
    init_schema(c)
    return c


def _idem(
    idem_key: str | None,
    route: str,
    fn,
) -> dict[str, Any]:
    if not idem_key:
        raise HTTPException(400, "Idempotency-Key header required")
    conn = _conn()
    try:
        cached = services.idempotency_get(conn, idem_key)
        if cached is not None:
            return cached
        out = fn(conn)
        services.idempotency_put(conn, idem_key, route, out)
        return out
    finally:
        conn.close()


@router.post("/tasks")
def create_task(
    payload: dict[str, Any] = Depends(read_hmac_json),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    trace_id = str(payload.get("trace_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    if not trace_id or not task_id:
        raise HTTPException(400, "trace_id and task_id required")

    def go(conn) -> dict[str, Any]:
        if services.task_get(conn, trace_id):
            raise HTTPException(409, "trace_id already exists")
        tc = {
            "task_id": task_id,
            "agent_id": str(payload.get("agent_id") or "openmanus"),
            "runtime_id": str(payload.get("runtime_id") or "openmanus"),
            "description": str(payload.get("description") or ""),
            "trace_id": trace_id,
        }
        row = services.task_create(conn, trace_id=trace_id, task_id=task_id, task_contract=tc)
        return {"ok": True, "task": _serialize_task(row)}

    return _idem(idempotency_key, "create_task", go)


@router.post("/tasks/{trace_id}/order-snapshot")
def order_snapshot(
    trace_id: str,
    payload: dict[str, Any] = Depends(read_hmac_json),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    def go(conn) -> dict[str, Any]:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "task not found")
        if row["state"] != "PLANNED":
            raise HTTPException(409, f"expected PLANNED for snapshot, got {row['state']}")
        services.task_set_state(conn, trace_id, "SNAPSHOT_RECORDED")
        services.task_update_snapshot(conn, trace_id, payload)
        row2 = services.task_get(conn, trace_id)
        return {"ok": True, "task": _serialize_task(row2)}

    return _idem(idempotency_key, f"order_snapshot:{trace_id}", go)


@router.post("/tasks/{trace_id}/buyer-lock-intent")
def buyer_lock_intent(
    trace_id: str,
    payload: dict[str, Any] = Depends(read_hmac_json),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Return buyer-facing lock page URL (wallet signing happens in browser, not here)."""

    def go(conn) -> dict[str, Any]:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "task not found")
        if row["state"] != "SNAPSHOT_RECORDED":
            raise HTTPException(409, f"expected SNAPSHOT_RECORDED, got {row['state']}")
        services.task_set_state(conn, trace_id, "LOCK_PENDING")
        base = config.public_base_url()
        lock_url = f"{base}/public/lock/{trace_id}"
        return {
            "ok": True,
            "trace_id": trace_id,
            "state": "LOCK_PENDING",
            "buyer_lock_page_url": lock_url,
            "instructions": "Buyer opens URL in mobile or desktop browser and connects wallet; funds move only via Karma contracts.",
            "karma_docs": "See docs/TESTNET_RUNBOOK.md for NonCustodialAgentPayment lockFunds/createBill flow.",
        }

    return _idem(idempotency_key, f"buyer_lock_intent:{trace_id}", go)


@router.post("/tasks/{trace_id}/receipts")
def append_receipt(
    trace_id: str,
    payload: dict[str, Any] = Depends(read_hmac_json),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    def go(conn) -> dict[str, Any]:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "task not found")
        st = row["state"]
        if st == "EVIDENCE_BUILT":
            raise HTTPException(409, "cannot append receipt after evidence is sealed")
        if st not in ("EXECUTE_ALLOWED", "EXECUTING"):
            raise HTTPException(409, f"cannot append receipt in state {st}")
        if st == "EXECUTE_ALLOWED":
            services.task_set_state(conn, trace_id, "EXECUTING")
        # minimal validation
        for k in ("receipt_id", "step_index", "tool_name", "status"):
            if k not in payload:
                raise HTTPException(400, f"missing {k}")
        payload.setdefault("trace_id", trace_id)
        tc = json.loads(row["task_contract_json"])
        payload.setdefault("task_id", tc.get("task_id"))
        payload.setdefault("agent_id", tc.get("agent_id"))
        payload.setdefault("runtime_id", tc.get("runtime_id"))
        services.receipt_append(conn, trace_id, payload)
        return {"ok": True, "trace_id": trace_id, "state": services.task_get(conn, trace_id)["state"]}

    return _idem(idempotency_key, f"receipt:{trace_id}:{payload.get('receipt_id')}", go)


@router.post("/tasks/{trace_id}/evidence/build")
def build_evidence(
    trace_id: str,
    payload: dict[str, Any] = Depends(read_hmac_json),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Build evidence bundle from stored receipts + public structural verify + settlement plan (offchain)."""

    def go(conn) -> dict[str, Any]:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "task not found")
        if row["state"] not in ("EXECUTING", "EVIDENCE_BUILT"):
            raise HTTPException(409, f"expected EXECUTING for evidence build, got {row['state']}")
        raw_receipts = services.receipts_list(conn, trace_id)
        if not raw_receipts:
            raise HTTPException(400, "no receipts stored")
        tc_dict = json.loads(row["task_contract_json"])
        task = TaskContract(**tc_dict)
        store = InMemoryReceiptStore()
        ids: list[str] = []
        for r in raw_receipts:
            er = ExecutionReceipt(**r)
            store.save_receipt(er)
            ids.append(er.receipt_id)
        adapter = EvidenceAdapter(store)
        bundle = adapter.build_evidence_bundle(task, ids)
        proof = adapter.map_to_karma_proof_hash(bundle)
        vr = verify_evidence_bundle_structural(task, bundle, store)
        from trusted_agent_runtime.evidence_adapter import task_contract_hash

        scope_hex = "0x" + task_contract_hash(task)
        plan = SettlementAdapter().build_offchain_plan(
            task,
            bundle,
            proof,
            scope_hex,
            seller=str(payload.get("seller") or "0x000000000000000000000000000000000000dEaD"),
            token=str(payload.get("token") or "0x000000000000000000000000000000000000c0ffee"),
            amount_wei=int(payload.get("amount_wei") or 1_000_000),
            deadline_unix=int(payload.get("deadline_unix") or 2_000_000_000),
            verify=vr,
        )
        services.task_set_state(conn, trace_id, "EVIDENCE_BUILT")
        return {
            "ok": True,
            "trace_id": trace_id,
            "state": "EVIDENCE_BUILT",
            "evidence_bundle": bundle.__dict__.copy(),
            "verification": vr.__dict__.copy(),
            "proof_hash": proof,
            "scope_hex": scope_hex,
            "offchain_settlement_plan": plan,
        }

    return _idem(idempotency_key, f"evidence_build:{trace_id}", go)


@router.get("/tasks/{trace_id}/status")
def task_status(trace_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "task not found")
        n = len(services.receipts_list(conn, trace_id))
        return {"ok": True, "task": _serialize_task(row), "receipt_count": n}
    finally:
        conn.close()


@router.post("/demo/seed")
def demo_seed(payload: dict[str, Any] = Depends(read_hmac_json)) -> dict[str, Any]:
    """Optional: load demo bundle into a new trace for integration tests (still requires HMAC)."""
    trace_id = str(payload.get("trace_id") or "trace-demo-seed")
    bundle = build_demo_offchain_bundle(trace_id=trace_id)
    task = bundle["task"]
    conn = _conn()
    try:
        if services.task_get(conn, trace_id):
            raise HTTPException(409, "exists")
        services.task_create(
            conn,
            trace_id=trace_id,
            task_id=task["task_id"],
            task_contract=task,
        )
        services.task_set_state(conn, trace_id, "SNAPSHOT_RECORDED")
        services.task_update_snapshot(conn, trace_id, {"demo": True, "order": "demo-seed"})
        services.task_set_state(conn, trace_id, "LOCK_PENDING")
        services.task_set_state(conn, trace_id, "EXECUTE_ALLOWED")
        services.task_set_state(conn, trace_id, "EXECUTING")
        for r in bundle["receipt_chain"]["receipts"]:
            services.receipt_append(conn, trace_id, r)
        row = services.task_get(conn, trace_id)
        return {"ok": True, "task": _serialize_task(row)}
    finally:
        conn.close()


def _serialize_task(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k in ("task_contract_json", "snapshot_json"):
        if out.get(k):
            try:
                out[k] = json.loads(out[k])
            except json.JSONDecodeError:
                pass
    return out
