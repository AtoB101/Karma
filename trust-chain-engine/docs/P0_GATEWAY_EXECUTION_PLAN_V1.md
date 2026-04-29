# P0 Gateway Execution Plan V1 (Private)

Status: Ready for implementation  
Scope: `trust-chain-engine` only (do not publish)

Related strategy:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`

## 1. Goal and constraints

Goal:

- Ship a usable "AI Agent paid API auto-settlement gateway" that produces real paid calls.

Hard constraints:

1. Must preserve non-custodial settlement guarantees.
2. Must support one-call-one-settlement evidence path.
3. Must be operable by a small team with low integration overhead.
4. Must avoid non-essential features until traction thresholds are met.

## 2. Scope (MVP only)

In scope:

1. Single API product (BTC price query) with per-call pricing.
2. Provider registration and pricing config.
3. User pre-authorization policy (wallet side).
4. Agent call execution + delivery proof generation.
5. Automatic settlement and evidence export.
6. Minimal ops dashboard for daily metrics.

Out of scope:

- Multi-provider marketplace matching
- Dynamic pricing auctions
- Cross-chain settlement
- Advanced arbitration automation
- Enterprise multi-tenant control plane

## 3. System modules and ownership

### 3.1 `risk-engine/`

Responsibilities:

- Pre-call risk checks (`allow`, `review`, `deny`)
- Velocity and abuse protection
- Basic anomaly flags for P0

Owner role:

- Risk engineer

### 3.2 `settlement-optimizer/`

Responsibilities:

- Build settlement intents from completed calls
- Control retry/idempotency semantics
- Queue and batch only where safe (P0 keeps policy conservative)

Owner role:

- Settlement engineer

### 3.3 `routing-engine/`

Responsibilities:

- Route calls to registered endpoint version
- Fallback only within same provider policy

Owner role:

- Routing engineer

### 3.4 `dispute-engine/`

Responsibilities:

- Generate dispute packet from evidence
- Provide operator decision support (manual final decision in P0)

Owner role:

- Dispute operations

### 3.5 `analytics-engine/`

Responsibilities:

- Daily metrics aggregation for success criteria
- Conversion/repeat usage snapshots

Owner role:

- Data/analytics engineer

### 3.6 `enterprise-dashboard/` + `internal-admin/`

Responsibilities:

- Provider onboarding status
- Call/settlement timeline view
- Incident and dispute queue

Owner role:

- Platform ops

## 4. API and interface contracts (P0)

## 4.1 External integration contract

1. `POST /v1/providers/register`
   - Registers provider profile and settlement address.
2. `POST /v1/products/create`
   - Creates a priced API product (per-call amount).
3. `POST /v1/authorizations/create`
   - Records user authorization policy reference.
4. `POST /v1/calls/execute`
   - Agent triggers call and gets response + callId.
5. `POST /v1/settlements/commit`
   - Commits settlement intent and returns tx reference/evidence id.

## 4.2 Internal private interfaces

Internal SDK adapters (private implementation):

- `RiskEngine.check(transactionContext) -> RiskDecision`
- `RoutingEngine.selectRoute(callContext) -> RoutePlan`
- `SettlementOptimizer.plan(callResult) -> SettlementPlan`
- `AnalyticsEngine.record(event) -> void`

Versioning:

- Must follow `docs/INTERFACE_COMPATIBILITY_POLICY_V1.md`

## 5. Data contracts (minimum)

## 5.1 Paid call event

Required fields:

- `callId`
- `providerId`
- `productId`
- `userId`
- `agentId`
- `requestHash`
- `responseHash`
- `startedAt`
- `completedAt`
- `status` (`success|failed|timeout`)

## 5.2 Settlement event

Required fields:

- `settlementId`
- `callId`
- `amount`
- `token`
- `chainId`
- `txHash`
- `settledAt`
- `status` (`pending|confirmed|failed|disputed`)

## 5.3 Evidence bundle

Required fields:

- `evidenceId`
- `callId`
- `settlementId`
- `requestDigest`
- `responseDigest`
- `authorizationRef`
- `riskDecisionRef`
- `createdAt`

## 6. Milestones and exit criteria

## M0: Foundation wiring

Tasks:

- Define data schema files
- Create endpoint skeletons
- Wire module stubs and logging

Exit:

- All P0 APIs return contract-valid responses in local env

## M1: Functional path

Tasks:

- Implement provider/product/authorization flow
- Implement call execution and settlement intent generation
- Persist evidence bundle records

Exit:

- End-to-end simulated run succeeds 20/20 times

## M2: Reliability hardening

Tasks:

- Idempotency on call and settlement
- Retry policy with dedup guard
- Timeout/error taxonomy and observability panels

Exit:

- Settlement success >= 95% on controlled runs

## M3: Real-user pilot

Tasks:

- Onboard first provider
- Onboard first 10 users
- Run paid sessions and collect metrics

Exit:

- Meets all go/no-go thresholds from GTM strategy V1

## 7. Acceptance test set (must pass)

Functional:

1. Provider can create priced API product.
2. User authorization can be attached to call.
3. Agent call success triggers settlement automatically.
4. Evidence bundle is generated and queryable per call.

Failure and edge:

5. Timeout call does not settle as success.
6. Duplicate call request does not double settle.
7. Insufficient authorization fails deterministically.
8. Dispute packet generation works from one settlement record.

## 8. Risk register for P0 execution

Top execution risks:

1. Call/settlement mismatch due to async failures
2. Duplicate settlement on retries
3. Poor first-user onboarding causing no paid volume
4. Metrics blind spots delaying corrective action

Mitigations:

- Strict idempotency keys across call and settlement layers
- Hard reconciliation job between call ledger and settlement ledger
- Guided onboarding script for first provider/users
- Daily dashboard with red-line alerts

## 9. Operational cadence

Daily:

- Review paid calls, settlement success, dispute queue
- Review stop-loss triggers

Twice weekly:

- Risk/route/pricing tuning review
- Provider and user feedback review

Weekly:

- Decision checkpoint: continue, correct, or pause expansion

## 10. Stop-loss and decision policy

Immediate freeze on scope expansion if any condition holds:

1. Settlement success < 95% for two straight days
2. Dispute rate > 8% for three straight days
3. Repeat ratio < 20% after onboarding wave

During freeze:

1. Reliability bug backlog gets highest priority
2. No new feature category accepted
3. Resume only after two consecutive healthy reporting cycles

## 11. Task board template (ready to assign)

Track each work item with:

- `id`
- `module`
- `owner`
- `priority`
- `status` (`todo|in_progress|blocked|done`)
- `acceptance`
- `riskNotes`

Suggested first tickets:

1. Define P0 schemas (`paid_call`, `settlement`, `evidence`)
2. Build provider + product endpoints
3. Implement authorization reference path
4. Implement call execution with route selection
5. Implement settlement planner with idempotency
6. Build evidence bundle writer and query endpoint
7. Build minimal operator metrics dashboard
8. Add acceptance test suite for section 7

## 12. Deliverables checklist

- [ ] P0 API spec finalized
- [ ] Data contracts checked into repo
- [ ] End-to-end demo script executable
- [ ] Daily metrics dashboard online
- [ ] Pilot report generated with real transaction references

