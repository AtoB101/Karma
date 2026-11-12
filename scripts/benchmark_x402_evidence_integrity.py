#!/usr/bin/env python3
"""Phase 2 benchmark — x402 receipt external_payment integrity (local mock)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=10)
    p.add_argument("--out", default="results/x402_benchmark_summary.json")
    args = p.parse_args()

    from sdk.x402.client import X402Client
    from sdk.x402.executors import MockX402PaymentExecutor
    from sdk.x402.models import PaymentRequiredDocument
    import base64

    doc = PaymentRequiredDocument(
        x402Version=1,
        accepts=[
            {
                "scheme": "exact",
                "network": "base-sepolia",
                "maxAmountRequired": "1.0",
                "payTo": "0x" + "e" * 40,
                "resource": "https://benchmark.example/resource",
            }
        ],
    )
    hdr = base64.urlsafe_b64encode(doc.model_dump_json(by_alias=True).encode()).decode()

    ok = 0
    t0 = time.perf_counter()
    for i in range(args.iterations):
        from unittest.mock import AsyncMock, MagicMock, patch

        resp_402 = MagicMock(status_code=402, content=b"", headers={"PAYMENT-REQUIRED": hdr})
        resp_200 = MagicMock(status_code=200, content=b'{"i":%d}' % i, headers={})
        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=[resp_402, resp_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        import asyncio

        async def _one():
            with patch("sdk.x402.client.httpx.AsyncClient", return_value=mock_client):
                c = X402Client(MockX402PaymentExecutor())
                r = await c.pay_and_fetch("https://benchmark.example/resource", max_budget_usdc=10.0)
                return r.external_payment is not None

        if asyncio.run(_one()):
            ok += 1

    elapsed = time.perf_counter() - t0
    summary = {
        "iterations": args.iterations,
        "success": ok,
        "success_rate": ok / max(1, args.iterations),
        "elapsed_seconds": round(elapsed, 4),
        "protocol": "x402",
        "executor": "mock",
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return 0 if ok == args.iterations else 1


if __name__ == "__main__":
    raise SystemExit(main())
