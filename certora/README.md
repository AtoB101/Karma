# Certora formal verification (Karma core)

These specs target the five core contracts under `karma-core/contracts/core/`. They are written for **CVL 2** (function-style `methods` entries, `sig:` where needed, envfree call discipline).

## Prerequisites

- **Certora CLI** installed and **`CERTORAKEY`** set ([Certora installation](https://docs.certora.com/)).
- **Java 21+** recommended for the Prover toolchain.
- **Solc** aligned with `foundry.toml` (this repo uses **0.8.28** with **`via_ir`**).

## Configuration (`certora/conf/*.json`)

- **`solc`**: set to **`/usr/local/bin/solc`** for **Certora Cloud** compatibility. On a dev machine, install solc 0.8.28 (e.g. via `solc-select`) and point to it, or symlink to `/usr/local/bin/solc`, or edit the conf file to your absolute path.
- **`solc_via_ir`**: **`true`**, matching Foundry `via_ir = true` in the repo root `foundry.toml`.

## Run (from repository root)

### Option A — JSON config (recommended for CI / cloud)

```bash
certoraRun certora/conf/KYARegistry.conf
```

Additional Prover flags go **after** the config path, e.g.:

```bash
certoraRun certora/conf/KYARegistry.conf --disable_local_typechecking
```

Use one conf per contract: `KYARegistry.conf`, `CircuitBreaker.conf`, `AuthTokenManager.conf`, `SettlementEngine.conf`, `NonCustodialAgentPayment.conf`.

### Option B — Run all five (script)

```bash
./scripts/certora-verify.sh
# with extra flags forwarded to each job:
./scripts/certora-verify.sh --disable_local_typechecking
```

The script invokes `certoraRun "${conf}" "$@"` so the config file is the **first positional argument** (no `--conf`).

### Option C — CLI without conf file

```bash
certoraRun karma-core/contracts/core/KYARegistry.sol:KYARegistry \
  --verify KYARegistry:certora/specs/KYARegistry.spec \
  --solc "$(which solc)" \
  --solc_via_ir true
```

| Contract                 | Spec                                      |
|--------------------------|-------------------------------------------|
| `KYARegistry`            | `certora/specs/KYARegistry.spec`          |
| `CircuitBreaker`         | `certora/specs/CircuitBreaker.spec`       |
| `AuthTokenManager`       | `certora/specs/AuthTokenManager.spec`     |
| `SettlementEngine`       | `certora/specs/SettlementEngine.spec`     |
| `NonCustodialAgentPayment` | `certora/specs/NonCustodialAgentPayment.spec` |

## SettlementEngine scope (design)

This batch **does not** include parametric **`QuoteTypes.Quote` / `submitSettlement`** rules. That avoids brittle struct wiring across Certora CLI versions and keeps the first pass green. Extend with quote / batch settlement properties in a **follow-up spec** once your toolchain accepts the struct in `methods` cleanly.

See also `certora/FIXLIST.md`.

## Audit posture

Passing Certora jobs prove **the stated CVL properties** only. They complement but do not replace independent third-party review, operational security, and economic threat modeling.

## Troubleshooting

- **`AuthTokenManager.spec`**: no `import` of `Types.sol`; `Types.OperationType` is taken from the compiled contract scene.
- **Zero address in CVL**: use literal **`0`**, not Solidity’s `address(0)`.
- **`bytes32` vs zero**: use **`to_bytes32(0)`** or a full **64-hex** literal; short **`0x0`** is not `bytes32`.
- **`payable` in `methods {}`**: some builds reject `payable` in the methods block; entries may omit it while rules use `e.msg.value` and **`=> NONDET`** on the summarized call.
- **State-changing methods**: for **secondary** contracts or heavily wrapped calls, non-`envfree` entries often need a summary such as **`=> NONDET`**. For the **primary contract under verification**, summarizers may be **unused** (Certora INFO); plain `external` is OK unless you see “has no effect” warnings.
- **`view` + `block.timestamp`**: do **not** mark as `envfree` (e.g. `KYARegistry.verifyDID`); call with **`verifyDID(e, agent)`**.
- **Local typechecking failures**: after installing **Java 21**, if issues persist, see Certora docs for **`--disable_local_typechecking`** (escape hatch only).
