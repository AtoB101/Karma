# karma-sdk

Minimal client for **KarmaBilateral** — the bilateral lock + Bill Token protocol.

Three methods. No middleware. No HTTP server required.

---

## Python

```bash
pip install karma-sdk          # requires: web3>=6
```

```python
from karma_sdk import KarmaBilateral

k = KarmaBilateral(
    rpc_url="https://mainnet.base.org",
    private_key="0x...",
    contract_address="0xKARMA_BILATERAL_ADDRESS",
)

# 1. Lock 100 USDC → mint Bill Token
bill_id = k.lock(USDC_ADDRESS, 100_000_000)

# 2. Bind buyer bill + agent bill → enter BOUND state
binding_id = k.bind(buyer_bill_id, agent_bill_id, scope_hash)

# 3. Settle → burn bills, release USDC atomically
k.settle(binding_id, proof_hash)
```

---

## TypeScript

```bash
npm install @karma/sdk ethers   # ethers v6 peer dep
```

```typescript
import { KarmaBilateral } from '@karma/sdk'
import { parseUnits } from 'ethers'

const k = new KarmaBilateral({
  rpc:        'https://mainnet.base.org',
  privateKey: '0x...',
  contract:   '0xKARMA_BILATERAL_ADDRESS',
})

// 1. Lock 100 USDC → mint Bill Token
const billId = await k.lock(USDC_ADDRESS, parseUnits('100', 6))

// 2. Bind buyer bill + agent bill → enter BOUND state
const bindingId = await k.bind(buyerBillId, agentBillId, scopeHash)

// 3. Settle → burn bills, release USDC atomically
await k.settle(bindingId, proofHash)
```

---

## Bill Token lifecycle

```
lock()   →  MINTED  (can unlock before bind)
bind()   →  BOUND   (frozen — cannot withdraw, cannot re-bind)
settle() →  BURNED  (USDC released atomically)
```

Global invariant enforced by contract at all times:

```
totalBillSupply[token] == totalLocked[token]
```

---

## Additional methods

| Method | Description |
|---|---|
| `unlock(billId)` | Withdraw a MINTED (unbound) bill |
| `getBill(billId)` | Read Bill Token state |
| `getBinding(bindingId)` | Read Binding state |
| `checkInvariant(token)` | Verify 1:1 supply/locked parity on-chain |

---

## Directory structure

```
packages/karma-sdk/
├── python/
│   ├── karma_sdk/
│   │   ├── __init__.py
│   │   └── client.py
│   └── pyproject.toml
├── typescript/
│   ├── src/index.ts
│   ├── package.json
│   └── tsconfig.json
└── README.md
```
