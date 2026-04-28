# P0 Launch Day Command Center Playbook V1 (Private)

Status: Launch-day operations playbook  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/P0_SPRINT_1_ACCEPTANCE_TEST_MATRIX_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- `docs/P0_RACI_AND_DECISION_AUTHORITY_V1.md`
- `docs/P0_RELEASE_GATING_AND_CHANGE_FREEZE_V1.md`

## 1. Purpose

Define a command-center operating model for launch day to ensure:

1. real-time visibility of call/settlement health
2. fast, deterministic incident handling
3. single-command decision authority
4. strict financial correctness protection

## 2. Command center roles and shifts

Mandatory launch-day roles:

- Incident Commander (IC)
- Ops Commander (OC)
- Settlement Lead
- Risk Lead
- Routing Lead
- Scribe / Timeline Recorder
- Provider Liaison

Shift coverage:

- T-2h to T+6h: all roles online
- T+6h to T+24h: minimum IC + Ops + Settlement + Risk on-call

## 3. Pre-launch readiness checklist (T-120 to T-30 min)

- [ ] Release gate status = PASS
- [ ] Freeze policy active (non-essential changes blocked)
- [ ] Dashboards confirmed live:
  - paid calls
  - settlement success
  - dispute inflow
  - duplicate settlement detector
  - reconciliation mismatch count
- [ ] Alert channels tested (pager + chat)
- [ ] Provider contact bridge open
- [ ] Rollback controls dry-run completed
- [ ] Decision authority confirmed in writing

## 4. Launch timeline (minute-by-minute)

### T-30 to T-10

- [ ] Final readiness call
- [ ] Confirm no unresolved Sev-1/Sev-2
- [ ] Snapshot baseline metrics
- [ ] Confirm launch window and decision checkpoint times

### T-10 to T+0

- [ ] Enable launch banner and incident channel
- [ ] OC opens structured event log
- [ ] IC announces go/no-go checkpoint at T+15

### T+0 to T+15

- [ ] Start controlled traffic ramp (10% -> 30%)
- [ ] Watch settlement success and latency minute-by-minute
- [ ] Block expansion if anomalies exceed threshold

### T+15 checkpoint

Go criteria:

- settlement success >= 98% (rolling window)
- duplicate settlement count = 0
- no active Sev-1

Actions:

- if pass: ramp 30% -> 60%
- if fail: hold traffic and invoke incident runbook

### T+15 to T+45

- [ ] Continue ramp under guardrails
- [ ] Validate evidence bundle generation rate
- [ ] Reconcile first batch (`callId` vs `settlementId`)

### T+45 checkpoint

Go criteria:

- settlement success >= 97%
- reconciliation mismatch = 0 (or owned exceptions)
- dispute rate within baseline

Actions:

- if pass: move to full planned launch load
- if fail: freeze ramp and run corrective path

### T+45 to T+120

- [ ] Enhanced monitoring mode
- [ ] 30-minute internal updates
- [ ] Provider status sync every 20 minutes

## 5. Launch-day metric guardrails

Hard guards:

1. settlement success < 95% for 2 consecutive windows -> freeze expansion
2. any confirmed duplicate settlement -> Sev-1 + settlement commit pause
3. dispute rate > 8% sustained -> risk controls tightened + triage expansion
4. reconciliation mismatch > 0 without owner -> hold ramp

Soft guards:

- latency p95 degradation > 50% from baseline
- timeout rate > 2x baseline
- provider error-rate spike > 2x baseline

## 6. Decision protocol

Decision levels:

- Level 1 (Ops): keep/hold ramp
- Level 2 (IC + Leads): freeze and corrective actions
- Level 3 (Exec authority): hard rollback and relaunch window reset

Every decision must include:

- timestamp (UTC)
- decision type
- trigger metric(s)
- accountable owner
- next checkpoint time

## 7. Incident split routing

Use incident runbook for exact flow:

- Settlement failure spike -> Scenario A
- Duplicate settlement -> Scenario B
- Dispute surge -> Scenario C
- Provider outage -> Scenario D

Routing rule:

- financial correctness uncertainty always routes to highest priority (Sev-1 path)

## 8. Communication cadence

Internal updates:

- every 15 minutes during first hour
- every 30 minutes from hour 2 to hour 6
- hourly until end of day

Minimum update payload:

- current traffic level
- key metrics vs guardrails
- active incidents
- decision and next checkpoint

## 9. Rollback triggers and sequence

Immediate rollback triggers:

1. duplicate settlement confirmed
2. unrecoverable settlement failure beyond 30 minutes
3. unresolved Sev-1 with active financial risk

Rollback sequence:

1. stop new settlement commits
2. preserve evidence and logs
3. run reconciliation and impact list
4. communicate status and estimated recovery path
5. resume only after approvals from IC + Settlement Lead + Risk Lead

## 10. End-of-day closure checklist

- [ ] Launch-day final metric snapshot archived
- [ ] Incident timeline exported
- [ ] All open risks assigned owner + ETA
- [ ] Day-1 follow-up plan published
- [ ] Weekly review input package prepared

## 11. Launch-day report template

```text
Launch Date:
Window:
IC:
Ops Commander:

Traffic Ramp:
- planned:
- actual:

Metrics:
- paid_calls:
- settlement_success_rate:
- dispute_rate:
- duplicate_settlement_count:
- reconciliation_mismatch_count:

Incidents:
1) id / severity / status
2) ...

Decisions:
1) time / decision / owner
2) ...

Final status:
- launch verdict: success | constrained-success | rollback
- day+1 priorities:
```

