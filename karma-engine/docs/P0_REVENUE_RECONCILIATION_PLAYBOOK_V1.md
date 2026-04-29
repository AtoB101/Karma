# P0 Revenue Reconciliation Playbook V1 (Private)

Status: Operational finance playbook  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`

## 1. Purpose

Define daily reconciliation process across three ledgers:

1. Call ledger (`paid_call`)
2. Settlement ledger (`settlement`)
3. Revenue ledger (finance reporting aggregates)

Primary objective:

- Ensure financial correctness and traceability for every paid call.

## 2. Reconciliation principle

For any reporting window, every successful paid call must map to exactly one
valid settlement outcome and one corresponding revenue record.

Expected mappings:

- `paid_call.status = success` -> settlement must be `confirmed` or valid terminal business state
- settlement `confirmed` -> revenue recognized according to accounting rule
- disputes/refunds -> revenue adjustment entries required

## 3. Roles and RACI

Roles:

- Finance Ops (FO)
- Settlement Engineer (SE)
- Risk/Dispute Ops (RO)
- Incident Commander (IC, only when threshold breached)

RACI summary:

- Daily reconciliation run: FO (R), SE (A), RO (C), IC (I)
- Difference triage: FO (R), SE (R), RO (C), IC (I)
- Correction execution: SE (R), FO (A), RO (C)
- Escalation and freeze decision: IC (A), FO/SE/RO (C)

## 4. Daily process (T+0 day close)

### Step 1: Extract ledgers

Window:

- UTC `00:00:00` to `23:59:59`

Exports required:

1. `paid_call` export
2. `settlement` export
3. revenue summary export
4. dispute/refund adjustments export

### Step 2: Normalize and join

Join keys priority:

1. `callId`
2. `settlementId`
3. `traceId`

Normalization rules:

- UTC timestamps only
- canonical amount unit (smallest token unit)
- canonical status mapping table

### Step 3: Run invariants

Mandatory invariants:

1. no missing successful-call -> settlement mapping
2. no duplicate confirmed settlement for same `callId`
3. revenue record count equals confirmed settlement count (+/- adjustments)
4. sum(amount confirmed) - sum(refund/adjustment) == net revenue

### Step 4: Produce reconciliation report

Output envelope (recommended):

```json
{
  "schemaVersion": "karma.p0.reconciliation.v1",
  "generatedAt": "2026-04-28T19:00:00Z",
  "source": "finance:reconciliation",
  "traceId": "recon-20260428",
  "window": "2026-04-28",
  "status": "pass",
  "diffCount": 0
}
```

## 5. Difference taxonomy

Classify every diff into one category:

1. `MISSING_SETTLEMENT`
   - successful call without settlement
2. `DUPLICATE_SETTLEMENT`
   - more than one confirmed settlement for same logical charge
3. `MISSING_REVENUE_ENTRY`
   - settlement confirmed but no finance record
4. `AMOUNT_MISMATCH`
   - amount differs between settlement and revenue
5. `STATUS_MISMATCH`
   - state transitions not aligned
6. `LATE_ARRIVAL`
   - event arrived after window close (requires carry-over)
7. `DISPUTE_ADJUSTMENT_GAP`
   - dispute/refund not reflected in revenue adjustment

Severity mapping:

- Critical: duplicate settlement, major amount mismatch
- High: missing settlement, missing revenue entry
- Medium: late arrival, status mismatch

## 6. Correction actions by category

### 6.1 Missing settlement

Actions:

1. verify call success and idempotency key integrity
2. requeue settlement commit in controlled mode
3. mark record with correction ticket id

SLA:

- fix within 4 hours for same-day records

### 6.2 Duplicate settlement

Actions:

1. immediate Sev-1 escalation
2. pause affected settlement slice
3. compute remediation/refund set
4. run duplicate-prevention replay tests before resume

SLA:

- containment within 15 minutes

### 6.3 Missing revenue entry

Actions:

1. verify settlement confirmation state
2. replay accounting writer for missing set
3. annotate correction journal

SLA:

- fix within same reconciliation cycle

### 6.4 Amount mismatch

Actions:

1. verify token decimals and amount normalization
2. compare raw settlement payload vs finance transform logic
3. issue correction journal and root-cause ticket

SLA:

- critical mismatches fixed within 2 hours

## 7. Escalation thresholds

Trigger incident escalation when any condition holds:

1. `DUPLICATE_SETTLEMENT` count > 0
2. total unmatched successful calls > 0.5% of paid calls
3. net amount mismatch > 0.3% of gross settled amount
4. unresolved critical diffs older than 2 hours

Escalation action:

- invoke `P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- freeze expansion decisions for the day

## 8. Daily sign-off checklist

- [ ] all three ledgers extracted for exact UTC window
- [ ] invariant checks completed
- [ ] differences categorized and counted
- [ ] correction actions assigned with owners/ETA
- [ ] escalations triggered where required
- [ ] net revenue number approved by Finance Ops
- [ ] reconciliation report archived

Sign-off fields:

- Finance Ops approver:
- Settlement approver:
- Sign-off timestamp (UTC):

## 9. Weekly audit roll-up

Aggregate weekly:

- total gross settled amount
- total net recognized revenue
- total adjustment/refund amount
- diff rate by category
- mean time to reconcile (MTTR-recon)
- unresolved diff backlog

Weekly decision:

- `healthy | watch | corrective`

## 10. Control and compliance notes

Never store in reconciliation artifacts:

- private keys
- plaintext API secrets
- unredacted user sensitive data

Required controls:

- immutable report archive
- change log for correction journals
- dual approval for critical corrections

## 11. Implementation next steps

1. Add machine reconciliation script under:
   - `internal-admin/reconciliation/`
2. Add CI gate for schema + invariant smoke checks on samples.
3. Add dashboard widgets:
   - diff count by category
   - unmatched amount
   - reconciliation MTTR
4. Add automated daily reminder and sign-off workflow.
