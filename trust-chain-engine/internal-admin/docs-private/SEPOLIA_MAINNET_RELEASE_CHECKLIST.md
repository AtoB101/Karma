# Sepolia to Mainnet Release Checklist (v0.1)

## 1) Scope Lock

- Freeze v0.1 scope to settlement flow only.
- No new modules or architecture changes after this point.
- Tag candidate commit and keep artifact hashes.

## 2) Contract Readiness

- `forge build` passes with pinned compiler settings.
- Core tests pass (`SettlementEngine.t.sol`, `ScenarioFlow.t.sol`).
- Re-run stress scripts with current artifact schema (`txHashes` field).
- Verify `setTokenAllowed()` behavior and pause/unpause controls.
- If using `settleBatch()`, validate:
  - length mismatch reverts (`InvalidBatchInput`)
  - nonce progression correctness for sequential quotes
  - replay protection per quote ID

## 3) Security Baseline

- Ensure no privileged path allows fund transfer by non-authorized signer.
- Ensure signature domain matches deployed contract + chain ID.
- Ensure `tokenAllowed` is admin-gated and auditable.
- Ensure replay protection (`executedQuotes`) and nonce checks are intact.
- Run static checks and audit review before mainnet.

## 4) Sepolia Validation Gate

- Deploy candidate bytecode to Sepolia.
- Configure allowlist token and funding/approval.
- Single run must pass end-to-end.
- Batch 50 and batch 100 success rate each >= 95% (target 100%).
- Produce:
  - `results/run-050.json`
  - `results/run-100.json`
  - `results/aggregate-summary.json`
- Confirm failures are classified (no opaque "Other" spikes).

## 5) Operational Readiness

- Define owner/admin key policy (hardware wallet or multisig preferred).
- Define incident process:
  - pause criteria
  - rollback/containment steps
  - communication path
- Define monitoring:
  - failed settlement count
  - nonce mismatch error rate
  - token transfer failure alerts

## 6) Mainnet Go/No-Go

Go only if all below are true:

- Security review completed
- Sepolia gate passed
- Runbook and monitoring configured
- Stakeholders sign-off completed (engineering + QA + ops)

## 7) Post-Deploy Verification

- Verify deployed addresses and constructor args.
- Perform one controlled low-value settlement on mainnet.
- Confirm event traces and balances.
- Archive report set:
  - `docs/FINAL_TEST_REPORT.md`
  - `docs/FINAL_TEST_REPORT_CN.md`
  - `docs/TEST_REPORT_INDEX.md`
