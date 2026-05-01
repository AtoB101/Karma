# P0 Executive Metrics Dashboard Spec V1 (Private)

Status: Executive dashboard specification  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`
- `docs/P0_30_DAY_EXECUTION_BOARD_V1.md`
- `docs/P0_REVENUE_RECONCILIATION_PLAYBOOK_V1.md`
- `docs/P0_POST_LAUNCH_14_DAY_STABILIZATION_PLAN_V1.md`

## 1. Purpose

Define a CEO/ops-ready metrics dashboard specification for P0:

1. one-screen business health view
2. clear metric definitions and ownership
3. threshold-based warning system
4. decision support for `expand|hold|freeze`

This spec is the single source of truth for executive reporting metrics.

## 2. Dashboard principles

1. Actionable over decorative: each metric must map to a decision/action.
2. Traceable: every metric must map to an auditable source.
3. Freshness-aware: stale metrics must be visibly flagged.
4. Owner-bound: each metric has a directly accountable owner.

## 3. Executive top strip (must always be visible)

Show these 8 KPIs at top:

1. Active Providers
2. Unique Paying Users (24h / 7d)
3. Net Settled Amount (24h / 7d)
4. Settlement Success Rate (24h)
5. Dispute Rate (24h)
6. Repeat Ratio (D1 / D7)
7. Duplicate Settlement Count (24h)
8. Stop-loss Status (`normal|warning|freeze`)

## 4. Metric definitions and formulas

## 4.1 Growth and demand

### Active Providers

- Definition: providers with at least one successful paid call in window.
- Formula: `count(distinct providerId where paid_call.status=success)`
- Owner: Provider Ops Lead
- Update frequency: every 5 min
- Alert threshold:
  - warning: `< 1`
  - critical: `= 0`

### Unique Paying Users

- Definition: unique users with at least one confirmed settlement in window.
- Formula: `count(distinct userId where settlement.status=confirmed)`
- Owner: Growth Lead
- Update frequency: every 5 min
- Alert threshold:
  - warning: week-over-week drop > 20%
  - critical: daily value = 0

## 4.2 Revenue and monetization

### Gross Settled Amount

- Definition: sum of confirmed settlement amount before refunds/disputes.
- Owner: Finance Ops
- Update frequency: every 5 min

### Net Settled Amount

- Definition: gross settled - refunds - dispute compensation.
- Owner: Finance Ops
- Update frequency: every 5 min
- Alert threshold:
  - warning: net/gross ratio < 0.92
  - critical: net settled <= 0 for 24h

### Average Revenue per Paid Call (ARPC)

- Formula: `net_settled_amount / paid_calls_confirmed`
- Owner: Pricing Lead
- Update frequency: hourly
- Alert threshold:
  - warning: drop > 15% in 7d rolling

## 4.3 Reliability and correctness

### Settlement Success Rate

- Formula: `confirmed / attempts`
- Owner: Settlement Lead
- Update frequency: every 1 min
- Alert threshold:
  - warning: `< 97%`
  - critical: `< 95%`

### Duplicate Settlement Count

- Definition: count of confirmed duplicate settlements for same logical call.
- Owner: Settlement Lead
- Update frequency: every 1 min
- Alert threshold:
  - warning: `>= 1`
  - critical: `>= 1` (Sev-1 always)

### Reconciliation Mismatch Count

- Definition: unmatched records between call ledger and settlement ledger.
- Owner: Finance + Settlement joint
- Update frequency: every 15 min
- Alert threshold:
  - warning: `> 0`
  - critical: persistent `> 0` for 30 min

## 4.4 Risk and disputes

### Dispute Rate

- Formula: `new_disputes / confirmed_settlements`
- Owner: Dispute Lead
- Update frequency: every 5 min
- Alert threshold:
  - warning: `> 5%`
  - critical: `> 8%`

### Risk Decision Mix

- Display:
  - allow %
  - review %
  - deny %
- Owner: Risk Lead
- Update frequency: every 5 min
- Alert threshold:
  - warning: sudden review+deny jump > 2x baseline

## 4.5 Retention and repeat behavior

### Repeat Ratio D1 / D7

- Definition: percent of users who return for another paid call in D1/D7.
- Owner: Growth Lead
- Update frequency: daily
- Alert threshold:
  - warning: D1 < 25%
  - critical: D7 < 20%

## 5. Dashboard layout specification

Section A (Top strip): 8 executive KPIs with sparkline + status color.

Section B (Business panel):

- paid calls trend
- users/providers trend
- revenue trend

Section C (Reliability panel):

- settlement success
- latency
- duplicate count
- reconciliation mismatch

Section D (Risk/Dispute panel):

- dispute inflow/backlog
- risk decision mix
- top root causes

Section E (Decision panel):

- stop-loss gate status
- recommended decision: `expand|hold|freeze`
- top 3 required actions and owners

## 6. Data freshness and SLA

Freshness SLA:

- critical reliability metrics: <= 2 minutes
- revenue/growth metrics: <= 10 minutes
- retention metrics: daily batch by 02:00 UTC

Staleness policy:

- any metric stale beyond SLA must display `STALE` badge
- stale critical metric forces decision panel to `hold` until refreshed

## 7. Alerting and escalation mapping

Alert levels:

- Green: all metrics within target
- Amber: one or more warning thresholds breached
- Red: any critical threshold breached

Escalation:

- Amber -> module owner + ops channel
- Red -> Sev-1/2 process from incident runbook

Auto-actions (Red):

1. freeze expansion recommendation
2. open incident ticket with metric snapshot
3. assign incident commander

## 8. Decision engine mapping

Daily decision rules:

- `expand`: all core KPIs healthy for 7 consecutive days
- `hold`: warnings present, no critical breach
- `freeze`: any critical breach or stop-loss trigger

Core KPI set for expansion:

1. settlement success >= 95%
2. dispute rate <= 8%
3. duplicate settlement count = 0
4. repeat D7 >= 20%
5. net settled amount > 0

## 9. Ownership matrix (required)

Define per-metric owner and backup owner:

- Growth metrics owner:
- Revenue metrics owner:
- Settlement reliability owner:
- Risk/dispute owner:
- Dashboard platform owner:
- Executive approver:

## 10. Delivery specification

Output contracts (recommended):

- `karma.p0.exec-dashboard.snapshot.v1` (5-minute snapshots)
- `karma.p0.exec-dashboard.daily.v1` (daily summary)

Required envelope fields:

- `schemaVersion`
- `generatedAt`
- `source`
- `traceId`

## 11. Conformance checklist

- [ ] Every KPI has a clear formula and owner
- [ ] Every KPI has warning/critical threshold
- [ ] Data freshness SLA implemented
- [ ] Stop-loss mapping implemented
- [ ] Decision panel produces `expand|hold|freeze`
- [ ] Alert routing tested end-to-end
- [ ] Weekly metric review ritual linked

## 12. Next implementation steps

1. create dashboard schema under `internal-admin/contracts/dashboard/`
2. implement metric computation jobs for each KPI
3. wire alert thresholds to incident routing
4. add daily snapshot export for investor/update narratives
5. validate against 14-day stabilization plan

