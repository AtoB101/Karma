# P0 Provider Onboarding Checklist V1 (Private)

Status: Operational checklist  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`
- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`

## 1. Purpose

Define the executable process to onboard the first paid API provider for P0:

1. provider readiness validation
2. pricing and settlement readiness
3. risk-control activation
4. end-to-end settlement rehearsal
5. go-live acceptance and rollback preparation

This checklist is a gate: if any must-pass item fails, onboarding is blocked.

## 2. Roles and approvals

Required roles:

- Provider Success Lead (owner of onboarding)
- Risk Engineer (risk policy sign-off)
- Settlement Engineer (settlement path sign-off)
- Platform Ops (runbook and incident readiness)
- Compliance/Legal Reviewer (if required by jurisdiction)

Approval policy:

- No single-person go-live approval
- At least 2 approvers required:
  - one from engineering (risk/settlement)
  - one from operations/compliance

## 3. Provider pre-qualification (must pass)

## 3.1 Identity and endpoint legitimacy

- [ ] Provider legal entity or accountable operator identified
- [ ] Official domain ownership verified
- [ ] API endpoint ownership verified (DNS/TLS cert alignment)
- [ ] Contact channels verified (incident + billing + technical)

Evidence to attach:

- provider profile record id
- domain verification artifact
- point-of-contact list with backup contacts

## 3.2 Service quality baseline

- [ ] Endpoint uptime evidence available (last 7 days)
- [ ] P95 latency baseline provided
- [ ] Error code taxonomy documented
- [ ] Rate limit policy documented

Threshold guidance (P0):

- uptime >= 99.0% (7-day baseline)
- p95 latency <= 1500 ms for priced endpoint

## 3.3 Integration compatibility

- [ ] Request/response schema mapped to gateway contract
- [ ] Deterministic response fields identified for proof hashing
- [ ] Versioning policy declared by provider
- [ ] Breaking change notice window agreed (minimum 7 days)

## 4. Commercial and settlement setup (must pass)

## 4.1 Product and pricing

- [ ] Single priced API product defined (`productId`)
- [ ] Price unit and smallest settlement unit documented
- [ ] Currency/token pair approved for P0
- [ ] Refund/dispute commercial policy documented

## 4.2 Settlement destination

- [ ] Payee wallet ownership verified
- [ ] Settlement network (`chainId`) confirmed
- [ ] Token contract allowlist validated
- [ ] Dust/minimum payout threshold confirmed

## 4.3 Billing safety controls

- [ ] Daily payout cap configured
- [ ] Per-user spend cap configured
- [ ] Duplicate settlement guard enabled (idempotency keys)
- [ ] Reconciliation job enabled (call ledger vs settlement ledger)

## 5. Risk controls activation (must pass)

## 5.1 Baseline policy

- [ ] Provider risk tier assigned (`low|medium|high`)
- [ ] Velocity limits configured (calls/min, calls/hour)
- [ ] Abuse detection thresholds configured
- [ ] Timeout and retry policy configured

## 5.2 Decision path validation

- [ ] `allow` path tested
- [ ] `review` path tested (manual operator queue)
- [ ] `deny` path tested (no settlement side-effect)
- [ ] All risk decisions traceable via `riskDecisionRef`

## 5.3 Alerting

- [ ] Alert rules configured for failure-rate spikes
- [ ] Alert rules configured for dispute-rate spikes
- [ ] On-call routing verified
- [ ] Escalation contacts verified

## 6. End-to-end rehearsal (must pass before go-live)

Run controlled rehearsal with at least 20 calls:

- [ ] 15 successful calls
- [ ] 3 failed calls (deterministic failure path)
- [ ] 2 timeout calls

Required assertions:

- [ ] exactly one settlement per successful call
- [ ] no settlement on failed/timeout calls unless explicit compensated policy
- [ ] evidence bundle generated for every call attempt
- [ ] trace continuity valid: call -> settlement -> evidence
- [ ] no duplicate settlement during retries

## 7. Go-live acceptance checklist

Go-live can proceed only if all are true:

- [ ] provider pre-qualification passed
- [ ] settlement configuration passed
- [ ] risk controls active and validated
- [ ] rehearsal pass report archived
- [ ] rollback runbook approved
- [ ] incident commander assigned for launch window

Launch window requirements:

- [ ] at least one risk engineer on standby
- [ ] at least one platform ops on standby
- [ ] live metrics dashboard open and monitored

## 8. Required evidence pack (for audit and dispute)

Store under onboarding evidence directory:

- [ ] provider registration payload + response
- [ ] product creation payload + response
- [ ] authorization sample records
- [ ] rehearsal call/settlement/evidence exports
- [ ] risk policy snapshot id
- [ ] settlement policy snapshot id
- [ ] go-live approval records (names + timestamps)

Minimum retention:

- onboarding evidence: 1 year hot + 3 years cold

## 9. Rollback and emergency controls

Rollback triggers (any one):

1. settlement success rate < 95% during first launch day
2. duplicate settlement incident confirmed
3. dispute rate > 8% within first 24h
4. critical provider endpoint instability

Immediate rollback steps:

1. set provider route status to `disabled`
2. pause new settlement commits for provider
3. keep evidence collection active
4. run reconciliation to identify unsettled or inconsistent records
5. publish internal incident summary and corrective actions

Rollback exit criteria:

- root cause identified
- patch validated in rehearsal environment
- re-approval from risk + settlement + ops leads

## 10. Post-launch day-1 and day-7 checkpoints

## Day-1 checkpoint

- [ ] paid call volume > 0
- [ ] settlement success rate >= 95%
- [ ] dispute rate <= 8%
- [ ] no unresolved critical incidents

## Day-7 checkpoint

- [ ] repeat usage ratio >= 20%
- [ ] at least one successful dispute drill completed
- [ ] reconciliation mismatch count == 0 (or documented exception)
- [ ] provider SLA adherence within agreed range

If day-7 fails:

- freeze provider expansion
- open corrective action plan
- re-run controlled rehearsal before scaling

## 11. Execution template (fill per provider)

Provider record:

- `providerId`:
- `serviceName`:
- `endpointBaseUrl`:
- `riskTier`:
- `productId`:
- `pricePerCall`:
- `payeeWallet`:
- `chainId`:
- `token`:

Approvals:

- Engineering approver:
- Operations/compliance approver:
- Launch decision timestamp:

Results:

- rehearsal pass rate:
- settlement success rate:
- dispute rate:
- day-1 status: `pass|fail`
- day-7 status: `pass|fail`

