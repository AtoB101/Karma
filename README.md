# TrustChain Non-Custodial Protocol

This repository now uses a single architecture story centered on `NonCustodialAgentPayment`.
User funds stay in user wallets, while on-chain accounting enforces lock/reserve/dispute state transitions.

## Golden Path (3 commands)

```bash
cp .env.example .env
./scripts/dev-up.sh --from-env
python3 -m webbrowser "http://127.0.0.1:8790/examples/v01-metamask-settlement.html?ts=$(date +%s)"
```

Or shorter:

```bash
cp .env.example .env
make quickstart
```

If your shell does not have `python3 -m webbrowser`, open this URL manually:
`http://127.0.0.1:8790/examples/v01-metamask-settlement.html`

Quick docs:
- Fast onboarding: `docs/GET_STARTED.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Full ops workflow: `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt`

## Core Modules

- `NonCustodialAgentPayment`: bill lifecycle, dual-side lock model, dispute and batch settlement
- `SettlementEngine`: direct transfer settlement path with strict EIP-712 checks
- `AuthTokenManager`: auth token consumption and replay-safe signature validation
- `KYARegistry`: identity registration and permission hash management
- `CircuitBreaker`: emergency pause and agent-level risk control

## Prerequisites

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
forge --version
forge install foundry-rs/forge-std
```

## Build And Test

```bash
forge build
forge test -q
```

Focused non-custodial test runs:

```bash
forge test --match-path "contracts/test/NonCustodialAgentPayment.t.sol" -vv
forge test --match-path "contracts/test/NonCustodialAgentPaymentReentrancy.t.sol" -vv
forge test --match-path "contracts/test/NonCustodialAgentPayment.invariant.t.sol" -vv
```

## Sepolia Deployment

Deploy only the non-custodial core:

```bash
ETH_RPC_URL=<rpc> \
DEPLOYER_PRIVATE_KEY=<pk> \
ADMIN_ADDRESS=<admin> \
TOKEN_ADDRESS=<token> \
./scripts/deploy-v01-eth.sh
```

Artifacts:

- `results/deploy-v01-eth.json`
- `examples/v01-console-config.json`

Optional batch fuses:

- `BATCH_MODE_ENABLED` (default `1`)
- `BATCH_CIRCUIT_BREAKER` (default `0`)

## Integration And Operations

- One-step smoke: `./scripts/smoke-v01-eth.sh`
- Non-custodial batch integration: `./scripts/integration-v01-noncustodial-batch.sh`
- Scenario wrappers: `./scripts/integration-openclaw-run.sh`, `./scripts/integration-hermes-run.sh`
- Full NC-205 pipeline: `./scripts/run-nc205-full.sh`

## Frontend Console

```bash
python3 -m http.server 8787
```

Open `http://localhost:8787/examples/v01-metamask-settlement.html`.
The page defaults to non-custodial mode; legacy engine controls are hidden by default.

## Primary Ops Doc

See `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt` for deploy, smoke, integration, and reporting workflows.
