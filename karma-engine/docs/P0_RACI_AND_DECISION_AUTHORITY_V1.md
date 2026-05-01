# P0 RACI and Decision Authority V1 (Private)

Status: Governance baseline  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_INCIDENT_RESPONSE_RUNBOOK_V1.md`
- `docs/P0_WEEKLY_EXEC_REVIEW_RITUAL_V1.md`

## 1. Purpose

Define clear accountability and authority for P0 operations so that:

1. incidents are handled without command conflicts
2. financial-risk decisions are made quickly and traceably
3. expansion/freeze decisions are auditable

## 2. Core roles

- Exec Sponsor (ES)
- Incident Commander (IC)
- Risk Lead (RL)
- Settlement Lead (SL)
- Routing Lead (RoL)
- Ops Lead (OL)
- Analytics Lead (AL)
- Dispute Lead (DL)
- Compliance/Legal Reviewer (CL)

## 3. RACI matrix (P0 critical decisions)

Legend:

- R = Responsible
- A = Accountable (single owner)
- C = Consulted
- I = Informed

| Decision / Action | ES | IC | RL | SL | RoL | OL | AL | DL | CL |
|---|---|---|---|---|---|---|---|---|---|
| Enable new provider go-live | I | C | C | C | C | R | I | I | A |
| Approve pricing experiment start | A | I | C | C | I | R | C | I | C |
| Trigger emergency freeze | I | A | R | R | C | C | I | C | I |
| Resume after freeze | A | R | C | C | C | C | C | C | C |
| Pause settlement path (partial) | I | A | C | R | C | C | I | I | I |
| Pause settlement path (global) | A | R | C | R | C | C | I | I | C |
| Dispute surge escalation | I | A | C | C | I | C | I | R | C |
| Refund/remediation approval (material) | A | C | C | R | I | C | I | C | C |
| Weekly expand/hold/freeze decision | A | C | C | C | C | C | C | C | C |
| Public external statement approval | A | C | I | I | I | R | I | I | C |

## 4. Decision classes and authority thresholds

### 4.1 Class D1: Operational routine (low risk)

Examples:

- minor routing parameter tuning
- non-financial dashboard/report adjustments

Authority:

- Accountable: module lead
- No exec approval required
- Must be logged in daily report

### 4.2 Class D2: Financial-impacting but bounded

Examples:

- provider-level pause
- spend cap changes
- risk threshold tightening

Authority:

- Accountable: IC during incident, otherwise Ops Lead
- Requires one peer approval from Risk or Settlement Lead

### 4.3 Class D3: Material financial/systemic risk

Examples:

- global settlement freeze
- bulk refund/remediation decision
- restart after Sev-1

Authority:

- Accountable: Exec Sponsor
- Requires IC + Risk Lead + Settlement Lead concurrence
- Compliance consulted when external impact is possible

## 5. Incident-time command protocol

Single-command principle:

1. IC has operational command during active incident.
2. Conflicting instructions from non-IC roles are ignored until IC resolution.
3. Escalation to Exec Sponsor is mandatory for Class D3.

Command cadence:

- first command packet within 5 minutes
- status update every 30 minutes for Sev-1
- explicit handoff record if IC changes

## 6. Freeze / Resume explicit authority

### 6.1 Freeze authority

Can trigger immediate freeze:

- IC (during active incident)
- Exec Sponsor (at any time)

Can request freeze (not final):

- Risk Lead
- Settlement Lead
- Ops Lead

### 6.2 Resume authority

Resume requires all:

1. IC recommendation
2. Risk Lead sign-off
3. Settlement Lead sign-off
4. Exec Sponsor approval

Minimum resume evidence:

- reconciliation mismatch status
- duplicate settlement verification
- latest error-rate trend
- rollback readiness confirmation

## 7. Expansion / Hold / Freeze governance

Weekly decision owner:

- Accountable: Exec Sponsor

Required inputs:

1. weekly metric roll-up
2. stop-loss trigger status
3. top incident summary
4. unresolved risk list

Decision definitions:

- expand: add scope/users/providers
- hold: keep current scope, optimize quality
- freeze: stop expansion, reliability-only work

## 8. Escalation ladder

When conflict or uncertainty occurs:

1. module lead -> IC
2. IC -> Exec Sponsor
3. Exec Sponsor -> Compliance/Legal (if exposure risk)

Maximum allowed decision delay:

- D2 decisions: 30 minutes
- D3 decisions: 60 minutes

## 9. Decision logging standard (mandatory)

Every D2/D3 decision must record:

- decisionId
- timestamp (UTC)
- class (`D2|D3`)
- decision (`approve|reject|freeze|resume|rollback`)
- accountable role and name
- consulted roles
- rationale (short)
- expected impact
- review checkpoint time

Storage:

- internal-admin decision log registry (append-only preferred)

## 10. Anti-patterns (must avoid)

- multi-head command during incident
- undocumented verbal approvals
- restarting settlement path without reconciliation evidence
- expansion decisions made from vanity metrics only

## 11. Conformance checklist

- [ ] All core roles assigned by name (not role placeholder only)
- [ ] On-call rota mapped to IC fallback chain
- [ ] Freeze/resume flow tested in tabletop drill
- [ ] Decision log template integrated into ops workflow
- [ ] Weekly meeting uses expand/hold/freeze template

