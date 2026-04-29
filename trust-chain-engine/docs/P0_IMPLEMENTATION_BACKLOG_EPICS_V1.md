# P0 Implementation Backlog Epics V1 (Private)

Status: Execution backlog baseline  
Scope: `trust-chain-engine` only (do not publish)

Related strategy set:

- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_PROVIDER_ONBOARDING_CHECKLIST_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- `docs/P0_RELEASE_GATING_AND_CHANGE_FREEZE_V1.md`

## 1) Backlog governance

Priority model:

- P0 = blocking for survival metrics
- P1 = critical for reliability and repeat usage
- P2 = efficiency/scale after P0-P1 stable

Story status:

- `todo | in_progress | blocked | done`

Definition of done (global):

1. acceptance criteria pass
2. evidence artifact attached
3. rollback plan defined
4. owner + reviewer signoff

## 2) Epic map (30-day focus)

### EPIC-01: Paid call -> settlement deterministic path

Priority: P0  
Owner: Settlement + Platform

Stories:

1. STORY-01-01 (P0): Provider registration endpoint
   - AC: provider can register and receive immutable `providerId`
2. STORY-01-02 (P0): Product pricing endpoint
   - AC: per-call pricing persisted with versioned snapshot
3. STORY-01-03 (P0): Authorization reference binding
   - AC: each call requires valid `authorizationRef`
4. STORY-01-04 (P0): Call execution pipeline
   - AC: call result always emits `paid_call` record
5. STORY-01-05 (P0): Settlement commit pipeline
   - AC: successful call maps to at most one successful settlement

Dependencies:

- data contracts finalized
- idempotency key middleware

### EPIC-02: Evidence integrity and auditability

Priority: P0  
Owner: Platform + Audit tooling

Stories:

1. STORY-02-01 (P0): Evidence bundle writer
   - AC: each call emits evidence record with trace continuity
2. STORY-02-02 (P0): Digest/signature verifier
   - AC: invalid digest/signature is blocked and alerted
3. STORY-02-03 (P1): Export package generator
   - AC: export includes manifest digest and verification metadata
4. STORY-02-04 (P1): Evidence retention automation
   - AC: hot/cold retention policy enforced by lifecycle jobs

Dependencies:

- P0 evidence contract doc

### EPIC-03: Risk controls and dispute handling

Priority: P0  
Owner: Risk + Dispute ops

Stories:

1. STORY-03-01 (P0): Risk decision engine baseline
   - AC: `allow/review/deny` paths testable end-to-end
2. STORY-03-02 (P0): Dispute intake workflow
   - AC: disputes can be opened with linked evidence refs
3. STORY-03-03 (P1): Dispute triage queue and SLA tracking
   - AC: SLA timers visible for each dispute stage
4. STORY-03-04 (P1): Arbitration decision ledger
   - AC: decisions are immutable and auditable

Dependencies:

- dispute policy baseline
- RACI authority baseline

### EPIC-04: Reliability, incident response, and freeze controls

Priority: P0  
Owner: SRE/Ops + Settlement

Stories:

1. STORY-04-01 (P0): Reconciliation job (call vs settlement)
   - AC: mismatch count produced daily with owner assignment
2. STORY-04-02 (P0): Stop-loss auto evaluator
   - AC: freeze trigger status computed daily
3. STORY-04-03 (P0): Incident command playbook integration
   - AC: runbook actions available as incident templates
4. STORY-04-04 (P1): Release gate pipeline
   - AC: deployment blocked when mandatory checks fail

Dependencies:

- incident runbook
- release gating policy

### EPIC-05: Metrics and operating rhythm

Priority: P1  
Owner: Analytics + Ops

Stories:

1. STORY-05-01 (P1): Daily ops report generator
   - AC: report JSON and markdown generated for each day
2. STORY-05-02 (P1): Weekly review board auto-pack
   - AC: weekly decision pack includes all required metrics
3. STORY-05-03 (P1): 30-day board progress tracker
   - AC: each week gate status auto-updated
4. STORY-05-04 (P2): Investor update draft assistant
   - AC: monthly narrative template prefilled from metrics

Dependencies:

- daily report template
- weekly ritual template

### EPIC-06: GTM execution (provider + first 10 users)

Priority: P0  
Owner: Growth + Ops

Stories:

1. STORY-06-01 (P0): First provider onboarding flow
   - AC: provider passes all must-pass checklist items
2. STORY-06-02 (P0): First 10 user acquisition pipeline
   - AC: 10 real users complete paid flow at least once
3. STORY-06-03 (P1): Pricing experiment orchestration
   - AC: A/B cohorts tracked with stop-loss conditions
4. STORY-06-04 (P1): Repeat usage conversion loop
   - AC: D7 repeat ratio tracked and actioned

Dependencies:

- onboarding checklist
- pricing experiment plan

### EPIC-07: Security and secrets baseline enforcement

Priority: P0  
Owner: Security + Platform

Stories:

1. STORY-07-01 (P0): Secret scanning and push guard
   - AC: blocking checks in CI for secret leaks
2. STORY-07-02 (P0): Key rotation workflow
   - AC: documented + testable rotation play for critical keys
3. STORY-07-03 (P1): Access policy enforcement
   - AC: least privilege verified for runtime identities
4. STORY-07-04 (P1): Compromise drill
   - AC: simulated key leak runbook executed and reviewed

Dependencies:

- secrets baseline policy

## 3) 30-day execution order

Phase order:

1. Week 1: EPIC-01, EPIC-02, EPIC-04 (foundation)
2. Week 2: EPIC-03, EPIC-06 (onboarding + control plane)
3. Week 3: EPIC-06 + EPIC-05 (real-user and metrics loop)
4. Week 4: EPIC-05 + EPIC-07 (stabilize and decision checkpoint)

## 4) Gate-linked acceptance

Day-7 gate requires:

- EPIC-01 P0 stories done
- EPIC-02 core stories done
- EPIC-04 reconciliation and stop-loss evaluator done

Day-14 gate requires:

- EPIC-06 provider onboarding story done
- EPIC-03 dispute intake story done

Day-21 gate requires:

- EPIC-06 first-10-users story done
- no active Sev-1 unresolved incident

Day-30 gate requires:

- survival metrics met or explicit freeze decision documented

## 5) Blocker escalation policy

If any P0 story remains blocked > 24h:

1. escalate to Incident Commander + Exec approver
2. freeze non-essential feature work
3. assign unblocking owner with explicit ETA

## 6) Backlog template (copy per story)

```text
Story ID:
Epic:
Priority:
Owner:
Reviewer:
Status:
Dependencies:

Acceptance Criteria:
- ...
- ...

Evidence:
- test/report link
- reconciliation or metrics snapshot

Rollback Plan:
- ...

Risk Notes:
- ...
```

