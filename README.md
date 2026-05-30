# Karma

Non-custodial bilateral escrow protocol for AI agent tasks.

## Mechanism

Lock USDC → mint Bill Token (1:1). Bind buyer + agent bill tokens → task begins. Settle on proof → burn tokens, release USDC.

## Quickstart

**Python**

```python
from karma_sdk import KarmaBilateral
k = KarmaBilateral(rpc_url, private_key, contract_address)
bill_id = k.lock(USDC_ADDRESS, 100_000_000)  # lock 100 USDC
```

**TypeScript**

```typescript
import { KarmaBilateral } from '@karma/sdk'
const k = new KarmaBilateral({ rpc, privateKey, contract })
const billId = await k.lock(USDC, parseUnits('100', 6))
```

## Core Interface

```solidity
function lock(address token, uint256 amount) external returns (uint256 billId);
function bind(uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash) external returns (uint256 bindingId);
function settle(uint256 bindingId, bytes32 proofHash) external;
```

## Install

```bash
pip install karma-sdk        # Python
npm install @karma/sdk       # TypeScript
```

## Build & Test

```bash
forge build
forge test
```

---

*Non-custodial. No admin keys. Math settles, not humans.*
