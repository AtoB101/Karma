# Security Verification Status

Karma maintains a layered security verification approach that combines tests,
fuzzing, static analysis, and formal verification.

Investor- and partner-facing one-page bilingual summary:
`docs/SECURITY_SUMMARY_CN_EN.md`

## Verification Matrix (Current Baseline)

| Layer | Tool | Type | Status |
|---|---|---|---|
| 1 | Forge Unit Tests | Functional correctness | 55/55 passing |
| 2 | Forge Invariant Tests | Fuzzed safety invariants | 256 rounds, 0 revert |
| 3 | Slither | Static analysis | 22 findings, no fund-loss critical |
| 4 | Echidna | Stateful fuzz attack simulation | 100,000 rounds, 0 violation |
| 5 | Certora Prover | Formal methods proof | 6/6 rules verified |

## Certora Rules Verified

1. `confirmWorksOnPending`  
   Confirm can only apply when bill state is `Pending`.
2. `cancelWorksOnPending`  
   Cancel can only apply when bill state is `Pending`.
3. `finalStateNoTransition`  
   Final states are terminal and cannot transition back.
4. `splitResolvedMath`  
   Split and settlement math is internally consistent.
5. `unlockPreservesReserved`  
   Unlock operations do not incorrectly reduce reserved accounting.
6. `lockFundsIncreasesLocked`  
   Lock operations correctly increase locked accounting.

## Scope Notes

- Formal verification proves the specified properties, not total absence of all bugs.
- The strongest assurance currently targets state-machine safety and settlement accounting.
- Additional assurance comes from cross-layer overlap (unit + invariant + fuzz + static + formal).

## Reproducibility

This repository includes Foundry configuration and pinned dependencies (`foundry.lock`, `lib/forge-std`) for reproducible test runs.

Core local commands:

```bash
forge test -vv
forge test --match-path "contracts/test/LockPoolManager.invariant.t.sol" -vv
forge test --match-path "contracts/test/CrossModuleAccounting.invariant.t.sol" -vv
forge test --match-path "contracts/test/BillStateMachine.invariant.t.sol" -vv
./scripts/run_focus_demo.sh
```

For static analysis, Echidna, and Certora, run the project's corresponding tool pipelines in your CI/security environment and archive result artifacts with commit hashes.
