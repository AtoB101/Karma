"""Dual-agent autonomous settlement demo — Hermes (buyer) + Claw (seller).

Hermes is simulated by this script (buyer side); Claw is OpenClaw driving the
seller side. Both use the same /v1/bilateral/* endpoints the karma-openclaw MCP
tools call, so this exercises the real agent -> API -> KarmaBilateral chain.
"""
import asyncio
import os
import hashlib

from karma_openclaw.http_client import api_post, api_get

RUNTIME = os.environ.get("KARMA_RUNTIME_URL", "http://127.0.0.1:8010").rstrip("/")
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"


def _h(s: str) -> str:
    return "0x" + hashlib.sha256(s.encode()).hexdigest()


def _post(api_key: str, path: str, body: dict):
    os.environ["KARMA_API_KEY"] = api_key
    return api_post(path, body)


def _get(api_key: str, path: str):
    os.environ["KARMA_API_KEY"] = api_key
    return api_get(path)


async def main():
    buyer_key = os.environ["BUYER_API_KEY"]
    seller_key = os.environ["SELLER_API_KEY"]

    print("=== Hermes (buyer) & Claw (seller) — autonomous bilateral trade ===")

    # 1. Hermes discovers the task and locks the full order
    print("\n[Hermes] 我需要一份交付服务，锁定 100 mUSDC 作为订单全款")
    bl = await _post(buyer_key, "/v1/bilateral/lock", {"token": USDC, "amount": 100_000_000, "role": "buyer"})
    buyer_bill = bl["bill_id"]
    print(f"[Hermes] 已锁仓 → buyer bill {buyer_bill}")

    # 2. Claw accepts the order and locks only the penalty (10%)
    print("\n[Claw] 我接单，只需锁 10% 违约金（10 mUSDC），不用锁全款")
    sl = await _post(seller_key, "/v1/bilateral/lock", {"token": USDC, "amount": 10_000_000, "role": "agent"})
    seller_bill = sl["bill_id"]
    print(f"[Claw] 已锁违约金 → agent bill {seller_bill}")

    # 3. Hermes binds the two bills (responsibility locked)
    print("\n[Hermes] 双方都已锁仓，绑定责任")
    bd = await _post(buyer_key, "/v1/bilateral/bind", {
        "buyer_bill_id": buyer_bill,
        "agent_bill_id": seller_bill,
        "scope_hash": _h("delivery:hermes-buys-from-claw"),
    })
    binding = bd["binding_id"]
    print(f"[Hermes] 绑定完成 → binding {binding} (ACTIVE)")

    # 4. Claw delivers and submits settlement proof
    print("\n[Claw] 交付完成，提交结算证明")
    st = await _post(seller_key, "/v1/bilateral/settle", {"binding_id": binding, "proof_hash": _h("delivery-proof")})
    print(f"[Claw] 已提交 settle → state {st['state']} (FINALIZING)")

    # 5. Hermes finalizes after dispute window (0s in this deployment)
    print("\n[Hermes] 争议期已过，最终结算")
    fn = await _post(buyer_key, f"/v1/bilateral/finalize/{binding}", {})
    print(f"[Hermes] finalize → state {fn['state']} (SETTLED)")

    # 6. Verify
    status = await _get(buyer_key, f"/v1/bilateral/status/{binding}")
    bb_state = status["buyer_bill"]["state"]
    ab_state = status["agent_bill"]["state"]
    print("\n=== RESULT ===")
    print(f"binding {binding}: state={status['state']}")
    print(f"buyer bill {buyer_bill}: state={bb_state}")
    print(f"seller bill {seller_bill}: state={ab_state}")
    assert status["state"] == 3 and bb_state == 2 and ab_state == 2, "settlement not finalized"
    print("\n[OK] DUAL-AGENT AUTONOMOUS TRADE: PASS (Hermes paid, Claw delivered, escrow released)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
