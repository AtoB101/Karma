# P0 API Provider Partnership Terms Baseline V1 (Private)

Status: Internal baseline draft  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_PROVIDER_ONBOARDING_CHECKLIST_V1.md`
- `docs/P0_DISPUTE_POLICY_AND_ARBITRATION_BASELINE_V1.md`
- `docs/P0_REVENUE_RECONCILIATION_PLAYBOOK_V1.md`
- `docs/P0_AUDIT_EVIDENCE_RETENTION_AND_EXPORT_V1.md`

## 1. Purpose

Define the minimum commercial and operational terms for onboarding API providers in P0.

This baseline is used to:

1. reduce partner onboarding ambiguity
2. align settlement and SLA expectations
3. standardize dispute and liability handling
4. protect Karma operational and legal boundaries

## 2. Partner profile and qualification

Minimum requirements:

- verifiable legal entity or accountable operator
- verifiable domain and endpoint ownership
- technical contact and escalation contact available
- ability to maintain SLA reporting data

Disqualifiers:

- unclear service ownership
- repeated unresolved outage behavior
- refusal to support evidence-based dispute process

## 3. Product and pricing terms

Required terms:

- explicit `productId` and endpoint scope
- per-call pricing in smallest settlement unit
- supported chain/token pair
- billing interval (real-time per call in P0)
- refund eligibility rules

Change policy:

- pricing updates require advance notice window (default >= 7 days)
- emergency pricing changes require explicit Karma approval

## 4. Settlement terms

Partner must agree to:

- non-custodial settlement model
- one successful paid call maps to one settlement record
- idempotency-protected settlement commit flow
- reconciliation support between call ledger and settlement ledger

Required setup:

- verified payee wallet ownership
- chainId and token allowlist confirmation
- payout caps and safety thresholds enabled

## 5. Service level agreement (SLA) baseline

P0 minimums:

- uptime target: >= 99.0% (rolling 7-day baseline)
- p95 latency target: <= 1500 ms for priced endpoint
- error-rate transparency with category reporting

SLA breach response:

- minor breach: corrective plan within 24h
- major repeated breach: traffic throttling or temporary disablement
- critical breach: emergency suspension

## 6. Data boundary and usage rights

Partner commitments:

- process only required data for service delivery
- avoid retaining unnecessary user identifiers
- do not use Karma operational data outside agreed scope

Karma commitments:

- expose only minimum required call context
- keep partner secrets outside public artifacts
- support auditable evidence exports with redaction controls

## 7. Incident and escalation obligations

Partner must provide:

- 24/7 incident escalation channel for P0 window
- incident acknowledgement SLA (default <= 15 minutes for Sev-1)
- status update cadence during incident (default every 30 minutes)

Karma may enforce:

- temporary route disablement
- settlement pause for undelivered calls
- enhanced monitoring and restricted traffic mode

## 8. Dispute and arbitration terms

Dispute process baseline:

1. intake with structured evidence references
2. triage and category assignment
3. evidence-based initial decision
4. escalation to arbitration when needed

Evidence priority:

- call and settlement records
- request/response digest lineage
- signed/exported evidence manifests

Partner obligations:

- respond within dispute SLA window
- provide supplementary logs when requested
- honor final arbitration decision according to policy

## 9. Liability and compensation boundaries

Baseline principles:

- each party accountable for its own system failures
- compensation tied to verified impact scope
- no unlimited liability in P0 baseline

Compensation modes:

- refund to payer
- settlement reversal/remediation
- service credit (only when explicitly agreed)

Excluded from automatic compensation:

- unverifiable claims without evidence chain
- force majeure events (subject to explicit terms)

## 10. Security and key management obligations

Partner must:

- follow secret and key hygiene standards
- rotate credentials on schedule or incident trigger
- prevent plaintext secret exposure in logs/artifacts

Karma reserves right to:

- request security attestation summary
- trigger emergency credential rotation on incident
- suspend integration on unresolved security risk

## 11. Audit and compliance support

Partner agrees to:

- preserve required operational evidence for agreed retention period
- support audit export requests in defined format
- cooperate in post-incident root cause review

Minimum retention alignment:

- follow `P0_AUDIT_EVIDENCE_RETENTION_AND_EXPORT_V1.md` baseline

## 12. Termination and suspension

Immediate suspension triggers:

- repeated financial correctness failures
- duplicate-charge incidents without remediation
- unresolved high-severity security incident

Termination triggers:

- chronic SLA breach with no corrective progress
- refusal to comply with dispute/arbitration outcomes
- material contractual misrepresentation

## 13. Commercial review cadence

Recommended cadence:

- weekly operational review in pilot stage
- monthly commercial review after stabilization

Review topics:

- volume and conversion
- settlement and dispute trends
- SLA and incident behavior
- pricing fit and sustainability

## 14. Template clause checklist (for legal drafting)

- [ ] party identity and authority
- [ ] product scope and exclusions
- [ ] settlement mechanics and token/chain scope
- [ ] SLA targets and breach handling
- [ ] dispute and arbitration process
- [ ] liability cap and compensation methods
- [ ] data handling and confidentiality
- [ ] security obligations and incident notification
- [ ] suspension/termination rights
- [ ] governing law and jurisdiction

## 15. Internal approval gate before signing

Required approvals:

- business owner
- risk owner
- settlement owner
- legal/compliance reviewer

Signing gate:

- no partner agreement becomes active without all required approvals recorded.

