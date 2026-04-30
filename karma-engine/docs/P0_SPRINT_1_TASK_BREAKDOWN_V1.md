# P0 Sprint 1 Task Breakdown V1 (Private)

Status: Sprint-ready  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_IMPLEMENTATION_BACKLOG_EPICS_V1.md`
- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_RELEASE_GATING_AND_CHANGE_FREEZE_V1.md`

## 1) Sprint goal (7 days)

Deliver a deterministic end-to-end path:

1. provider/product/authorization setup
2. paid call execution
3. settlement commit
4. evidence bundle generation
5. reconciliation check

Hard sprint exit:

- 20/20 controlled runs pass
- no duplicate settlement
- evidence generated for all runs

## 2) Team and ownership

- Sprint owner: Platform PM
- Risk owner: Risk engineer
- Settlement owner: Settlement engineer
- Routing owner: Routing engineer
- Data/ops owner: Analytics + Ops

## 3) Task board (ready to assign)

## T1. Provider + Product APIs

- Priority: P0
- Owner: Backend engineer A
- Estimate block: 1.5 days
- Dependencies: none
- Deliverables:
  - `POST /v1/providers/register`
  - `POST /v1/products/create`
- Acceptance:
  - create provider/product successfully
  - persistence records retrievable
  - duplicate create handled idempotently

## T2. Authorization reference path

- Priority: P0
- Owner: Backend engineer A
- Estimate block: 1 day
- Dependencies: T1
- Deliverables:
  - `POST /v1/authorizations/create`
  - `authorizationRef` linkage for call execution
- Acceptance:
  - call cannot execute without valid authorization
  - insufficient authorization fails deterministically

## T3. Call execution route + risk gate

- Priority: P0
- Owner: Routing engineer + Risk engineer
- Estimate block: 1.5 days
- Dependencies: T1, T2
- Deliverables:
  - route selection (`routeRef`)
  - risk decision (`allow/review/deny`) with `riskDecisionRef`
- Acceptance:
  - allow path executes
  - deny path blocks settlement side-effect
  - review path lands in review queue

## T4. Settlement commit with idempotency

- Priority: P0
- Owner: Settlement engineer
- Estimate block: 1.5 days
- Dependencies: T3
- Deliverables:
  - `POST /v1/settlements/commit`
  - idempotency guard for retry safety
- Acceptance:
  - one successful call -> max one successful settlement
  - repeated request with same key returns same logical settlement
  - failed/timeout call does not settle as success

## T5. Evidence bundle writer

- Priority: P0
- Owner: Backend engineer B
- Estimate block: 1 day
- Dependencies: T3, T4
- Deliverables:
  - evidence bundle creation and lookup
  - trace continuity (`callId -> settlementId -> evidenceId`)
- Acceptance:
  - evidence generated for each call attempt
  - required fields conform to data contract doc
  - missing evidence count == 0 on test run

## T6. Reconciliation job (call vs settlement)

- Priority: P0
- Owner: Data/ops engineer
- Estimate block: 1 day
- Dependencies: T4, T5
- Deliverables:
  - daily reconciliation script/report
  - mismatch classification output
- Acceptance:
  - mismatch report generated with categories
  - duplicate detection included
  - zero mismatch in controlled run baseline

## T7. Acceptance test pack

- Priority: P0
- Owner: QA engineer
- Estimate block: 1 day
- Dependencies: T1..T6
- Deliverables:
  - scenario tests for success/failure/timeout/retry
- Acceptance:
  - 20/20 controlled run passes
  - test report archived with trace ids

## 4) Daily execution ritual (sprint)

Daily standup inputs:

1. yesterday done
2. today plan
3. blockers
4. metric pulse:
   - settlement success
   - duplicate count
   - evidence completeness

Daily decision:

- `continue` / `correct` / `freeze`

## 5) Blocker handling SLA

- Critical blocker (P0 path blocked): assign owner within 30 min, escalate same day
- Non-critical blocker: assign owner within business day
- Any blocker > 24h: mandatory escalation to sprint owner

## 6) Sprint risk list

1. Asynchronous call/settlement drift
2. Retry path causing duplicate commits
3. Missing evidence linkage
4. Provider instability during tests

Mitigations:

- strict idempotency
- reconciliation every run
- trace continuity checks in CI
- fallback provider disabled by default in sprint

## 7) Definition of Ready (DoR)

Task can start only if:

- acceptance criteria written
- dependency tasks identified
- owner assigned
- required API/schema references linked

## 8) Definition of Done (DoD)

Task is done only if:

- code/logic merged to sprint branch
- tests pass for target behavior
- artifacts produced (logs/report/screenshots where needed)
- operational notes updated in doc

## 9) Sprint exit report template

- Sprint period:
- Completed tasks:
- Deferred tasks:
- Exit metrics:
  - controlled runs:
  - settlement success rate:
  - duplicate settlement count:
  - missing evidence count:
- Decision: `pass` / `partial` / `fail`
- Next sprint prerequisites:
