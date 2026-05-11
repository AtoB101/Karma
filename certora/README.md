# Certora formal verification (Karma core)

These specs target the five core contracts under `karma-core/contracts/core/`. They are written for **CVL 2** (function-style `methods` entries, `sig:` where needed, envfree call discipline).

## Prerequisites

- Certora CLI installed and `CERTORAKEY` set (see [Certora installation](https://docs.certora.com/)).
- Solidity compiler matching `foundry.toml` (e.g. `solc8.28`).

## Run (from repository root)

Use `certoraRun` with the contract path **and** the spec. Example for KYA:

```bash
certoraRun karma-core/contracts/core/KYARegistry.sol:KYARegistry \
  --verify KYARegistry:certora/specs/KYARegistry.spec \
  --solc solc8.28
```

Repeat for each contract, swapping the Solidity path, contract name, and spec file:

| Contract                 | Spec                                      |
|--------------------------|-------------------------------------------|
| `KYARegistry`            | `certora/specs/KYARegistry.spec`          |
| `CircuitBreaker`         | `certora/specs/CircuitBreaker.spec`       |
| `AuthTokenManager`       | `certora/specs/AuthTokenManager.spec`     |
| `SettlementEngine`       | `certora/specs/SettlementEngine.spec`     |
| `NonCustodialAgentPayment` | `certora/specs/NonCustodialAgentPayment.spec` |

## Foundry / IR

This repo enables `via_ir` in Foundry. If the Prover fails on IR-only code paths, re-run with Certora’s documented flags for your CLI version (often a disable-IR or alternate build mode). Specs here avoid deep `Quote` parametric rules so `SettlementEngine` stays lightweight.

## Audit posture

Passing Certora jobs prove **the stated CVL properties** only. They complement but do not replace independent third-party review, operational security, and economic threat modeling.
