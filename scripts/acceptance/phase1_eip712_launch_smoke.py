#!/usr/bin/env python3
"""Phase 1 path B smoke — signing-preview → sign-with-backend → launch (live API)."""

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
    if not base or not key:
        print("ERR  KARMA_RUNTIME_URL and KARMA_API_KEY required", file=sys.stderr)
        return 1

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{base.rstrip('/')}/docs")
        if r.status_code != 200:
            print(f"ERR  API unreachable: {r.status_code}")
            return 1
        print("OK   API reachable", base)

    from karma_openmanus import KarmaRuntimeClient

    c = KarmaRuntimeClient(base, key)
    idem = args.idempotency_key or f"eip712-smoke-{args.buyer_id}-{args.seller_id}"
    body_common = dict(
        buyer_identity_id=args.buyer_id,
        seller_identity_id=args.seller_id,
        requirement_text=args.requirement or "caption eip712 smoke 12 USDC precision 1",
        idempotency_key=idem,
        task_type=args.task_type,
    )

    try:
        preview = await c.trade_launch_signing_preview(**body_common)
        print("OK   signing-preview", "wallet=", preview.get("buyer_wallet_address"))
        signed = await c.trade_launch_sign_with_backend(**body_common)
        sig = (signed.get("buyer_signature") or "").strip()
        if not sig.startswith("0x"):
            print("FAIL sign-with-backend: missing buyer_signature")
            return 2
        print("OK   sign-with-backend", sig[:18], "...")
        out = await c.launch_trade_order(**body_common, buyer_signature=sig)
    except Exception as exc:
        print(f"FAIL eip712 path: {exc}")
        print("HINT TRADE_LAUNCH_REQUIRE_EIP712=true, KARMA_SIGNING_BACKEND=env,")
        print("     buyer bound_wallet matches KARMA_SIGNING_DEV_PRIVATE_KEY")
        print("     see deploy/.env.local-eip712.example")
        return 2

    if out.get("status") != "execution_started":
        print("FAIL launch status:", out.get("status"))
        return 2
    print("OK   launch", "order_id=", out.get("order_id"))

    out2 = await c.launch_trade_order(**body_common, buyer_signature=sig)
    if out2.get("idempotent_replay") and out2.get("order_id") == out.get("order_id"):
        print("OK   idempotent replay")
    else:
        print("WARN idempotent replay missing or order_id mismatch")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 1 EIP-712 launch smoke (path B)")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--buyer-id", default="buyer-demo")
    p.add_argument("--seller-id", default="seller-demo")
    p.add_argument("--requirement", default="")
    p.add_argument("--task-type", default="api.caption")
    p.add_argument("--idempotency-key", default="")
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
