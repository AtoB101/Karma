"""Chain indexer → BFF webhooks (HMAC)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from apps.karma_bff.app import services
from apps.karma_bff.app.deps import read_webhook_json
from apps.karma_bff.app.routes_integration import _conn
from apps.karma_bff.app.security_utils import assert_valid_trace_id

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/chain")
def chain_event(payload: dict[str, Any] = Depends(read_webhook_json)) -> dict[str, Any]:
    try:
        trace_id = assert_valid_trace_id(str(payload.get("trace_id") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    event = str(payload.get("event") or "").strip()
    if not event:
        raise HTTPException(400, "event required")
    conn = _conn()
    try:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "task not found")
        st = row["state"]
        if event in ("LOCK_CONFIRMED", "BILL_CREATED"):
            if st == "LOCK_PENDING":
                services.task_set_state(conn, trace_id, "LOCKED")
                if payload.get("bill_id") is not None:
                    services.task_set_bill(conn, trace_id, int(payload["bill_id"]), str(payload.get("tx_hash") or ""))
                services.task_set_state(conn, trace_id, "EXECUTE_ALLOWED")
            elif st == "LOCKED":
                services.task_set_state(conn, trace_id, "EXECUTE_ALLOWED")
            elif st == "EXECUTE_ALLOWED":
                return {"ok": True, "ignored": True, "reason": "already unlocked for execution", "trace_id": trace_id}
            else:
                return {"ok": True, "ignored": True, "reason": f"no transition from {st}", "trace_id": trace_id}
        else:
            raise HTTPException(400, f"unsupported event {event}")
        return {"ok": True, "trace_id": trace_id, "state": services.task_get(conn, trace_id)["state"]}
    finally:
        conn.close()
