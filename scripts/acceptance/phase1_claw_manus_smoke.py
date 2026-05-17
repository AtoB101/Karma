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

    from karma_openmanus import KarmaRuntimeClient

    client = KarmaRuntimeClient(base, key)
    idem = args.idempotency_key or f"smoke-{args.buyer_id}-{args.seller_id}"

    try:
        out = await client.launch_trade_order(
            buyer_identity_id=args.buyer_id,
            seller_identity_id=args.seller_id,
            requirement_text=args.requirement or "caption smoke 10 USDC precision 1",
            idempotency_key=idem,
            task_type=args.task_type,
            chain_anchor_hash=args.chain_anchor_hash or None,
        )
    except Exception as exc:
        print(f"FAIL launch: {exc}")
        print("HINT seed policies, runtime keys, capacity — see docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md")
        return 2

    print("OK   launch", out.get("status"), "order_id=", out.get("order_id"))
    if out.get("order_id"):
        row = await client.get_trade_order(str(out["order_id"]))
        print("OK   get_trade_order status=", row.get("status"), "pipeline=", row.get("pipeline_version"))

    out2 = await client.launch_trade_order(
        buyer_identity_id=args.buyer_id,
        seller_identity_id=args.seller_id,
        requirement_text=args.requirement or "caption smoke 10 USDC precision 1",
        idempotency_key=idem,
        task_type=args.task_type,
        chain_anchor_hash=args.chain_anchor_hash or None,
    )
    if out2.get("idempotent_replay") and out2.get("order_id") == out.get("order_id"):
        print("OK   idempotent replay")
    else:
        print("WARN idempotent replay flag missing or order_id mismatch")
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
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
