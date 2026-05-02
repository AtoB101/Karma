# Karma Non-Custodial Protocol

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
- Public vs private operations (releases without mixing repos): `docs/PUBLIC_PRIVATE_OPERATIONS.md`
- Fast onboarding: `docs/GET_STARTED.md`
- Commands cheat sheet: `docs/COMMANDS.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Public/private split policy: `docs/REPO_VISIBILITY_POLICY.md`
- Proof verification SOP: `docs/PROOF_VERIFICATION_SOP.md`
- Full ops workflow: `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt`
- One-shot diagnostics: `make doctor` (text report) / `make doctor-json` (JSON report)
- Support bundle zip: `make support-bundle` (collects doctor reports + key artifacts)
- Evidence schema check: `make validate-evidence-schema` (validates latest diagnosis JSON compatibility)
- Proof CI gate: `make ci-proof-gates` (schema compatibility + proof-index batch policy checks)
- Proof patrol profile: `make proof-patrol` (scheduled-style patrol with strict|balanced|lenient policy profiles)
- Agent safety guardian: `make agent-safety-guardian` (end-to-end self-check + risk grading + risk register ledger)
- Compatibility aliases: `make ci-proof-gate` and `make guardian` (mapped to current targets)
- Rule-gap model: `docs/RULE_GAP_RISK_MODEL_V01.md` (rule exploitation attack surface + alert strategy)
- Commercial readiness checklist: `docs/COMMERCIAL_READINESS_CHECKLIST_V01.md` (MUST/SHOULD/CAN commercial gate baseline)
- Command map: `docs/COMMAND_MAP_V01.md` (layered entrypoints: core/ops/safety/api)
- Data contracts: `docs/DATA_CONTRACTS_V01.md` (shared output schema/version/trace fields)
- System status: `make system-status` (aggregate commercial/proof/guardian/contracts into one health view)
- Ops one-shot summary: `make ops-summary` (generate and print a concise operational status snapshot)
- Ops alert export: `make ops-alert` (emit `results/ops-alert-latest.json` for IM/on-call integrations)
- Ops runbook hints: `make ops-summary` now prints severity and prioritized next-actions for on-call execution
- Release readiness: `make release-readiness` (one-command release preflight; fail-fast on any critical gate)
- API roadmap: `docs/API_ROADMAP_V01.md` (ecosystem API landing phases and governance baseline)
- OpenAPI contract: `openapi/karma-v1.yaml` (contract-first API spec for integration teams)
- API local run: `make api-run` (starts zero-dependency API service at `127.0.0.1:8811`)
- API smoke test: `make api-smoke` (verifies payment intent + evidence + risk alert routes)
- Commercialization gate: `make commercialization-gate` (outputs `commercial-ready | pilot-ready | not-ready` with action plan)
- Output contract gate: `make validate-output-contracts` (checks schemaVersion/source/traceId/generatedAt on latest artifacts)
- Static analysis gate: `make slither-gate` (runs Slither; fails when tool is missing or findings are reported)
- Security CI workflow: `.github/workflows/security-ci.yml` (PR gate chain: forge test + slither + release-readiness)
- Layered aliases: `make ops-*`, `make safety-*`, `make api-*` (clean command namespace, old targets still supported)
- Local CI gate: `make ci-local` (build + focused core tests, no env required)
- Env-aware CI gate: `make ci-local-env` (includes preflight with `.env`)
- Security baseline gate: `make security-baseline-guard` (blocks sensitive file/secret leaks)
- Owner watchdog dry run: `make owner-watchdog` (tests owner-change alert config and hooks)
- Private repo sync scaffold: `make private-repo-sync PRIVATE_REPO_DIR=../karma-internal`
- M4 roadmap: `docs/M4_ROADMAP_V01.md`

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
- Private scenario wrappers are intentionally excluded from this public repository.

## Frontend Console

```bash
python3 -m http.server 8787
```

Open `http://localhost:8787/examples/v01-metamask-settlement.html`.
The page defaults to non-custodial mode; legacy engine controls are hidden by default.

## Security

Security reporting policy and contact:
- `SECURITY.md`
