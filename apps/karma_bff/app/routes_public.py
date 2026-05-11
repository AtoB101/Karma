"""Public read-only pages (buyer lock instructions, status)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Response

from apps.karma_bff.app import config, services
from apps.karma_bff.app.routes_integration import _conn

router = APIRouter(tags=["public"])


@router.get("/public/lock/{trace_id}")
def buyer_lock_page(trace_id: str) -> Response:
    conn = _conn()
    try:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "unknown trace")
        snap = json.loads(row["snapshot_json"]) if row.get("snapshot_json") else {}
        tc = json.loads(row["task_contract_json"]) if row.get("task_contract_json") else {}
        html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Karma lock — {trace_id}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}
code{{background:#f3f4f6;padding:0.1rem 0.35rem;border-radius:4px}}</style></head><body>
<h1>Secure lock-in</h1>
<p><strong>Trace</strong>: <code>{trace_id}</code></p>
<p><strong>State</strong>: <code>{row["state"]}</code></p>
<p>This page does <strong>not</strong> collect private keys. Connect your wallet only in a wallet you trust, then execute <code>lockFunds</code> / <code>createBill</code> per <code>docs/TESTNET_RUNBOOK.md</code>.</p>
<h2>Order snapshot (summary)</h2>
<pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:1rem;border-radius:8px;font-size:0.85rem">{json.dumps(snap, indent=2)}</pre>
<h2>Task</h2>
<pre style="white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:1rem;border-radius:8px;font-size:0.85rem">{json.dumps(tc, indent=2)}</pre>
<p><a href="{config.public_base_url()}/public/status/{trace_id}">JSON status</a></p>
</body></html>"""
        return Response(content=html, media_type="text/html; charset=utf-8")
    finally:
        conn.close()


@router.get("/public/status/{trace_id}")
def public_status(trace_id: str) -> dict:
    conn = _conn()
    try:
        row = services.task_get(conn, trace_id)
        if not row:
            raise HTTPException(404, "unknown trace")
        n = len(services.receipts_list(conn, trace_id))
        return {
            "trace_id": trace_id,
            "state": row["state"],
            "receipt_count": n,
            "bill_id": row.get("bill_id"),
        }
    finally:
        conn.close()
