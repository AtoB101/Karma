# P0 Provider Contract Negotiation Checklist V1 (Private)

Status: Negotiation checklist  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_API_PROVIDER_PARTNERSHIP_TERMS_BASELINE_V1.md`
- `docs/P0_DISPUTE_POLICY_AND_ARBITRATION_BASELINE_V1.md`
- `docs/P0_AUDIT_EVIDENCE_RETENTION_AND_EXPORT_V1.md`

## 1. Purpose

Turn baseline partnership terms into a practical negotiation checklist to:

1. speed up provider deal closure
2. keep financial correctness and risk controls non-negotiable
3. avoid legal ambiguity in disputes and settlement

## 2. Negotiation framework

Classify each term into:

- Must-have (non-negotiable)
- Negotiable range (trade-off allowed with approval)
- Red-line rejection (deal must stop if violated)

Approval rule:

- Any deviation from Must-have requires Legal + Risk + Settlement dual sign-off.

## 3. Must-have terms (cannot be removed)

### 3.1 Settlement correctness

- [ ] One successful delivery must map to at most one successful settlement.
- [ ] Duplicate settlement remediation process defined in writing.
- [ ] Idempotency and reconciliation obligations acknowledged by provider.
- [ ] On-chain settlement references and timestamps treated as source-of-truth.

### 3.2 Auditability

- [ ] Provider agrees to supply required dispute/audit artifacts within SLA.
- [ ] Evidence retention windows meet minimum contract baseline.
- [ ] Hash/digest verifiability supported for payload proofing.

### 3.3 Service quality

- [ ] SLA metrics explicitly defined (availability, latency, error budget).
- [ ] Incident notification SLA accepted (critical incidents within defined window).
- [ ] Maintenance windows and notice expectations documented.

### 3.4 Legal/compliance minimum

- [ ] Data handling and confidentiality clauses signed.
- [ ] Jurisdiction and dispute forum defined.
- [ ] Sanctions/compliance representations included (if applicable).

## 4. Negotiable terms (with controlled ranges)

### 4.1 Commercial

- [ ] Price per call (within approved range)
- [ ] Volume tiers / discounts
- [ ] Settlement cycle cadence (e.g., T+0 / T+1 / T+N)
- [ ] Minimum monthly commitment (if any)

### 4.2 Operational

- [ ] Rate limit ceilings
- [ ] Burst allowance
- [ ] Non-critical support response windows

### 4.3 Liability structure

- [ ] Liability caps (must not undercut fraud/duplicate remediation obligations)
- [ ] Indemnity scope refinements

## 5. Red-line terms (automatic no-go)

If provider insists on any of the below, stop negotiation:

1. No accountability for duplicate billing or settlement incidents.
2. No requirement to provide dispute evidence.
3. Ability to retroactively alter billed call logs without traceability.
4. Refusal to define incident notification timeline.
5. Clauses that force one-sided irreversible payment without dispute window.
6. Contract language that blocks legally required audit access.

## 6. Term-by-term negotiation table

Use this table in every negotiation round:

| Clause | Category (Must/Negotiable/Red-line) | Proposed by us | Proposed by provider | Status | Owner | Notes |
|---|---|---|---|---|---|---|
| Settlement mapping | Must | 1:1 success->settlement |  | open | Settlement lead |  |
| Duplicate remediation SLA | Must | <= 24h triage |  | open | Ops lead |  |
| Evidence export SLA | Must | <= 4h for Sev-1 cases |  | open | Risk lead |  |
| Price per call | Negotiable | baseline X |  | open | Biz owner |  |
| Availability SLA | Must | >= 99.0% |  | open | Platform owner |  |
| Incident notice SLA | Must | <= 15 min Sev-1 |  | open | Ops lead |  |
| Liability cap | Negotiable | >= 6 months fees |  | open | Legal |  |

## 7. Standard fallback package (if negotiation stalls)

If no agreement in primary package, offer one fallback package:

Fallback A:

- Higher per-call price
- Looser non-critical support SLA
- same Must-have and Red-line terms unchanged

Fallback B (optional):

- Lower base price with strict usage commitment
- same dispute and evidence obligations

Never relax:

- settlement correctness
- duplicate remediation
- evidence accessibility
- incident notification baseline

## 8. Decision gates and authority

### Gate 1: Commercial fit

- Pass if unit economics remain above internal floor.

### Gate 2: Risk fit

- Pass if fraud/dispute exposure stays within acceptable envelope.

### Gate 3: Legal fit

- Pass if enforceability and audit rights are preserved.

Final authority:

- Commercial owner + Legal owner + Risk owner must all approve.

## 9. Pre-signing verification checklist

- [ ] Final term sheet matches approved negotiation table
- [ ] No hidden appendix conflicting with core terms
- [ ] Annexes include SLA and incident procedure references
- [ ] Dispute and arbitration clauses align with baseline policy
- [ ] Data retention/export clauses align with audit baseline
- [ ] Signature authority of provider confirmed

## 10. Post-signing activation checklist

- [ ] Register provider contract ID in internal admin system
- [ ] Map contract terms to onboarding controls
- [ ] Configure SLA and alert rules per signed terms
- [ ] Upload signed contract and redline summary to secure repository
- [ ] Schedule Day-7 and Day-30 contract compliance reviews

## 11. Negotiation retrospective template

After each closed negotiation:

- Deal ID:
- Outcome (`signed|dropped|deferred`):
- Time to close:
- Main blockers:
- Terms most frequently contested:
- Which fallback package used:
- Incidents after signing (if any):
- Process improvements for next negotiation:

## 12. Quick reference

Do:

1. protect settlement correctness first
2. document every negotiated change with owner + rationale
3. align signed terms with operational controls before go-live

Do not:

1. trade away evidence/dispute rights for pricing discounts
2. accept ambiguous language on incident handling
3. activate provider before legal/risk sign-offs complete

