# 15-Minute KarmaBilateral Quickstart (Sepolia Testnet)

Follow this guide to complete a full lock → bind → settle cycle in 15 minutes.

## Prerequisites

- Python 3.10+ or Node.js 18+
- A Sepolia wallet with Sepolia ETH (get from [sepoliafaucet.com](https://sepoliafaucet.com))

## Step 1 — Install (1 min)

```bash
# Python
pip install karma-sdk

# OR TypeScript
npm install @karma/sdk
```

## Step 2 — Get Test USDC (1 min)

Join the [Karma Testnet Discord](#) and use `/faucet` to receive **100 mUSDC** on Sepolia.
Or send 0 Sepolia ETH to `0x...faucet` to receive mUSDC automatically.

**Contract addresses:**
- KarmaBilateral: `0x496d178a5D32E9410E52bD5800602BDEe81B2A91`
- mUSDC (test): `0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF`

## Step 3 — Lock USDC (3 min)

Both Buyer and Agent must lock USDC before any task begins. This is the core difference from traditional escrow: **both sides have skin in the game.**

**Python (Buyer):**
```python
from karma_sdk import KarmaBilateral

RPC = "https://sepolia.infura.io/v3/YOUR_KEY"
USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
KARMA = "0x496d178a5D32E9410E52bD5800602BDEe81B2A91"

k = KarmaBilateral(RPC, YOUR_PRIVATE_KEY, KARMA)

# Step A: Approve USDC spending (one-time)
# Use your wallet or cast to: usdc.approve(KARMA, amount)

# Step B: Lock 10 USDC
bill_id = k.lock(USDC, 10_000_000)  # 10 USDC (6 decimals)
print(f"Bill Token minted: #{bill_id}")
```

**TypeScript (Agent):**
```typescript
import { KarmaBilateral } from '@karma/sdk'

const k = new KarmaBilateral({ rpc: RPC, privateKey: YOUR_KEY, contract: KARMA })
const billId = await k.lock(USDC, parseUnits('10', 6))
```

## Step 4 — Bind (1 min)

The Buyer calls `bind()` to pair both Bill Tokens into a Binding. This freezes both sides' USDC.

```python
# Buyer calls:
binding_id = k.bind(BUYER_BILL_ID, AGENT_BILL_ID, SCOPE_HASH)
print(f"Bound: binding #{binding_id}")

# Verify state
b = k.get_binding(binding_id)
print(f"State: {b.state}")  # ACTIVE
```

## Step 5 — Settle (10 min wait + 1 min)

KarmaBilateral has a **30-minute settle delay** (configurable) and a **24-hour dispute window**. On testnet these are shortened.

```python
# Wait for settle delay, then:
k.settle(binding_id, PROOF_HASH)
# State → FINALIZING (dispute window opens)

# After dispute window:
k.finalizeSettle(binding_id)
# State → SETTLED, bills burned, USDC released
```

## Verify on Explorer

- [KarmaBilateral on Sepolia](https://sepolia.etherscan.io/address/0x496d178a5D32E9410E52bD5800602BDEe81B2A91)
- Check your bills: `k.get_bill(bill_id)`
- Check your binding: `k.get_binding(binding_id)`

## What's Different from Old Escrow

| | Old (MinimalEscrow) | New (KarmaBilateral) |
|---|---|---|
| Lock | Buyer only deposits ETH | **Both sides lock USDC** |
| Bind | Not required | Buyer calls `bind()` to pair bills |
| Settle | Single step | Two-step: `settle()` → wait 24h → `finalizeSettle()` |
| Dispute | Manual | Built-in: dispute within 24h window |
| Proof | Optional | Required: `proofHash` on every settle |

## Next Steps

- [Full Documentation](docs/)
- [API Reference](docs/API_REFERENCE.md)
- [Migration Guide](docs/MIGRATION_NCPA_TO_BILATERAL.md)
- [Test Report](docs/TEST_REPORT_2026-05-31.md)
