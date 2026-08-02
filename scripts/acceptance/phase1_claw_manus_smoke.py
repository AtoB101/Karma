#!/usr/bin/env python3
"""Phase 1 SDK smoke — Karma Runtime API (no MCP stdio)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def _run(args: argparse.Namespace) -> int:
    base = os.environ.get("KARMA_RUNTIME_URL", args.base_url).strip()
    key = os.environ.get("KARMA_API_KEY", "").strip()
    if not base:
        print("ERR  KARMA_RUNTIME_URL or --base-url required", file=sys.stderr)
        return 1
    if not key:
        print("WARN  KARMA_API_KEY unset — only health/doc checks possible", file=sys.stderr)

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{base.rstrip('/')}/docs")
        if r.status_code != 200:
            print(f"ERR  API docs unreachable: {r.status_code}")
            return 1
        print("OK   API reachable", base)

    if args.skip_launch or not key:
        return 0

    idem = args.idempotency_key or f"smoke-{args.buyer_id}-{args.seller_id}"
    req_text = args.requirement or "caption smoke 10 USDC precision 1"
    launch_body: dict = {
        "buyer_identity_id": args.buyer_id,
        "seller_identity_id": args.seller_id,
        "requirement_text": req_text,
        "buyer_signature": "0xa2a_smoke",
        "task_type": args.task_type,
    }
    if args.chain_anchor_hash:
        launch_body["chain_anchor_hash"] = args.chain_anchor_hash

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Karma-Api-Key": key,
        "Idempotency-Key": idem,
    }
    root = base.rstrip("/")

    async with httpx.AsyncClient(timeout=60.0) as http:
        try:
            r = await http.post(f"{root}/v1/trade/orders/launch", json=launch_body, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
            out = r.json()
        except Exception as exc:
            print(f"FAIL launch: {exc}")
            print(
                "HINT run: python3 scripts/seed_phase1_dual_agents.py "
                "— see docs/AGENT_TO_AGENT_TEST.md"
            )
            return 2

        status = out.get("status")
        print(
            "OK   launch",
            status,
            "order_id=",
            out.get("order_id"),
            "task_id=",
            out.get("task_id"),
        )
        if args.require_execution_started and status != "execution_started":
            print(f"FAIL expected status=execution_started, got {status!r}")
            return 3
        if out.get("order_id"):
            gr = await http.get(
                f"{root}/v1/trade/orders/{out['order_id']}",
                headers={"Accept": "application/json", "X-Karma-Api-Key": key},
            )
            if gr.status_code < 400:
                row = gr.json()
                print(
                    "OK   get_trade_order status=",
                    row.get("status"),
                    "pipeline=",
                    row.get("pipeline_version"),
                )

        r2 = await http.post(f"{root}/v1/trade/orders/launch", json=launch_body, headers=headers)
        if r2.status_code >= 400:
            print(f"FAIL replay: HTTP {r2.status_code}: {r2.text}")
            return 4
        out2 = r2.json()
        if out2.get("idempotent_replay") and out2.get("order_id") == out.get("order_id"):
            print("OK   idempotent replay")
        else:
            print("WARN idempotent replay flag missing or order_id mismatch")
            if args.require_execution_started:
                return 4
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--buyer-id", default="buyer-demo")
    p.add_argument("--seller-id", default="seller-demo")
    p.add_argument("--requirement", default="")
    p.add_argument("--task-type", default="api.caption")
    p.add_argument("--idempotency-key", default="")
    p.add_argument("--chain-anchor-hash", default="")
    p.add_argument("--skip-launch", action="store_true")
    p.add_argument(
        "--require-execution-started",
        action="store_true",
        help="Fail unless launch status is execution_started (A2A land gate)",
    )
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
