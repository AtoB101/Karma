# Settlement flow (public)

Canonical on-chain settlement is **KarmaBilateral** only:

- Contract: `karma-core/contracts/core/KarmaBilateral.sol`
- Off-chain adapter: `services/chain/settlement_adapter.py`
- Plan builder: `evidence_runtime/settlement_adapter.py`

## Happy path

```text
lock(token, amount)     → mint Bill Token 1:1 (MINTED), USDC in escrow
bind(buyerBill, agentBill, scopeHash) → both bills BOUND
… execute task, collect evidence …
settle(bindingId, proofHash) → FINALIZING (dispute window)
finalizeSettle(bindingId)    → burn bills, release USDC (SETTLED)
```

Global invariant: `totalBillSupply[token] == totalLocked[token]`.

## States (informative)

**Bill:** `MINTED → BOUND → BURNED`  
**Binding:** `ACTIVE → FINALIZING → SETTLED | DISPUTED | REFUNDED | …`

## Off-chain mirrors

Capacity / voucher ledgers under `services/` reserve bill credits before or alongside chain locks.  
They must not invent a second escrow model — chain Bilateral is authoritative for on-chain funds.

## Not in this repo

Legacy `NonCustodialAgentPayment` / `SettlementEngine` paths and createBill scripts were removed.
