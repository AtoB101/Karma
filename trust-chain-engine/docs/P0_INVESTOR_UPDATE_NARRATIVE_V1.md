# P0 Investor Update Narrative V1 (Private)

Status: Investor communication template  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`
- `docs/P0_30_DAY_EXECUTION_BOARD_V1.md`
- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`
- `docs/P0_REVENUE_RECONCILIATION_PLAYBOOK_V1.md`

## 1. Purpose

Provide a monthly investor update narrative that prioritizes:

1. real paid transactions
2. reliability of settlement
3. repeat usage and retention
4. risk-control maturity
5. operational discipline

Principle:

- no "future-only" storytelling
- every claim must link to measurable evidence

## 2. One-page narrative structure (recommended order)

1. Executive headline (3 bullets)
2. Core business KPIs (this month vs last month)
3. Product progress tied to revenue outcomes
4. Reliability and risk controls status
5. Key incidents and what changed after them
6. Next 30-day plan with explicit go/no-go gates
7. Support request (what investors can help with)

## 3. Executive headline template

Use this format:

- Revenue reality: `<real settled amount this month>` (`+/- % MoM`)
- Usage reality: `<paid calls>` from `<unique paying users>`
- Reliability reality: settlement success `<x%>`, dispute rate `<y%>`

Example:

- Real settled amount: `$4,820` (`+38% MoM`)
- Paid calls: `12,430` from `37` unique paying users
- Settlement success: `98.4%`, dispute rate: `2.1%`

## 4. KPI block (must include)

## 4.1 Commercial KPIs

- Gross settled amount
- Net settled amount
- Paid call volume
- Unique paying users
- Active providers
- Average revenue per paid call
- Repeat ratio (D1, D7)

## 4.2 Reliability KPIs

- Settlement success rate
- Mean settlement latency
- Duplicate settlement count (target: 0)
- Reconciliation mismatch count (target: 0)
- Evidence completeness rate

## 4.3 Risk and trust KPIs

- Dispute rate
- Average dispute resolution time
- Risk decision distribution (`allow/review/deny`)
- Fraud/anomaly confirmed incidents

Presentation rule:

- always show MoM delta and target line

## 5. Product progress section

Only include shipped items that changed KPI behavior.

Template per item:

- What shipped:
- Why it mattered:
- KPI impact observed:
- Confidence level (`high|medium|low`):

Example:

- What shipped: stricter idempotency guard on settlement commit
- Why it mattered: prevented duplicate charge paths on retry storms
- KPI impact observed: duplicate settlement count reduced from `3` to `0`
- Confidence level: high

## 6. Risk and incident transparency

For each major incident, include:

- Incident type
- User/financial impact
- Root cause category (`system|process|external|human`)
- Containment speed
- Permanent fix status

Mandatory statement:

- "Financial correctness currently `stable|degraded|at-risk`"

## 7. What not to include (investor update guardrails)

Do not include:

- unverifiable vanity metrics
- roadmap claims without execution owner/date
- private algorithm internals
- security-sensitive implementation details

Do include:

- measurable outcomes
- controlled risks
- explicit constraints and decisions

## 8. 30-day forward plan section

Use three buckets:

1. Must achieve (gated)
2. Should achieve
3. Won't do

For each must-achieve item:

- owner
- deadline
- gate metric
- risk if missed

Example:

- Must: onboard 1 additional high-quality provider
- Owner: Provider Ops Lead
- Deadline: 2026-05-31
- Gate metric: provider passes onboarding checklist with zero Sev-1 issues
- Risk if missed: user growth bottleneck

## 9. Investor asks (high-leverage only)

Ask categories:

- distribution introductions (target provider/user profiles)
- enterprise pilot channel access
- hiring referrals for specific critical roles
- compliance advisory in target geography

Template:

- Ask:
- Why now:
- What outcome in next 30 days:

## 10. Monthly template (copy-paste)

```text
Month:
Prepared by:
Date (UTC):

Executive headline:
1)
2)
3)

Core KPIs (MoM):
- gross_settled_amount:
- net_settled_amount:
- paid_calls:
- unique_paying_users:
- active_providers:
- arpc:
- d1_repeat_ratio:
- d7_repeat_ratio:
- settlement_success_rate:
- dispute_rate:
- duplicate_settlement_count:
- reconciliation_mismatch_count:

Product progress:
1) shipped / reason / KPI impact / confidence
2)
3)

Risk and incidents:
1) incident / impact / root cause / containment / permanent fix
2)

Financial correctness status:
- stable | degraded | at-risk

Next 30-day plan:
- must:
- should:
- won't:

Investor asks:
1)
2)
3)
```

## 11. Quality checklist before sending

- [ ] every KPI number has source trace/reference
- [ ] no private-key/secret/security-sensitive data exposed
- [ ] no unverifiable statements
- [ ] all forward plans have owner + date + gate metric
- [ ] risk status and incident truth fully disclosed

## 12. Distribution policy

Internal classification:

- default: existing investors only
- board-level version: includes deeper risk details
- external summary: only with explicit approval

Approval requirement before sending:

- CEO/founder
- Finance owner
- Risk/ops owner

