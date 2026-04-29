# P0 Audit Evidence Retention and Export V1 (Private)

Status: Policy baseline  
Scope: `trust-chain-engine` only (do not publish)

Related docs:

- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_REVENUE_RECONCILIATION_PLAYBOOK_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- `docs/P0_SECRETS_AND_KEY_MANAGEMENT_BASELINE_V1.md`

## 1. Purpose

Define a unified standard for:

1. audit evidence retention
2. evidence integrity and traceability
3. export package format for external review
4. chain-of-custody controls

Goal:

- make disputes, audits, and investor diligence verifiable with consistent evidence packs

## 2. Evidence categories

P0 evidence is classified into:

1. Transaction evidence
   - call, settlement, tx hash, status transitions
2. Integrity evidence
   - digests, signatures, manifest hash chain
3. Operational evidence
   - incident timeline, approvals, rollback actions
4. Financial evidence
   - reconciliation reports, refund/remediation records
5. Access evidence
   - privileged access logs for sensitive actions

## 3. Retention policy

## 3.1 Minimum retention windows

- Settlement and transaction evidence: 3 years
- Evidence bundles and manifests: 5 years
- Sev-1 incident evidence: 5 years
- Sev-2 incident evidence: 3 years
- Sev-3 incident evidence: 1 year
- Access/approval logs for critical actions: 2 years

## 3.2 Storage tiers

- Hot tier (frequent query): first 90 days
- Warm tier (operational lookup): up to 12 months
- Cold tier (audit archive): beyond 12 months

## 3.3 Immutability requirements

- Evidence bundles are append-only (no in-place overwrite)
- Corrections require superseding record linked by `supersedesRef`
- Deletion is prohibited unless legal mandate is documented and approved

## 4. Data integrity and traceability

Mandatory fields for every exportable record:

- `schemaVersion`
- `generatedAt`
- `source`
- `traceId`

Trace continuity requirement:

- `callId -> settlementId -> evidenceId`
- all linked by consistent `traceId`

Integrity controls:

1. `requestDigest` and `responseDigest` stored for call-related evidence
2. `manifestDigest` generated per export package
3. signature metadata recorded in `integrityProof`

## 5. Export package standard

## 5.1 Package structure

Recommended package layout:

```text
audit-export-<timestamp>/
  manifest.json
  summary.json
  paid-calls.json
  settlements.json
  evidence-bundles.json
  reconciliation.json
  incidents/
    incident-<id>.json
  signatures/
    manifest.sig
```

## 5.2 Mandatory files

- `manifest.json`
  - file list, sizes, per-file digests, package digest
- `summary.json`
  - scope window, counts, status overview
- `reconciliation.json`
  - call vs settlement vs revenue parity summary

## 5.3 Export metadata

`summary.json` must include:

- `exportId`
- `windowStart`
- `windowEnd`
- `generatedBy`
- `generatedAt`
- `requestedBy`
- `reason` (`audit|dispute|investor|internal-review`)

## 6. Chain-of-custody controls

For each export:

1. Requestor identity logged
2. Approver identity logged
3. Export operator identity logged
4. Hash/signature verification log recorded
5. Delivery method and recipient recorded

No anonymous export is allowed.

## 7. Access and authorization

Export permission tiers:

- Tier A (full evidence + incidents): audit lead, security lead
- Tier B (financial + settlement only): finance lead, ops lead
- Tier C (redacted summary): internal stakeholders

Rules:

- least privilege by default
- temporary access grants auto-expire
- privileged export actions must be dual-approved for external recipients

## 8. Redaction baseline

Never export:

- raw private keys
- plaintext API secrets
- internal credentials
- unrelated tenant/user sensitive identifiers

Redact where required:

- direct PII fields (replace with pseudonymous ids)
- internal infrastructure topology details
- sensitive provider contract terms not required for audit scope

## 9. Verification checklist before release

Before releasing any export package:

- [ ] package hash computed and recorded
- [ ] file-level digests verified
- [ ] signature validation passed
- [ ] reconciliation parity checked
- [ ] redaction review completed
- [ ] approval records attached

If any item fails:

- export is blocked until corrected

## 10. Dispute-specific fast export (SLA mode)

When dispute escalation is active:

- generate scoped evidence export within 60 minutes
- include only affected `callId`/`settlementId` window plus required context
- attach dispute timeline and remediation status

SLA targets:

- T+30 min: scoped summary ready
- T+60 min: signed evidence package delivered internally

## 11. Audit-readiness KPIs

Track monthly:

- Export success rate
- Mean export generation time
- Mean verification time
- Export rejection rate (integrity/redaction failures)
- Evidence trace continuity success rate

Target baseline:

- export success >= 99%
- verification pass >= 99%
- trace continuity >= 99.5%

## 12. Control failures and escalation

Critical failures:

1. missing evidence for confirmed settlement
2. digest mismatch in export package
3. unsigned package where signature is required
4. unauthorized export access

Escalation policy:

- classify as Sev-1
- freeze non-essential exports
- initiate incident runbook (`P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`)
- produce corrective action report within 24 hours

## 13. Implementation checklist

- [ ] Define export schemas under internal contracts directory
- [ ] Add automated digest/signature verification in CI
- [ ] Add export audit log table with chain-of-custody fields
- [ ] Add redaction policy test cases
- [ ] Add monthly KPI report for audit-readiness

