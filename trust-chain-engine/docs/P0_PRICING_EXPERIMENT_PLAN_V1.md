# P0 Pricing Experiment Plan V1 (Private)

Status: Execution plan  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`
- `docs/P0_30_DAY_EXECUTION_BOARD_V1.md`
- `docs/P0_REVENUE_RECONCILIATION_PLAYBOOK_V1.md`

## 1. Purpose

Design controlled pricing experiments for the P0 gateway to optimize:

1. paid conversion
2. repeat usage
3. net settled revenue
4. dispute-safe growth

Hard rule:

- No pricing experiment may violate financial correctness or stop-loss gates.

## 2. Experiment window and governance

Window:

- 30 days, split into 3 rounds (10 days each)

Governance:

- Weekly approval by Risk + Settlement + Ops leads
- Daily monitor via P0 ops report
- Immediate freeze when stop-loss is triggered

## 3. Experiment hypotheses

H1:

- Lower entry price increases first paid call conversion.

H2:

- Tiered pricing by volume increases repeat usage without reducing net margin.

H3:

- Limited first-call subsidy improves user activation if capped by budget guardrails.

## 4. Experiment groups

All groups are provider-scoped and user-segmented to avoid noisy overlap.

## G0 (control)

- Fixed baseline price per call (current default)

## G1 (fixed low entry)

- 20% lower fixed price than control
- no subsidy

## G2 (tiered volume)

- First 20 paid calls: baseline price
- Calls 21-100: 10% discount
- Calls >100: 15% discount

## G3 (first-call subsidy)

- First successful paid call subsidized up to configured cap
- Subsequent calls at baseline price

## 5. Eligibility and assignment

- Users assigned by deterministic hash of `userId` to one group
- Same user must remain in same group for whole round
- Exclude disputed or flagged-abuse users from subsidy group

## 6. Metrics (daily and round-end)

Primary:

- paid conversion rate
- repeat ratio (D1, D7)
- net settled revenue

Secondary:

- gross settled amount
- average revenue per paid call
- settlement success rate
- dispute rate
- refund/remediation cost

Safety:

- duplicate settlement count (must remain zero)
- reconciliation mismatch count (must remain zero or documented)

## 7. Stop-loss and kill-switch

Stop experiment immediately if any condition occurs:

1. settlement success < 95% for 2 consecutive days
2. dispute rate > 8% for 3 consecutive days
3. any confirmed duplicate settlement incident
4. subsidy burn rate exceeds budget cap by >10%

Kill-switch actions:

1. revert all treatment groups to control price
2. disable subsidy flag
3. record incident and start correction loop

## 8. Budget and margin guardrails

Define before launch:

- daily subsidy cap
- total round subsidy cap
- minimum net margin threshold

Guardrail rules:

- If daily cap reached -> auto-disable subsidy for rest of day
- If round cap reached -> end subsidy group early
- If net margin below threshold for 3 days -> freeze treatment groups

## 9. Round plan

## Round 1 (Days 1-10): Baseline + low-entry validation

- run G0 + G1
- objective: first paid conversion uplift

Pass criteria:

- G1 conversion uplift >= 10% vs G0
- no safety metric breach

## Round 2 (Days 11-20): Tiered pricing validation

- run G0 + G2
- objective: repeat ratio uplift with stable margin

Pass criteria:

- D7 repeat uplift >= 8% vs G0
- net margin not lower than control by more than 3%

## Round 3 (Days 21-30): Subsidy validation

- run G0 + G3
- objective: activation uplift under strict budget caps

Pass criteria:

- first paid activation uplift >= 15% vs G0
- subsidy ROI positive within measurement horizon

## 10. Data requirements

Required data per event:

- `userId`, `providerId`, `productId`
- `experimentGroup`, `roundId`
- `priceApplied`, `discountApplied`, `subsidyApplied`
- `callId`, `settlementId`, `status`
- `settledAmountGross`, `settledAmountNet`
- `disputeFlag`, `refundFlag`

All data must join with:

- paid_call ledger
- settlement ledger
- revenue reconciliation outputs

## 11. Analysis template

Per round, produce:

1. group-level metric table
2. uplift vs control
3. safety incidents and anomaly summary
4. margin impact summary
5. recommendation:
   - adopt
   - iterate
   - reject

## 12. Decision policy

Adopt pricing strategy only if:

- primary metrics improve over control
- no safety redline breach
- margin impact is acceptable
- ops complexity does not increase unresolved incidents

Otherwise:

- roll back to control and open new hypothesis cycle

## 13. Execution checklist

- [ ] experiment config approved
- [ ] assignment logic validated
- [ ] budget caps configured
- [ ] dashboards include group dimensions
- [ ] stop-loss automation tested
- [ ] rollback script tested
- [ ] daily reporting includes experiment section

## 14. Daily experiment log template

```text
Date:
Round:
Groups active:

Metrics:
- conversion_uplift_vs_control:
- repeat_d1_uplift_vs_control:
- repeat_d7_uplift_vs_control:
- net_margin_delta_vs_control:
- dispute_rate:
- settlement_success_rate:
- subsidy_burn_today:

Safety:
- stop_loss_triggered: yes|no
- trigger_reason:

Decision:
- continue | tune | stop

Top actions:
1) action / owner / ETA
2) action / owner / ETA
3) action / owner / ETA
```

