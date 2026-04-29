# P0 Daily Operations Report Template V1 (Private)

Status: Operational reporting template  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/GO_TO_MARKET_VERTICAL_STRATEGY_V1.md`
- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_PROVIDER_ONBOARDING_CHECKLIST_V1.md`

## 1. Purpose

Provide a daily operator report template for P0 with direct focus on:

1. real fund flow
2. settlement reliability
3. repeat usage behavior
4. dispute and risk pressure
5. stop-loss trigger status

This report is mandatory during P0 pilot and early scale.

## 2. Report metadata (required)

- Report date (UTC):
- Report owner:
- On-call owner:
- Environment (`pilot|production-like|production`):
- Coverage window (`start -> end`, UTC):
- Data snapshot timestamp:
- Trace/report id:

## 3. Executive summary (3 lines max)

- Business status:
- Reliability status:
- Decision for next 24h (`continue|correct|freeze`):

## 4. North-star and mandatory success counters

Fill daily values:

1. Active API providers (target >= 1):
   - value:
2. Unique paying users (target >= 10 in pilot window):
   - value:
3. Real on-chain settled amount (must be > 0):
   - value:
4. Repeat usage ratio (D1 and D7):
   - D1:
   - D7:

Daily verdict:

- [ ] all four counters healthy
- [ ] one or more counters below target (requires action plan)

## 5. Traffic and monetization panel

### 5.1 Calls

- Total calls:
- Paid calls:
- Success calls:
- Failed calls:
- Timeout calls:

### 5.2 Settlement

- Settlement attempts:
- Confirmed settlements:
- Failed settlements:
- Disputed settlements:
- Settlement success rate:
- Mean settlement latency (ms):

### 5.3 Revenue

- Gross settled amount:
- Net settled amount (after refunds/disputes):
- Average revenue per paid call:
- Top provider by settled amount:

## 6. Reliability and integrity panel

### 6.1 Core reliability

- Call success rate:
- Settlement success rate:
- Retry rate:
- Duplicate settlement count:
- Reconciliation mismatch count:

### 6.2 Evidence integrity

- Evidence bundles generated:
- Missing evidence bundles:
- Invalid digest/signature count:
- Trace continuity failures (`call -> settlement -> evidence`):

### 6.3 SLA and latency

- Provider uptime (24h):
- Provider p95 latency:
- Gateway p95 latency:

## 7. Risk and dispute panel

### 7.1 Risk decisions

- `allow` count:
- `review` count:
- `deny` count:
- Risk escalation events:

### 7.2 Disputes

- New disputes opened:
- Disputes resolved:
- Open disputes backlog:
- Mean dispute resolution time:
- Top dispute root cause category:

### 7.3 Fraud/anomaly signals

- Suspicious pattern alerts:
- Confirmed abuse incidents:
- False positive count:

## 8. Stop-loss gate check (must evaluate daily)

Evaluate each trigger:

1. Settlement success rate < 95% for two consecutive days
   - today status: `yes|no`
   - consecutive day count:
2. Dispute rate > 8% for three consecutive days
   - today status: `yes|no`
   - consecutive day count:
3. Repeat ratio < 20% after onboarding wave
   - today status: `yes|no`

Overall stop-loss status:

- [ ] no trigger active
- [ ] trigger active -> scope freeze required

If triggered, mandatory actions:

- Freeze scope expansion
- Assign incident owner
- Open corrective action ticket set
- Re-run controlled rehearsal before resuming expansion

## 9. Top incidents and actions

List top 3 incidents of the day:

1. Incident:
   - severity:
   - impact:
   - root cause (known/unknown):
   - mitigation applied:
   - owner:
2. Incident:
3. Incident:

## 10. Next-24h action plan

Priority-ordered actions:

1. Action:
   - owner:
   - deadline (UTC):
   - expected metric impact:
2. Action:
3. Action:

## 11. Weekly roll-up fields (fill on designated day)

- 7-day total paid calls:
- 7-day unique paying users:
- 7-day gross settled amount:
- 7-day repeat ratio:
- 7-day dispute rate:
- 7-day settlement success rate:
- Expansion decision (`expand|hold|freeze`):

## 12. Report output format (recommended JSON envelope)

Use this top-level envelope for machine aggregation:

```json
{
  "schemaVersion": "trustchain.p0.daily-ops-report.v1",
  "generatedAt": "2026-04-28T18:40:00Z",
  "source": "ops:daily-report",
  "traceId": "report-20260428T184000Z-ops",
  "reportDate": "2026-04-28",
  "decision": "continue",
  "stopLoss": {
    "active": false,
    "reasons": []
  }
}
```

## 13. Conformance checklist (before publishing daily report)

- [ ] all required metadata filled
- [ ] fund flow numbers reconciled with settlement ledger
- [ ] dispute metrics reconciled with dispute queue
- [ ] stop-loss gate explicitly evaluated
- [ ] decision for next 24h recorded
- [ ] action owners assigned

