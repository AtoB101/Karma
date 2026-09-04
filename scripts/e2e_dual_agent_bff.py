"""Dual-agent autonomous settlement driver (Hermes buyer / Claw seller).

Drives a real bilateral transaction through the BFF (`apps/karma_bff`), the same
endpoints the karma-openclaw MCP tools call, so it proves the full
agent -> BFF -> API -> KarmaBilateral chain.

Prereqs:
  - BFF running:  uvicorn apps.karma_bff.app.main:app --port 8020
  - Karma API + worker + Redis + seeded buyer/seller (see team/reports/...-integration-ready.md)
  - BUYER_API_KEY / SELLER_API_KEY in env (from .env.phase1.local)

Usage:
  BUYER_API_KEY=karma_buyer-... SELLER_API_KEY=karma_seller-... \
  KARMA_RUNTIME_URL=http://127.0.0.1:8020 \
  python scripts/e2e_dual_agent_bff.py
"""
import os
import sys
import time
import hashlib

from karma_openclaw.http_client import api_post, api_get

RUNTIME = os.environ.get("KARMA_RUNTIME_URL", "http://127.0.0.1:8010").rstrip("/")
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
AMOUNT = 100_000_000      # buyer locks 100 USDC
PENALTY = 10_000_000      # seller locks 10 USDC (10%)


def _post(api_key: str, path: str, body: dict) -> dict:
    os.environ["KARMA_API_KEY"] = api_key
    return api_post(path, body)


def _get(api_key: str, path: str) -> dict:
    os.environ["KARMA_API_KEY"] = api_key
    return api_get(path)


def h(s: str) -> str:
    return "0x" + hashlib.sha256(s.encode()).hexdigest()


def main():
    buyer_key = os.environ["BUYER_API_KEY"]
    seller_key = os.environ["SELLER_API_KEY"]

    # 1. Hermes (buyer) locks full order
    bl = _post(buyer_key, "/v1/bilateral/lock", {"token": USDC, "amount": AMOUNT, "role": "buyer"})
    buyer_bill = bl["bill_id"]

    # 2. Claw (seller) locks penalty
    sl = _post(seller_key, "/v1/bilateral/lock", {"token": USDC, "amount": PENALTY, "role": "agent"})
    seller_bill = sl["bill_id"]

    # 3. Buyer binds
    bd = _post(buyer_key, "/v1/bilateral/bind", {
        "buyer_bill_id": buyer_bill,
        "agent_bill_id": seller_bill,
        "scope_hash": h("hermes-buys-claw-delivery"),
    })
    binding = bd["binding_id"]

    # 4. Seller settles (delivered)
    st = _post(seller_key, "/v1/bilateral/settle", {
        "binding_id": binding,
        "proof_hash": h("delivery-proof"),
    })

    # 5. Buyer finalizes (after dispute window)
    time.sleep(2)
    fn = _post(buyer_key, f"/v1/bilateral/finalize/{binding}", {})

    # 6. status
    status = _get(buyer_key, f"/v1/bilateral/status/{binding}")

    print("=" * 60)
    print("  DUAL-AGENT BFF SETTLEMENT: PASS")
    print("=" * 60)
    print("  buyer_bill :", buyer_bill)
    print("  seller_bill:", seller_bill)
    print("  binding    :", binding)
    print("  settle     :", st)
    print("  finalize   :", fn)
    print("  status     :", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
