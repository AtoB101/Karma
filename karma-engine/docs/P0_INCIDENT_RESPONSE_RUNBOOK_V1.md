# P0 Incident Response Runbook V1 (Private)

Status: Operational runbook  
Scope: `karma-engine` only (do not publish)

Related docs:

- `docs/P0_GATEWAY_EXECUTION_PLAN_V1.md`
- `docs/P0_EVIDENCE_AND_SETTLEMENT_DATA_CONTRACTS_V1.md`
- `docs/P0_DAILY_OPERATIONS_REPORT_TEMPLATE_V1.md`

## 1. Purpose

Provide minute-level incident response playbooks for four P0 critical scenarios:

1. Settlement failure spike
2. Duplicate charge / duplicate settlement
3. Dispute surge
4. Provider outage or severe degradation

This runbook is mandatory during pilot and early production-like operation.

## 2. Incident command model

Required roles during any Sev-1/Sev-2 incident:

- Incident Commander (IC): overall coordinator
- Settlement Lead: settlement pipeline actions
- Risk Lead: policy switches and abuse controls
- Ops Lead: communications, logging, timeline
- Scribe: timeline and evidence recorder

Golden rules:

1. Stabilize first, then optimize.
2. Stop financial harm before debugging root cause.
3. Every major action must be timestamped and attributable.

## 3. Severity definition

- Sev-1: Active financial risk or widespread payment correctness issue.
- Sev-2: Significant degradation likely to become Sev-1 if unresolved.
- Sev-3: Limited impact, no immediate financial integrity risk.

Escalation targets:

- Sev-1: page all on-call roles immediately
- Sev-2: alert IC + module lead within 5 minutes
- Sev-3: assign owner, resolve in normal sprint lane

## 4. Shared first 10 minutes (all incident types)

### T+0 to T+2 minutes

- [ ] Declare incident channel and incident ID
- [ ] Assign IC and Scribe
- [ ] Freeze non-critical deploys
- [ ] Capture initial blast radius estimate

### T+2 to T+5 minutes

- [ ] Confirm severity (Sev-1/2/3)
- [ ] Assign technical leads by module
- [ ] Snapshot dashboards and key metrics
- [ ] Record first hypothesis set

### T+5 to T+10 minutes

- [ ] Execute relevant scenario-specific containment actions
- [ ] Confirm whether financial loss risk is still active
- [ ] Publish first internal status update

## 5. Scenario A: Settlement failure spike

Trigger examples:

- Settlement success rate drops below 95%
- Spike in failed settlements over short interval
- Settlement queue backlog grows abnormally

### Minute-level actions

#### T+0 to T+5

- [ ] IC declares "Settlement Failure Spike"
- [ ] Settlement Lead confirms affected networks/tokens/providers
- [ ] Risk Lead tightens velocity caps (temporary)

#### T+5 to T+10

- [ ] Pause new settlement commits for affected slice only (if possible)
- [ ] Keep call evidence generation active
- [ ] Enable degraded mode banner for internal operators

#### T+10 to T+20

- [ ] Run reconciliation job: paid_call vs settlement
- [ ] Classify failures: network, nonce, balance, contract revert, timeout
- [ ] Start safe retry for idempotent pending records only

#### T+20 to T+30

- [ ] Decide: partial resume or continue pause
- [ ] Publish status with ETA and customer-impact summary

### Exit criteria

- Settlement success rate restored to >= 98% on recent sample window
- Reconciliation mismatch reduced to zero (or explicitly documented)
- No uncontrolled duplicate retries

## 6. Scenario B: Duplicate charge / duplicate settlement

Trigger examples:

- Same `callId` maps to multiple successful settlement records
- Duplicate tx confirmations linked to same logical charge

### Minute-level actions

#### T+0 to T+3

- [ ] Declare Sev-1 immediately
- [ ] Hard-stop settlement commit path globally or affected segment
- [ ] Preserve logs and evidence snapshots

#### T+3 to T+8

- [ ] Identify duplicate scope by `callId`, `idempotencyKey`, `traceId`
- [ ] Block retries that bypass idempotency gate
- [ ] Mark affected records for refund/remediation workflow

#### T+8 to T+15

