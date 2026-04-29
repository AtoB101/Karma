# M1 Acceptance Checklist (Policy + Evidence)

This checklist defines formal acceptance criteria for M1, M1.1, and M1.2.

## Scope

- M1: on-chain policy controls + structured evidence export
- M1.1: policy enforcement extended to batch-critical paths + policy UI panel
- M1.2: readable policy error mapping + policy decision fields in evidence

---

## 1) Contract Policy Controls (M1)

- [ ] `setPolicy(...)` is available and updates policy config for caller.
- [ ] `getPolicy(address)` returns expected limits and flags.
- [ ] `getPolicyUsage(address)` returns usage counters.
- [ ] `setPolicyPayee(...)` updates payee rule.
- [ ] `setPolicyToken(...)` updates token rule.
- [ ] `createBill(...)` enforces:
  - [ ] `enabled` gate
  - [ ] `perTxLimit`
  - [ ] `dailyLimit`
  - [ ] `maxTxPerWindow` over `windowSeconds`
  - [ ] payee allowlist when enabled
  - [ ] token allowlist when enabled

### Evidence in tests

- [ ] Unit tests include policy-blocked create bill scenarios.
- [ ] Unit tests include policy usage progression/reset behavior.

---

## 2) Batch Path Policy Controls (M1.1)

- [ ] `closeBatch(...)` is blocked when policy scope/rate checks fail.
- [ ] `settleBatch(...)` is blocked when policy projected amount exceeds limits.
- [ ] Batch scope naming is explicit in docs and usage:
  - [ ] `batch:close`
  - [ ] `batch:settle`

### Evidence in tests

- [ ] Unit test covers closeBatch policy rejection.
- [ ] Unit test covers settleBatch policy rejection.

---

## 3) Frontend Policy Operations (M1.1)

- [ ] Console has policy control panel.
- [ ] Operator can apply policy via UI.
- [ ] Operator can refresh/read policy and usage via UI.
- [ ] Operator can allow payee via UI.
- [ ] Operator can allow token via UI.
- [ ] Policy snapshot is visible in UI (`policySnapshot` panel text).

---

## 4) Readable Policy Error Mapping (M1.2)

- [ ] Runtime classifier maps policy errors to explicit kinds:
  - [ ] `policy_violation`
  - [ ] `policy_daily_limit_exceeded`
  - [ ] `policy_per_tx_limit_exceeded`
  - [ ] `policy_counterparty_not_allowed`
  - [ ] `policy_scope_not_allowed`
  - [ ] `policy_expired`
- [ ] UI output includes actionable guidance when policy errors happen.

---

## 5) Evidence Export Fields (M1 + M1.2)

- [ ] Export includes frozen top-level fields:
  - [ ] `reportVersion`
  - [ ] `evidenceVersion`
  - [ ] `traceId`
  - [ ] `app`
  - [ ] `exportedAt`
- [ ] Export includes frozen snapshots:
  - [ ] `authSnapshot`
  - [ ] `requestSnapshot`
  - [ ] `executionSnapshot`
  - [ ] `riskSnapshot`
- [ ] `requestSnapshot.policySnapshot` is present.
- [ ] `requestSnapshot.policyDecision` is present.
- [ ] `executionSnapshot.diagnostics[*].traceId` is present.
- [ ] `executionSnapshot.transactionHistory[*].traceId` is present.

---

## 6) Schema Freeze and Compatibility

- [ ] `docs/EVIDENCE_SCHEMA_V01.md` reflects actual exported JSON shape.
- [ ] Schema freeze note is included:
  - [ ] no field removals/renames in v0.1.x
  - [ ] additive-only changes for patch updates
  - [ ] major version bump for breaking changes

---

## 7) Operational Validation Commands

Local (Foundry required):

```bash
forge test --match-path "contracts/test/NonCustodialAgentPayment.t.sol" -vv
```

Frontend quick check:

```bash
python3 -m http.server 8790
```

Open:

```text
http://127.0.0.1:8790/examples/v01-metamask-settlement.html
```

---

## Acceptance Decision

- [ ] PASS
- [ ] PARTIAL PASS (list blocked items)
- [ ] FAIL (list must-fix items)
