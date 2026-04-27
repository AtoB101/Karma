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

### Foolproof deploy + visual console (recommended first)

Short path (clone, deploy three on-chain steps, open one web UI): see section **0)** in `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt`.

ETH-chain one-command deploy helper:

```bash
ETH_RPC_URL=<rpc> DEPLOYER_PRIVATE_KEY=<pk> ADMIN_ADDRESS=<admin> TOKEN_ADDRESS=<token> PAYEE_ADDRESS=<payee> \
./scripts/deploy-v01-eth.sh
```

This writes:
- `results/deploy-v01-eth.json`
- `examples/v01-console-config.json` (used by the UI "Load config" button)

Non-custodial defaults in deploy helper:
- `DEPLOY_NON_CUSTODIAL=1` (enabled)
- `SELLER_BOND_BPS=3000` (30%)
- `BILL_TTL_SECONDS=86400` (24h)

ETH-chain one-command smoke test (single on-chain settlement):

```bash
ETH_RPC_URL=<rpc> ENGINE_ADDRESS=<engine> TOKEN_ADDRESS=<token> \
PAYER_PRIVATE_KEY=<payer-pk> PAYEE_ADDRESS=<payee> \
./scripts/smoke-v01-eth.sh
```

This writes:
- `results/smoke-v01-eth.json`

Serve the browser console from repo root:

```bash
python3 -m http.server 8787
```

Open `http://localhost:8787/examples/v01-metamask-settlement.html` — control + monitoring on one page; export diagnosis JSON from the page when reporting issues.

Run focused v0.1 tests:

```bash
forge test --match-path "contracts/test/SettlementEngine.t.sol" -vv
```

See scope definition: `docs/V0_1_SCOPE.md`.

Client integration template:

- script: `examples/v01-quote-settlement.ts`
- guide: `docs/V0_1_CLIENT_TEMPLATE.md`

Batch validation (50-100 settlements):

- script: `examples/v01-batch-settlement.ts`
- guide: `docs/V0_1_BATCH_TEST.md`
- aggregate tool: `scripts/aggregate-results.ts`

## Community

Community docs hub:

- `docs/community/INDEX.md`

New contributors should start here:
- `docs/community/COMMUNITY_START_HERE.md`
