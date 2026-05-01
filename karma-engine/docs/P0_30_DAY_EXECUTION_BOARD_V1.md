# P0 30-Day Execution Board V1 (Private)

Status: Execution board  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`
- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_PROVIDER_ONBOARDING_CHECKLIST_V1.md`
- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`

## 1. Objective for next 30 days

Move from internal readiness to real paid usage with strict survival gates:

1. >= 1 active provider
2. >= 10 real paying users
3. non-zero real on-chain settled amount
4. repeat usage ratio >= 20% after onboarding wave

If gates fail, freeze expansion and enter correction loop.

## 2. Governance model

Decision cadence:

- Daily: ops decision (`continue|correct|freeze`)
- Weekly: steering decision (`expand|hold|freeze`)

Required reviewers for weekly decision:

- Risk lead
- Settlement lead
- Ops lead

No single-owner expansion decision allowed.

## 3. 30-day timeline (week-by-week)

## Week 1 (Days 1-7): Foundation and deterministic flow

Primary objective:

- make call -> settlement -> evidence deterministic and observable

Must-deliver:

- [ ] P0 API skeletons stable (`providers/products/authorizations/calls/settlements`)
- [ ] Data contracts wired for `paid_call`, `settlement`, `evidence_bundle`
- [ ] Idempotency keys active on call and settlement paths
- [ ] Reconciliation job online (call ledger vs settlement ledger)
- [ ] Daily ops report generated every day

Week-1 hard gate:

- 20/20 controlled end-to-end runs successful
- settlement success >= 95% in rehearsal sample

If gate fails:

- week-2 onboarding blocked

## Week 2 (Days 8-14): First provider onboarding and launch rehearsal

Primary objective:

- onboard first provider and validate production-like launch behavior

Must-deliver:

- [ ] Provider onboarding checklist fully completed
- [ ] Pricing, token, wallet, chain setup validated
- [ ] Risk policy baseline activated (`allow/review/deny` paths tested)
- [ ] Incident runbook tabletop drill completed
- [ ] Launch-day owner roster confirmed

Week-2 hard gate:

- provider onboarding status = pass
- rehearsal includes success/failure/timeout mix and passes all assertions

If gate fails:

- no paid-user onboarding in week 3

## Week 3 (Days 15-21): Real-user pilot and cash-flow validation

Primary objective:

- prove real paid usage and stable settlement under real interactions

Must-deliver:

- [ ] First 10 users onboarded
- [ ] Real paid call volume > 0 every day
- [ ] Dispute triage process active
- [ ] Daily stop-loss evaluation recorded

Week-3 hard gate:

- active provider >= 1
- unique paying users >= 10
- non-zero settled amount

If gate fails:

- freeze provider expansion, run root-cause plan

## Week 4 (Days 22-30): Stabilize repeat behavior and decision point

Primary objective:

- confirm repeat usage and decide expand/hold/freeze

Must-deliver:

- [ ] D1 and D7 repeat behavior measured
- [ ] 7-day metric roll-up completed
- [ ] Incident rate and dispute rate trend reviewed
- [ ] final 30-day decision memo drafted

Week-4 hard gate:

- repeat usage ratio >= 20%
- settlement success sustained >= 95%
- dispute rate sustained <= 8%

If gate fails:

- decision forced to `freeze` with correction backlog

## 4. Daily execution checklist (operator card)

Every day, complete:

1. Publish daily ops report (`P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`)
2. Verify reconciled fund-flow numbers
3. Evaluate stop-loss triggers explicitly
4. Assign top 3 actions with owner and ETA
5. Record daily decision (`continue|correct|freeze`)

Mandatory daily artifacts:

- report id
- dashboard snapshot
- reconciliation result
- stop-loss decision log

## 5. Metric board and thresholds

Track daily:

- paid calls
- confirmed settlements
- settlement success rate
- dispute rate
- repeat ratio (D1, D7)
- net settled amount
- duplicate settlement count
- reconciliation mismatch count

Thresholds:

- settlement success: target >= 95%
- dispute rate: target <= 8%
- repeat ratio after onboarding wave: target >= 20%
- duplicate settlement count: target = 0
- reconciliation mismatch count: target = 0

## 6. Stop-loss gates (expansion freeze triggers)

Trigger freeze when any condition is met:

1. settlement success < 95% for 2 consecutive days
2. dispute rate > 8% for 3 consecutive days
3. repeat ratio < 20% after onboarding wave
4. any confirmed duplicate settlement incident

Freeze actions:

1. Stop scope expansion immediately
2. Open incident/correction war-room
3. Prioritize reliability fixes only
4. Resume only after 2 healthy cycles

## 7. Weekly review template

For each week, fill:

- Week #:  
- Decision: `expand|hold|freeze`  
- Key metrics summary:  
- Top failures and root causes:  
- Corrective actions for next week:  
- Owners and deadlines:  

## 8. 30-day final decision matrix

At day 30 choose one:

### Expand

Conditions:

- all four survival objectives reached
- no active stop-loss trigger
- reliability trend stable

### Hold

Conditions:

- partial targets reached
- no severe financial correctness incident
- clear fix path with short-cycle milestones

### Freeze

Conditions:

- one or more core survival objectives missed
- repeated reliability/dispute failures
- unresolved financial correctness risk

## 9. Owner map

- Risk owner:
- Settlement owner:
- Routing owner:
- Analytics owner:
- Ops/on-call owner:
- Exec approver:

## 10. Execution board template (copy per day)

```text
Day:
Decision: continue | correct | freeze

Metrics:
- paid_calls:
- settlement_success_rate:
- dispute_rate:
- repeat_ratio_d1:
- repeat_ratio_d7:
- net_settled_amount:
- duplicate_settlement_count:
- reconciliation_mismatch_count:

Stop-loss:
- trigger_active: yes | no
- trigger_reason:

Top actions:
1) action / owner / ETA
2) action / owner / ETA
3) action / owner / ETA
```

