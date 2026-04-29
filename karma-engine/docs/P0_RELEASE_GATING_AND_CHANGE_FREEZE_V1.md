# P0 Release Gating and Change Freeze Policy V1 (Private)

Status: Governance policy  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- `docs/P0_RACI_AND_DECISION_AUTHORITY_V1.md`

## 1. Purpose

Define mandatory release gates and freeze rules for P0 to prevent unstable production changes.

Core principle:

- No release is allowed when financial correctness risk is unresolved.

## 2. Release levels

Release levels:

1. L0: Internal dev build (not user-facing)
2. L1: Pilot release (limited providers/users)
3. L2: Expansion release (broader pilot scope)

Only L1/L2 require full gate execution in this policy.

## 3. Mandatory pre-release gates (L1/L2)

All gates must pass:

1. Contract and interface compatibility gate
   - no breaking interface change without approved migration
2. Settlement reliability gate
   - recent controlled sample settlement success >= 95%
3. Duplicate-protection gate
   - duplicate settlement count = 0 in pre-release validation
4. Reconciliation gate
   - call ledger vs settlement ledger mismatch = 0 (or approved exception)
5. Evidence integrity gate
   - evidence bundle completeness >= 99%
6. Incident readiness gate
   - on-call roster confirmed
   - incident runbook drill completed in current cycle
7. Rollback readiness gate
   - rollback plan and owner assigned
   - last rollback drill succeeded

Any gate failure => release blocked.

## 4. Change freeze policy

Freeze types:

1. Soft freeze:
   - only bug fixes allowed
   - no new feature categories
2. Hard freeze:
   - no deploy to pilot/prod-like paths
   - emergency fixes only with Sev-1 approval chain

Freeze trigger conditions:

1. settlement success < 95% for 2 consecutive days
2. dispute rate > 8% for 3 consecutive days
3. any confirmed duplicate settlement incident
4. unresolved Sev-1 incident impacting financial correctness

When trigger occurs:

- immediately enter hard freeze until explicit release committee approval.

## 5. Release decision workflow

Required roles in release committee:

- Release owner
- Risk lead
- Settlement lead
- Ops lead

Decision outcomes:

1. Approve
2. Approve with constraints
3. Reject and freeze

Decision record must include:

- release id
- gate results
- known risks
- mitigation actions
- sign-off list with timestamp

## 6. Emergency release rules

Emergency release permitted only when:

- current production risk is higher than patch deployment risk
- rollback path is validated
- IC and at least one technical lead approve

Emergency release must be followed by:

1. 60-minute enhanced monitoring
2. post-incident review within 48 hours
3. gate policy update if gaps were discovered

## 7. Release artifacts checklist

Required artifacts:

- [ ] gate report summary
- [ ] compatibility check result
- [ ] reconciliation report
- [ ] evidence integrity sample report
- [ ] rollback plan
- [ ] release approval record
- [ ] monitoring plan for first 60 minutes

## 8. Freeze exit criteria

Freeze can be lifted only when all are true:

1. trigger root cause is identified
2. patch or compensating control validated
3. two consecutive healthy cycles observed
4. release committee signs off

## 9. Audit and compliance trail

Store every release/freeze decision with:

- immutable timestamp
- decision owner
- gate inputs
- supporting metrics snapshot
- final verdict

Retention baseline:

- release/freeze governance records: 3 years minimum

## 10. Quick operator card

Before every L1/L2 release:

1. run all gates
2. verify freeze status = inactive
3. collect approval signatures
4. release with monitoring window
5. publish release outcome summary

If any gate fails:

1. block release
2. enter correction plan
3. re-run full gate set before next attempt

