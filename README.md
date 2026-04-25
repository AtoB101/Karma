# TrustChain Contracts Skeleton

This repository contains a first-pass Solidity skeleton for the TrustChain protocol:

- KYA identity registry
- lock pool and mapping-balance manager
- auth token manager
- bill + batch settlement manager
- circuit breaker controls

## Prerequisites

Install Foundry (macOS/Linux):

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

Verify installation:

```bash
forge --version
```

Install `forge-std` test library:

```bash
forge install foundry-rs/forge-std
```

## Build

From project root:

```bash
forge build
```

## Test

Run all tests:

```bash
forge test -vv
```

Run a single test file:

```bash
forge test --match-path "contracts/test/KYARegistry.t.sol" -vv
```

Run demo scenario (end-to-end flow):

```bash
forge test --match-path "contracts/test/ScenarioFlow.t.sol" -vv
```

Run invariant/fuzz tests:

```bash
forge test --match-path "contracts/test/LockPoolManager.invariant.t.sol" -vv
forge test --match-path "contracts/test/CrossModuleAccounting.invariant.t.sol" -vv
forge test --match-path "contracts/test/BillStateMachine.invariant.t.sol" -vv
```

## Notes

- Current contracts are a protocol skeleton and intentionally keep business logic minimal.
- Tests cover deployment, basic happy paths, and selected revert paths.
- Next iteration should tighten invariants for pool accounting, auth signatures (full EIP-712), and settlement safety.
- `BatchSettlement` is kept only as a deprecated compatibility wrapper; call `BillManager` directly for `closeBatch/settleBatch`.

## Core Settlement MVP v0.1

The focused v0.1 path is "Quote -> Verify -> Settle":

- signer creates EIP-712 quote commitment
- relayer/counterparty submits settlement
- contract verifies signature + nonce + deadline + replay
- contract executes token transfer settlement

Run focused v0.1 tests:

```bash
forge test --match-path "contracts/test/SettlementEngine.t.sol" -vv
```

See scope definition: `docs/V0_1_SCOPE.md`.
