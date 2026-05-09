# Karma v0.1 Scope

## Objective

Deliver one thing well: verifiable quote-to-settlement for off-chain AI agents.

## Core Flow

1. Agent (payer) signs a quote commitment with EIP-712.
2. Counterparty (or relayer) submits settlement transaction on-chain.
3. Contract verifies signature, nonce, deadline, replay.
4. On success, contract executes token transfer settlement.
5. On failure, revert reason + events are traceable.

## In Scope (v0.1)

- `SettlementEngine.submitSettlement(quote, sig)`
- EIP-712 quote digest and signature recovery
- Nonce validation
- Quote replay protection (`quoteId`)
- Deadline enforcement
- Token allowlist
- Simple pause/unpause (admin)
- Clear errors and settlement events

## Out of Scope (deferred)

- KYA hard dependency (kept as optional ecosystem module)
- Complex lock-pool orchestration
- Advanced multi-level circuit breaker
- Reputation/arbitration/governance layers
- Multi-scenario abstraction

## Success Criteria

- End-to-end settlement path runs with one command/test.
- Failure paths are deterministic and observable.
- Core tests cover success + signature/nonce/deadline/replay failures.
