# P0 Sprint 1 Acceptance Test Matrix V1 (Private)

Status: Acceptance baseline  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_SPRINT_1_TASK_BREAKDOWN_V1.md`
- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`

## 1. Purpose

Define a test matrix for Sprint 1 so each task has objective pass/fail gates.

Coverage pillars:

1. Core function correctness
2. Error-path determinism
3. Replay/idempotency safety
4. Evidence and reconciliation integrity
5. Stop-loss trigger observability

## 2. Test execution policy

- All P0-critical cases must pass before sprint close.
- Any Sev-1 bug found in acceptance blocks sprint sign-off.
- Test evidence (logs, payloads, tx refs) must be archived.

Environment layers:

1. local deterministic environment
2. pilot-like staging environment

## 3. Matrix fields

Each test case must include:

- `caseId`
- `category`
- `preconditions`
- `steps`
- `expectedResult`
- `artifactRequired`
- `owner`
- `status` (`not_run|pass|fail|blocked`)

## 4. Functional acceptance matrix

## F-01 Provider registration

- caseId: `F-01`
- category: function
- preconditions: provider payload valid
- steps:
  1. call provider registration endpoint
  2. query provider record
- expectedResult:
  - provider created
  - providerId unique
- artifactRequired:
  - request/response payload
  - provider record snapshot
- owner: backend/platform

## F-02 Product creation (priced API)

- caseId: `F-02`
- category: function
- preconditions: provider exists
- steps:
  1. create product with per-call price
  2. query product by provider
- expectedResult:
  - product active
  - price metadata persisted
- artifactRequired:
  - payload
  - db or API record snapshot
- owner: backend/platform

## F-03 Authorization reference attach

- caseId: `F-03`
- category: function
- preconditions: user authorization reference exists
- steps:
  1. execute call with authorizationRef
  2. inspect paid_call event
- expectedResult:
  - authorizationRef recorded
  - call accepted if policy allows
- artifactRequired:
  - paid_call event json
- owner: risk/backend

## F-04 Call success triggers settlement

- caseId: `F-04`
- category: function
- preconditions: provider healthy; authorization valid
- steps:
  1. execute priced call
  2. inspect settlement record
- expectedResult:
  - exactly one settlement created
  - settlement status reaches confirmed (or deterministic pending->confirmed path)
- artifactRequired:
  - paid_call + settlement + evidence references
- owner: settlement/backend

## F-05 Evidence bundle generation

- caseId: `F-05`
- category: function
- preconditions: completed call exists
- steps:
  1. fetch evidence by callId
  2. validate required fields
- expectedResult:
  - evidence bundle exists and schema valid
  - traceId continuity preserved
- artifactRequired:
  - evidence json
  - validation output
- owner: data/ops

## 5. Exception-path matrix

## E-01 Provider timeout

- caseId: `E-01`
- category: error-path
- preconditions: force endpoint timeout
- steps:
  1. execute call
  2. inspect call + settlement records
- expectedResult:
  - call status `timeout`
  - no success settlement generated
- artifactRequired:
  - timeout logs
  - record snapshots
- owner: backend/routing

## E-02 Insufficient authorization

- caseId: `E-02`
- category: error-path
- preconditions: authorization limit below price
- steps:
  1. execute call
- expectedResult:
  - deterministic rejection
  - clear failure code
- artifactRequired:
  - response/error payload
- owner: risk/backend

## E-03 Invalid product/provider mapping

- caseId: `E-03`
- category: error-path
- preconditions: mismatch product/provider identifiers
- steps:
  1. execute call with invalid linkage
- expectedResult:
  - request rejected
  - no settlement side effect
- artifactRequired:
  - response + no-write proof
- owner: backend

## 6. Idempotency and replay matrix

## I-01 Duplicate call replay

- caseId: `I-01`
- category: idempotency
- preconditions: same idempotencyKey reused
- steps:
  1. submit call twice with same key
- expectedResult:
  - same logical call identity returned
  - no duplicate success settlement
- artifactRequired:
  - both responses
  - settlement uniqueness proof
- owner: settlement/backend

## I-02 Settlement commit replay

- caseId: `I-02`
- category: idempotency
- preconditions: same settlement idempotencyKey reused
- steps:
  1. submit settlement commit twice
- expectedResult:
  - single settlement record in terminal success state
- artifactRequired:
  - settlement query results
- owner: settlement

## 7. Reconciliation and integrity matrix

## R-01 Ledger parity check

- caseId: `R-01`
- category: reconciliation
- preconditions: batch of mixed success/failure calls
- steps:
  1. run reconciliation job
- expectedResult:
  - mismatch count = 0 or documented known exception
- artifactRequired:
  - reconciliation report
- owner: data/ops

## R-02 Trace continuity

- caseId: `R-02`
- category: integrity
- preconditions: call and settlement records exist
- steps:
  1. verify `traceId` linkage call -> settlement -> evidence
- expectedResult:
  - no broken trace chains
- artifactRequired:
  - trace validation output
- owner: data/platform

## 8. Stop-loss observability matrix

## S-01 Settlement success degradation signal

- caseId: `S-01`
- category: stop-loss
- preconditions: synthetic failure injection lowers success rate
- steps:
  1. run metrics pipeline
  2. inspect alerting/report
- expectedResult:
  - threshold breach detected
  - stop-loss warning recorded
- artifactRequired:
  - daily report snippet
  - alert event
- owner: ops/risk

## S-02 Dispute surge signal

- caseId: `S-02`
- category: stop-loss
- preconditions: simulated dispute inflow spike
- steps:
  1. ingest dispute events
  2. inspect dashboard + report
- expectedResult:
  - dispute threshold breach detected
  - escalation path visible
- artifactRequired:
  - dashboard snapshot
  - incident log reference
- owner: dispute/ops

## 9. Exit gates for sprint sign-off

Sprint 1 sign-off requires:

- all `F-*` cases pass
- all `I-*` cases pass
- `E-*` cases produce deterministic outcomes
- `R-01` parity check clean (or approved exception)
- no unresolved Sev-1 bugs

If any gate fails:

- sprint status forced to `incomplete`
- release gate remains blocked
- correction tasks added to top of next sprint queue

## 10. Test report template

Use this per run:

```text
Run ID:
Environment:
Date:
Owner:

Results:
- F pass/fail:
- E pass/fail:
- I pass/fail:
- R pass/fail:
- S pass/fail:

Blocking issues:
1)
2)

Sign-off:
- QA/Owner:
- Ops:
- Risk:
- Settlement:
```

