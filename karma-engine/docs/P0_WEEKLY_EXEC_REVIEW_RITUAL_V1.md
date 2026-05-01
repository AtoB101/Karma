# P0 Weekly Execution Review Ritual V1 (Private)

Status: Operating ritual template  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_30_DAY_EXECUTION_BOARD_V1.md`
- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`
- `docs/P0_REVENUE_RECONCILIATION_PLAYBOOK_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`

## 1. Purpose

Establish a strict weekly operating ritual that converts data into decisions.

Primary goals:

1. prevent metric drift and blind optimism
2. force explicit `expand|hold|freeze` decisions weekly
3. assign owners and deadlines for corrective actions
4. ensure survival-first discipline over feature expansion

## 2. Cadence and attendance

Cadence:

- Weekly, fixed slot (recommended: Monday UTC morning)
- Duration: 60 minutes hard cap

Required attendees:

- Risk owner
- Settlement owner
- Routing owner
- Analytics owner
- Ops/on-call owner
- Decision approver (exec or delegate)

Rule:

- No decision is valid without at least one engineering owner + ops owner present.

## 3. Required inputs (pre-read)

Prepared 12 hours before meeting:

1. Last 7 daily ops reports
2. 7-day metric rollup
3. Reconciliation summary (call vs settlement vs revenue)
4. Incident log and postmortem status
5. Dispute queue health snapshot
6. Active stop-loss trigger status

Data quality check before meeting starts:

- [ ] all numbers sourced from canonical pipeline
- [ ] no unresolved reconciliation mismatch in summary
- [ ] incident severity labels normalized

## 4. 60-minute agenda (strict)

### 0-10 min: KPI truth table

Read current values only, no interpretation yet:

- paid calls (7d)
- unique paying users (7d)
- net settled amount (7d)
- settlement success rate (7d)
- dispute rate (7d)
- repeat ratio D1/D7
- duplicate settlement count
- reconciliation mismatch count

### 10-25 min: Reliability and financial integrity

- review incidents from week
- confirm all Sev-1/Sev-2 have owner and ETA
- confirm duplicate/ledger mismatch = 0 or documented recovery

### 25-40 min: Growth and monetization quality

- acquisition funnel quality (new -> paid -> repeat)
- provider reliability and contribution concentration
- pricing experiment outcomes (if active)

### 40-50 min: Stop-loss and expansion gate

Explicitly evaluate freeze conditions:

1. settlement success < 95% for two consecutive days
2. dispute rate > 8% for three consecutive days
3. repeat ratio < 20% after onboarding wave
4. any confirmed duplicate settlement incident

### 50-60 min: Decision and commitments

Force one decision:

- `expand`
- `hold`
- `freeze`

Then assign top 3 actions with owner + deadline.

## 5. Decision rubric

## 5.1 Expand

Allowed only when all are true:

- no active stop-loss trigger
- settlement success >= 95% (7d)
- dispute rate <= 8% (7d)
- repeat ratio >= 20%
- reconciliation mismatch count = 0

## 5.2 Hold

Use when:

- metrics mixed but no severe financial-integrity risk
- remediation path is clear and short-cycle

## 5.3 Freeze

Mandatory when:

- any stop-loss trigger active
- financial correctness uncertain
- unresolved Sev-1 with user-fund impact

During freeze:

- no scope expansion
- reliability and correctness fixes only
- next review must include explicit unfreeze checklist

## 6. Weekly output artifact (required)

File naming recommendation:

- `internal-admin/reviews/weekly-review-YYYY-MM-DD.md`

Required sections:

1. KPI snapshot table
2. Incidents and unresolved risk list
3. Decision (`expand|hold|freeze`)
4. Top 3 commitments (owner, deadline, expected impact)
5. Exceptions and executive notes

## 7. Responsibility tracking format

Each commitment must include:

- `actionId`
- `owner`
- `deadlineUtc`
- `metricTarget`
- `status` (`open|done|blocked`)
- `blocker`

Roll-over rule:

- Any `open` item older than 14 days must be escalated.

## 8. Meeting anti-patterns (must avoid)

Do not allow:

1. narrative without numbers
2. unresolved ownership ("team will handle")
3. optimistic continuation under active stop-loss
4. adding new experiments before closing critical incidents

## 9. Weekly review template

```text
Week Ending (UTC):
Chair:
Attendees:

KPI Snapshot (7d):
- paid_calls:
- unique_paying_users:
- net_settled_amount:
- settlement_success_rate:
- dispute_rate:
- repeat_ratio_d1:
- repeat_ratio_d7:
- duplicate_settlement_count:
- reconciliation_mismatch_count:

Incident Summary:
- sev1_count:
- sev2_count:
- unresolved_critical:

Stop-loss Check:
- trigger_1_active:
- trigger_2_active:
- trigger_3_active:
- trigger_4_active:

Decision: expand | hold | freeze
Rationale:

Top 3 Commitments:
1) action / owner / deadline / target
2) action / owner / deadline / target
3) action / owner / deadline / target

Escalations:
- 
```

## 10. Effectiveness KPIs for the ritual itself

Track monthly:

- % weekly reviews completed on schedule
- % commitments delivered on time
- mean age of unresolved critical actions
- count of wrong-way decisions (expand followed by freeze within 7 days)

Target baselines:

- on-schedule reviews >= 95%
- commitment on-time >= 80%
- wrong-way decisions <= 1 per quarter