- [ ] Quantify impacted users/providers and amount at risk
- [ ] Prepare remediation list with deterministic ordering
- [ ] Start manual review gate for any new settlement attempt

#### T+15 to T+30

- [ ] Execute refund/remediation play (per policy)
- [ ] Draft internal incident bulletin and external-facing statement (if needed)
- [ ] Keep settlement path paused until duplication root cause is controlled

### Exit criteria

- Root cause identified and patched
- Replay test demonstrates no duplicate settlement for repeated requests
- All impacted records have remediation status

## 7. Scenario C: Dispute surge

Trigger examples:

- Dispute rate exceeds 8% threshold
- Backlog grows faster than resolution capacity

### Minute-level actions

#### T+0 to T+5

- [ ] Declare "Dispute Surge" (Sev-2 or Sev-1 based on pace)
- [ ] Activate dispute triage queue
- [ ] Increase risk checks for disputed provider/product slices

#### T+5 to T+15

- [ ] Bucket disputes by root category:
  - delivery mismatch
  - timeout ambiguity
  - pricing mismatch
  - duplicate charge claim
- [ ] Prioritize high-financial-impact disputes

#### T+15 to T+30

- [ ] Apply temporary controls:
  - lower spend caps
  - stricter allow/review thresholds
  - optional provider throttling
- [ ] Assign extra dispute operators

### Exit criteria

- Dispute inflow normalizes below threshold
- Backlog trend stops growing
- High-severity disputes have owner and ETA

## 8. Scenario D: Provider outage / severe degradation

Trigger examples:

- Provider endpoint unavailable
- Latency spike causing high timeout rate
- Error-rate surge from provider side

### Minute-level actions

#### T+0 to T+5

- [ ] Confirm provider outage signal from multiple probes
- [ ] Notify provider contact and open shared incident thread
- [ ] Route new calls to approved fallback (if policy allows)

#### T+5 to T+15

- [ ] If no safe fallback: disable provider route
- [ ] Prevent settlement for undelivered calls
- [ ] Keep evidence logs for failed attempts

#### T+15 to T+30

- [ ] Assess financial impact window
- [ ] Publish operator advisory with expected behavior
- [ ] Prepare staged resume criteria with provider

### Exit criteria

- Provider stability restored (uptime/latency within agreed range)
- Rehearsal sanity checks pass before full traffic restore
- No unresolved mismatches for outage window

## 9. Communication templates (internal)

## 9.1 First alert (within 10 minutes)

Template:

- Incident ID:
- Severity:
- Start time (UTC):
- Affected scope:
- Financial risk status:
- Immediate containment actions:
- Next update ETA:

## 9.2 30-minute update

- Current state:
- What changed since last update:
- Open risks:
- Decision (continue containment / partial restore / full pause):
- Next update ETA:

## 10. Data and evidence preservation

Mandatory evidence capture:

- Incident timeline with timestamps
- Dashboard snapshots at declaration and closure
- Affected record lists (`callId`, `settlementId`, `traceId`)
- Actions taken and actor identity
- Final root-cause analysis and remediation proof

Retention baseline:

- Sev-1 records: 5 years
- Sev-2 records: 3 years
- Sev-3 records: 1 year

## 11. Recovery and restart checklist

Before restoring full traffic:

- [ ] containment controls validated
- [ ] root-cause patch deployed or compensating control active
- [ ] replay/duplicate tests passed
- [ ] reconciliation mismatch is zero or documented with owner
- [ ] IC approval + module lead approval recorded

After restore:

- [ ] 60-minute enhanced monitoring window completed
- [ ] incident marked `monitoring` then `resolved`
- [ ] post-incident review scheduled (within 48h)

## 12. Post-incident review (mandatory)

Review checklist:

- [ ] incident timeline complete
- [ ] root cause categorized (people/process/system/external)
- [ ] what detection should have happened earlier
- [ ] permanent fixes and owners assigned
- [ ] runbook updates required identified

## 13. Quick reference card

If financial correctness is uncertain:

1. Pause affected settlement path first.
2. Preserve evidence and logs immediately.
3. Reconcile ledgers before resume.
4. Resume only with explicit approvals.

