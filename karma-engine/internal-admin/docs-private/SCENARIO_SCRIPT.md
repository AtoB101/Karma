# Karma Demo Script

This script is designed for live demos, investor updates, and technical reviews.
It maps directly to `contracts/test/ScenarioFlow.t.sol`.

## 0) Setup

Run:

```bash
forge test --match-path "contracts/test/ScenarioFlow.t.sol" -vv
```

Talking point:

- "I will run a single end-to-end scenario that demonstrates identity binding, escrowed funds, signed authorization, and final payout."

## 1) DID Registration

What happens:

- Buyer agent DID is registered (by owner context in this MVP flow).
- Seller agent DID is registered.

Talking points:

- "Every agent action is anchored to an on-chain DID context."
- "No valid DID, no bill creation path."

Security angle:

- Identity existence and validity checks happen before bill creation.

## 2) Lock Pool Creation

What happens:

- Owner creates a lock pool using a real ERC20 token.
- `transferFrom(owner -> lock pool contract)` executes.
- Mapping balance equals deposited amount.

Talking points:

- "Funds are escrowed in-contract, not in platform custody."
- "Spending capacity is bounded by actual locked capital."

Key assertion in scenario:

- mapping balance equals `10_000` after pool creation.

## 3) Signed Create Bill (EIP-712)

What happens:

- Buyer agent issues an auth token for `CreateBill`.
- EIP-712 digest is produced and signed.
- `createBill(...)` consumes the signature.

Talking points:

- "Bill creation is not just a function call; it requires a valid signed authorization."
- "Amount and operation type are both cryptographically bound."

Security angle:

- Replay-protected digest consumption.
- Deadline-bound signature validity.

## 4) Signed Confirm Bill (EIP-712 + Owner Control)

What happens:

- Pool owner signs a `ConfirmBill` authorization.
- `confirmBill(...)` verifies owner context and signature.

Talking points:

- "The owner remains the final control point."
- "Even if a caller reaches the function, invalid or missing auth signature fails the flow."

## 5) Batch Close + Settle

What happens:

- Owner closes batch.
- Owner settles batch.
- Contract pays seller in real ERC20.

Talking points:

- "Settlement converts pending escrow into real payout."
- "This is no longer simulated accounting; token balances change on-chain."

## 6) Final Assertions You Should Call Out

From the scenario test:

- Seller balance delta is exactly `500`.
- Escrow conservation holds: `totalLocked == mappingBalance + pendingAmount`.
- `settledAmount == 500`.

Talking points:

- "We verify both business outcome (seller paid) and accounting integrity (no value leakage)."

## Suggested Demo Narrative (2-3 minutes)

1. "Identity first: both agents have DID context."
2. "Funds are pre-locked via ERC20 escrow."
3. "Buyer agent creates bill with signed authorization."
4. "Owner confirms with signed authorization."
5. "Batch closes and settles, seller receives tokens."
6. "Assertions prove payout and conservation."

## Common Questions and Recommended Answers

Q: "What prevents replay attacks?"

- "Auth digests are tracked and can only be consumed once; token usage is also marked."

Q: "What if signatures are old?"

- "Deadlines are enforced in auth consumption and cannot exceed token validity."

Q: "Can unauthorized users confirm or settle?"

- "No. Owner checks are enforced on sensitive paths, plus signature checks."

Q: "Is this using real token transfers?"

- "Yes. Pool create/top-up/withdraw and settle all execute ERC20 transfers."

Q: "Is there an emergency stop?"

- "Yes. Circuit breaker can block new bill creation under incident conditions."

## What To Build Next (Post-Demo Priority)

- Add CI execution for scenario + invariants.
- Add event-oriented indexer integration docs.
- Add production-safe ERC20 wrappers for non-standard token behavior.
- Add backend command API to generate/sign/submit auth payloads.
