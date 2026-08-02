# Pilot E2E path (Sepolia Bilateral)

Canonical path for external builders on the invite Sepolia pilot.

**Choose this path:** on-chain **KarmaBilateral** via `packages/karma-sdk`  
(`lock → bind → settle → finalizeSettle`).

HTTP capacity / vouchers / console writes are the **operator/off-chain** companion path
(see [CONSOLE_LAST_MILE-zh.md](./public-testing/CONSOLE_LAST_MILE-zh.md)). They do not replace on-chain finalize.

---

## Out of pilot scope

| Package / feature | Status |
|-------------------|--------|
| `packages/karma_solana` | Hollow — not used for Sepolia pilot |
| `packages/karma_billing` Solana Merkle bridge | Deferred |
| `settleWithTEE` / `settleWithZKProof` | L2/L3 stubs — L1 optimistic path only |
| P7 ticket issuer API | Deferred; use digital / hash POD scenes |

HTTP TypeScript client: `packages/sdk` (`KarmaPublicSdk`) — capacity/settlement/receipts against the public API. For on-chain bills use `packages/karma-sdk`.

---

## Prerequisites

- Sepolia ETH + test USDC (mUSDC)
- Deployed addresses in [`deploy/sepolia_bilateral_deployment.json`](../deploy/sepolia_bilateral_deployment.json)
- Python: `pip install -e packages/karma-sdk/python` (or `pip install karma-sdk` when published)
- Or TypeScript: `cd packages/karma-sdk/typescript && npm i && npm run build`

Default Sepolia addresses (confirm against the deploy JSON):

- KarmaBilateral: `0x496d178a5D32E9410E52bD5800602BDEe81B2A91`
- mUSDC: `0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF`
- Testnet windows: settle delay **60s**, dispute window **120s**

---

## Happy path (Python)

```python
from karma_sdk import KarmaBilateral

RPC = "https://sepolia.infura.io/v3/YOUR_KEY"
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
KARMA = "0x496d178a5D32E9410E52bD5800602BDEe81B2A91"
SCOPE = bytes.fromhex("11" * 32)
PROOF = bytes.fromhex("22" * 32)

buyer = KarmaBilateral(RPC, BUYER_KEY, KARMA)
agent = KarmaBilateral(RPC, AGENT_KEY, KARMA)

buyer_bill = buyer.lock(USDC, 10_000_000)   # 10 mUSDC
agent_bill = agent.lock(USDC, 10_000_000)

# Either party that owns the buyer bill typically binds (see contract access rules)
binding_id = buyer.bind(buyer_bill, agent_bill, SCOPE)

# Wait settleDelaySeconds, then:
buyer.settle(binding_id, PROOF)            # state → FINALIZING

# Wait disputeWindowSeconds, then anyone may finalize:
buyer.finalize_settle(binding_id)          # state → SETTLED; bills burned; USDC released

assert buyer.get_binding(binding_id).state == "SETTLED"
assert buyer.check_invariant(USDC)
```

TypeScript mirrors the same methods: `lock` / `bind` / `settle` / `finalizeSettle` / `dispute` / `refundOnTimeout`.

---

## Branches

| Situation | Call |
|-----------|------|
| Unbound bill, reclaim funds | `unlock(bill_id)` |
| Challenge during FINALIZING | `dispute(binding_id, evidence_hash)` |
| Settle never submitted in time | `refund_on_timeout(binding_id)` |

---

## Verify

1. Etherscan: binding events on the KarmaBilateral address  
2. `get_binding` → `SETTLED`; both bills `BURNED`  
3. `check_invariant(USDC)` → `True`  
4. Companion HTTP smoke (API + console helpers):  
   `python3 -m pytest -q tests/unit/test_console_live_write_smoke.py`

Longer narrative: [QUICKSTART_15MIN.md](./QUICKSTART_15MIN.md), [TESTNET_RUNBOOK.md](./TESTNET_RUNBOOK.md), [SETTLEMENT_FLOW_PUBLIC.md](./SETTLEMENT_FLOW_PUBLIC.md).
