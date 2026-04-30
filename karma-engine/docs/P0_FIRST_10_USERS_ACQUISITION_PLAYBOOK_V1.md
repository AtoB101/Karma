# P0 First 10 Paying Users Acquisition Playbook V1 (Private)

Status: Execution playbook  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`
- `docs/P0_30_DAY_EXECUTION_BOARD_V1.md`
- `docs/P0_PRICING_EXPERIMENT_PLAN_V1.md`
- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`

## 1. Objective

Acquire the first 10 real paying users within the P0 window, with validated repeat usage.

Success criteria:

1. 10 unique paying users completed at least one paid call
2. non-zero settled amount from real usage
3. D7 repeat ratio >= 20%
4. no active stop-loss trigger during acquisition sprint

## 2. ICP (ideal customer profile) for first 10

Prioritize users who already have frequent API-call behavior:

1. solo AI builder using tool-calling bots
2. small quant/data team querying market APIs
3. automation developer running scheduled data fetch jobs

Disqualify for P0:

- users requesting enterprise procurement cycle
- users needing deep custom integrations before first paid call

## 3. Channel mix (P0 low-cost)

Use lightweight, direct channels:

1. Existing founder/operator network outreach
2. Private dev communities and technical groups
3. Targeted DM to API-heavy builders
4. Warm introductions from first provider

Target split for first 10:

- 4 from direct network
- 3 from community outreach
- 2 from provider referrals
- 1 from inbound/organic

## 4. Offer design (what user gets)

Core offer:

- one-click demo path: "query BTC price -> auto settlement proof"
- clear per-call price (simple, transparent)
- visible proof and settlement record after each call

P0 launch incentives (bounded):

- first-call credit cap (strictly limited budget)
- onboarding support in first 24h
- priority support for first 10 users

Do not offer:

- open-ended free usage
- custom pricing before baseline usage data

## 5. Outreach scripts

## 5.1 First-touch message template (short)

```text
We built a paid API gateway for AI agents:
one API call -> automatic on-chain settlement -> verifiable proof.

Looking for 10 design partners who already run API-heavy agent workflows.
If you're open, we can onboard you in <30 minutes and you can run your first paid call today.
```

## 5.2 Follow-up (if interested)

```text
Great. We'll run a simple flow:
1) set your call policy
2) run one real API call
3) confirm settlement + proof output

We'll stay with you through first run. If it works, we capture feedback and optimize your setup.
```

## 5.3 Objection handling (common)

- "Too early?"
  - Response: "P0 is intentionally narrow; we only test one paid call path and settlement proof."
- "Worried about payment correctness?"
  - Response: "Every call has evidence and reconciliation; duplicate protections are active."
- "Need lower risk first?"
  - Response: "We can start with minimum spend cap and single-endpoint usage."

## 6. Conversion funnel (must track)

Define stages:

1. `lead_created`
2. `lead_qualified`
3. `demo_scheduled`
4. `demo_completed`
5. `wallet_authorized`
6. `first_paid_call_completed`
7. `repeat_paid_call_completed`

Daily funnel metrics:

- leads added
- stage conversion rates
- time-to-first-paid-call
- drop-off reasons by stage

## 7. 7-day onboarding and follow-up script (per user)

Day 0:

- complete first paid call in guided session
- confirm settlement and evidence visibility

Day 1:

- check first experience issues
- ensure second use case is defined

Day 3:

- review usage friction (latency, failures, pricing confusion)
- apply config improvements

Day 5:

- request repeat run with new query window
- collect value signal ("what did this replace?")

Day 7:

- confirm repeat usage status
- capture testimonial / case note (private)
- classify user: `retain|at-risk|drop`

## 8. Operator task checklist (daily)

1. Add new leads and qualify ICP fit
2. Schedule and execute demos within 24h
3. Track funnel stage transitions
4. Ensure each new user gets first-call support
5. Log friction points and assign fixes
6. Publish acquisition block in daily ops report

## 9. Risk controls during acquisition

Guardrails:

1. keep per-user spend cap active
2. enforce idempotency and reconciliation checks
3. block expansion if stop-loss triggers activate
4. avoid custom one-off flows that bypass core pipeline

Escalate to incident runbook when:

- duplicate charge suspicion appears
- settlement failure spike crosses threshold
- dispute rate breaches daily control range

## 10. Weekly review and decision gates

Review weekly:

- leads -> paid users conversion
- paid users -> repeat users conversion
- CAC proxy (time cost) vs settled revenue
- top 3 blockers and owner

Week decision:

- `continue`: conversion and reliability healthy
- `correct`: conversion weak but fixable in 7-day cycle
- `freeze`: stop-loss active or financial correctness at risk

## 11. First-10 user roster template

Track this table internally:

| userId | source | ICP fit | firstPaidCallAt | repeatByD7 | settledAmount | status | owner |
|---|---|---|---|---|---:|---|---|
| user_001 | network | high | 2026-04-XX | yes/no | 0.00 | active/at-risk/drop | <name> |

## 12. Exit criteria for acquisition sprint

Pass:

- >= 10 real paying users
- D7 repeat ratio >= 20%
- no unresolved Sev-1 financial correctness issue
- documented lessons for next 20 users

Fail:

- < 10 paying users by end of window
- repeat ratio < 20%
- major unresolved reliability risks

If fail:

1. freeze growth push
2. run root-cause correction sprint
3. restart acquisition only after reliability and funnel fixes are verified
