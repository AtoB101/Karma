#!/usr/bin/env python3
"""
Testnet acceptance helper for POST /v1/trade/orders/launch (pipeline v2).

  python3 scripts/testnet/trade_preauth_pipeline_acceptance.py \\
    --base-url http://127.0.0.1:8000 \\
    --buyer-id buyer-1 --seller-id seller-1 \\
    --idempotency-key testnet-trade-001 \\
    --chain-anchor-hash 0x$(python3 -c 'print("ab"*32)') \\
    --output-dir results/trade-acceptance

Requires SETTLEMENT_MODE=testnet|hybrid when chain_anchor_hash is enforced server-side.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _post_json(url: str, body: dict, headers: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"raw": raw}
        return e.code, detail


def main() -> int:
    p = argparse.ArgumentParser(description="Trade preauth pipeline testnet acceptance")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--buyer-id", required=True)
    p.add_argument("--seller-id", required=True)
    p.add_argument("--idempotency-key", required=True)
    p.add_argument("--chain-anchor-hash", default="")
    p.add_argument("--requirement", default="caption 字幕任务 金额 15 USDC 精度 1.2")
    p.add_argument("--task-type", default="api.caption")
    p.add_argument("--output-dir", default="results/trade-acceptance")
    p.add_argument("--replay", action="store_true", help="POST twice with same idempotency key")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    url = f"{args.base_url.rstrip('/')}/v1/trade/orders/launch"
    payload = {
        "buyer_identity_id": args.buyer_id,
        "seller_identity_id": args.seller_id,
        "requirement_text": args.requirement,
        "task_type": args.task_type,
        "buyer_signature": "0xtestnet_acceptance_sig",
    }
    if args.chain_anchor_hash:
        payload["chain_anchor_hash"] = args.chain_anchor_hash.strip()

    headers = {"Idempotency-Key": args.idempotency_key}
    status, body = _post_json(url, payload, headers)
    report = {"step": "launch", "http_status": status, "response": body, "headers": headers}

    if status not in (200, 201):
        (out_dir / "failure.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    if args.replay:
        status2, body2 = _post_json(url, payload, headers)
        report["replay"] = {"http_status": status2, "response": body2}
        if status2 not in (200, 201) or not body2.get("idempotent_replay"):
            (out_dir / "failure.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print("idempotent replay check failed", file=sys.stderr)
            return 2

    order_id = body.get("order_id")
    if order_id:
        get_url = f"{args.base_url.rstrip('/')}/v1/trade/orders/{order_id}"
        with urllib.request.urlopen(get_url, timeout=60) as resp:
            report["order_get"] = json.loads(resp.read().decode("utf-8"))

    (out_dir / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "order_id": order_id, "status": body.get("status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
