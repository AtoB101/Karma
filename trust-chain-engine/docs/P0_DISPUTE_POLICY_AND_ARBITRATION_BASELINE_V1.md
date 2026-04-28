# P0 Dispute Policy and Arbitration Baseline V1 (Private)

Status: Policy baseline  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_AUDIT_EVIDENCE_RETENTION_AND_EXPORT_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- `docs/P0_RACI_AND_DECISION_AUTHORITY_V1.md`

## 1. Purpose

Define a consistent dispute and arbitration baseline for P0 to ensure:

1. deterministic handling across operators
2. evidence-first decision quality
3. bounded financial and legal risk
4. measurable resolution SLA

## 2. Scope and principles

In scope (P0):

- call-level dispute intake
- settlement correctness disputes
- delivery mismatch disputes
- timeout/availability ambiguity disputes
- duplicate charge disputes

Out of scope (P0):

- fully automated final arbitration
- cross-jurisdiction legal escalation tooling
- third-party arbitration marketplace integration

Core principles:

1. Evidence over narrative.
2. Same facts -> same decision.
3. Financial correctness before speed when conflict exists.
4. All decisions must be auditable and attributable.

## 3. Dispute categories

Standard categories (required):

1. `delivery_mismatch`
   - API response does not satisfy promised product semantics.
2. `settlement_incorrect`
   - amount/token/chain/wallet mismatch.
3. `timeout_ambiguity`
   - call timeout with uncertain delivery outcome.
4. `duplicate_charge`
   - more than one effective charge for same logical call.
5. `authorization_scope_violation`
   - charge exceeds user authorization policy.
6. `other`
   - must include structured reason code.

Each dispute must include:

- `disputeId`
- `category`
- `openedAt` (UTC RFC3339)
- `openedBy` (user/provider/operator)
- `callId`
- `settlementId` (if available)
- `traceId`
- `initialClaim`

## 4. Evidence requirements and priority

Minimum evidence pack:

1. paid call record
2. settlement record
3. evidence bundle
4. authorization reference snapshot
5. risk decision reference

Evidence priority order (highest to lowest):

1. signed and hash-verified technical evidence
2. system logs with integrity proof
3. provider logs/user-provided attachments
4. narrative statements

If top-tier evidence conflicts with lower-tier evidence:

- top-tier evidence prevails unless corruption/tampering is proven.

## 5. SLA and response windows

P0 baseline SLA:

- intake acknowledgment: <= 15 minutes
- triage completion: <= 2 hours
- standard resolution target: <= 24 hours
- high-impact resolution target: <= 8 hours
- final closure confirmation: <= 48 hours

High-impact criteria:

- dispute amount above configured threshold
- duplicate charge confirmed
- systemic pattern affecting multiple users/providers

## 6. Decision matrix (deterministic outcomes)

### 6.1 Delivery mismatch

If delivery mismatch confirmed:

- settlement status -> `disputed`
- partial/full refund per product policy
- provider quality strike increments

If not confirmed:

- dispute rejected with evidence references

### 6.2 Settlement incorrect

If charged amount/token/recipient differs from intended contract:

- immediate Sev-1 incident path
- corrective settlement/refund mandatory
- freeze affected release lane until corrected

### 6.3 Timeout ambiguity

If delivery cannot be proven:

- default to user-protective handling (no successful charge outcome)
- move to manual review if conflicting proofs appear

### 6.4 Duplicate charge

If duplicate charge confirmed:

- immediate refund/remediation required
- incident path follows duplicate charge runbook
- recurrence prevention action item mandatory

## 7. Arbitration authority and approvals

Authority chain:

1. Dispute Operator (triage and recommendation)
2. Dispute Lead (approval for normal cases)
3. Incident Commander + Settlement Lead + Risk Lead (high-impact cases)

Final authority for high-impact disputes:

- designated accountable approver from `P0_RACI_AND_DECISION_AUTHORITY_V1.md`

No single operator may both investigate and fully approve high-impact dispute closure.

## 8. Compensation and remediation baseline

Compensation types:

1. direct refund
2. settlement reversal equivalent (where supported)
3. service credit (only for non-financial correctness issues)

Compensation rules:

- financial correctness errors: refund-first
- service degradation without wrong charge: credit/refund per policy
- duplicate charge: full duplicate amount returned

All compensation actions must reference:

- `disputeId`
- `remediationId`
- settlement transaction or credit ledger entry

## 9. Communication policy

Internal updates:

- first internal dispute summary within 30 minutes for high-impact disputes
- update interval every 2 hours until stabilized

External/user communication:

- acknowledgment with ticket id and category
- resolution statement with clear rationale and evidence references
- no disclosure of private model/routing/risk logic internals

## 10. Quality control and consistency checks

Weekly audit sample:

- randomly sample at least 10 closed disputes (or all if < 10)
- verify category correctness
- verify evidence completeness
- verify decision consistency across similar cases
- verify SLA compliance

Consistency KPI:

- decision consistency >= 95% across matched-case clusters
- reopened dispute ratio <= 5%
- overdue dispute ratio <= 3%

## 11. Escalation triggers

Automatic escalation if any condition holds:

1. dispute rate > 8% for three consecutive days
2. duplicate charge disputes > 0 in a day
3. overdue disputes exceed SLA threshold
4. same root cause category repeats > configured threshold

Escalation actions:

- switch ops state to `correct` or `freeze`
- activate incident response runbook
- assign corrective owner with deadline

## 12. Required records and retention

For each dispute, retain:

- full timeline
- all evidence links and integrity checks
- decision rationale
- approver identities and timestamps
- remediation records

Retention baseline (minimum):

- standard disputes: 3 years
- high-impact disputes: 5 years

## 13. Conformance checklist

Each dispute case must satisfy:

- [ ] category assigned from standard set
- [ ] required identifiers present (`disputeId/callId/traceId`)
- [ ] minimum evidence pack attached
- [ ] decision mapped to deterministic matrix
- [ ] approval path valid for impact level
- [ ] remediation record linked (if applicable)
- [ ] closure communication recorded

## 14. Implementation next steps

1. Create dispute schema and status machine under private contracts folder.
2. Add SLA monitors and overdue alerting in ops dashboard.
3. Add weekly consistency audit report to weekly review ritual.
4. Add dispute export bundle profile aligned with audit evidence policy.
