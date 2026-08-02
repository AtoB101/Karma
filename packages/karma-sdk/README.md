# karma-sdk

Minimal client for **KarmaBilateral** — bilateral lock + Bill Token protocol.

Canonical pilot path: [`docs/PILOT_E2E_PATH.md`](../../docs/PILOT_E2E_PATH.md).

---

## Python

```bash
pip install -e packages/karma-sdk/python   # requires: web3>=6
```

```python
from karma_sdk import KarmaBilateral

k = KarmaBilateral(
    rpc_url="https://sepolia.infura.io/v3/YOUR_KEY",
    private_key="0x...",
    contract_address="0xKARMA_BILATERAL_ADDRESS",
)

bill_id = k.lock(USDC_ADDRESS, 100_000_000)
binding_id = k.bind(buyer_bill_id, agent_bill_id, scope_hash)
k.settle(binding_id, proof_hash)       # → FINALIZING
k.finalize_settle(binding_id)          # after dispute window → SETTLED
```

---

## TypeScript

```bash
cd packages/karma-sdk/typescript && npm install && npm run build
```

```typescript
import { KarmaBilateral } from '@karma/sdk'
import { parseUnits } from 'ethers'

const k = new KarmaBilateral({
  rpc:        'https://sepolia.infura.io/v3/YOUR_KEY',
  privateKey: '0x...',
  contract:   '0xKARMA_BILATERAL_ADDRESS',
})

const billId = await k.lock(USDC_ADDRESS, parseUnits('100', 6))
const bindingId = await k.bind(buyerBillId, agentBillId, scopeHash)
await k.settle(bindingId, proofHash)         // → FINALIZING
await k.finalizeSettle(bindingId)            // after dispute window → SETTLED
```

---

## Bill / binding lifecycle

```
lock()            → Bill MINTED
bind()            → Bills BOUND, Binding ACTIVE
settle()          → Binding FINALIZING (dispute window open; USDC still locked)
finalizeSettle()  → Binding SETTLED; bills BURNED; USDC released
dispute()         → Binding DISPUTED (within window)
refundOnTimeout() → Binding REFUNDED (settle timeout)
unlock()          → reclaim MINTED unbound bill
```

Invariant: `totalBillSupply[token] == totalLocked[token]`.

---

## Methods

| Method | Description |
|--------|-------------|
| `lock` / `bind` / `settle` / `finalizeSettle` | Happy path |
| `dispute` / `refundOnTimeout` / `unlock` | Branches |
| `getBill` / `getBinding` / `finalizeAfter` / `checkInvariant` | Views |

---

## Directory structure

```
packages/karma-sdk/
├── python/karma_sdk/
├── typescript/src/
└── README.md
```
