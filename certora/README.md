# Certora formal verification (Karma core)

These specs target core contracts under `karma-core/contracts/core/` that still have CVL coverage.
Legacy NonCustodial / SettlementEngine specs were removed with the `_legacy` contracts.

## Prerequisites

- Certora CLI installed and `CERTORAKEY` set (see [Certora installation](https://docs.certora.com/)).
- Solidity compiler matching `foundry.toml` (e.g. `solc8.28`).

## Run (from repository root)

### Option A — JSON conf (recommended)

```bash
certoraRun --conf certora/conf/KYARegistry.conf
```

Repeat with `CircuitBreaker.conf`, `AuthTokenManager.conf`.

### Option B — CLI without conf file

```bash
certoraRun karma-core/contracts/core/KYARegistry.sol:KYARegistry \
  --verify KYARegistry:certora/specs/KYARegistry.spec \
  --solc solc8.28
```

| Contract           | Spec                                  |
|--------------------|---------------------------------------|
| `KYARegistry`      | `certora/specs/KYARegistry.spec`      |
| `CircuitBreaker`   | `certora/specs/CircuitBreaker.spec`   |
| `AuthTokenManager` | `certora/specs/AuthTokenManager.spec` |

Active settlement path for product work is `KarmaBilateral.sol` (add CVL coverage in a follow-up).

## Audit posture

Passing Certora jobs prove **the stated CVL properties** only. They complement but do not replace independent third-party review.
