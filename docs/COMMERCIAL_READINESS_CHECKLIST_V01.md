# TrustChain Commercial Readiness Checklist V0.1

## Purpose

Provide a machine-executable commercial-readiness baseline so teams can decide whether the current branch is:

- `pilot-ready` (design partner / controlled traffic)
- `commercial-ready` (business-grade baseline met)

## Gate Levels

The gate script (`scripts/commercialization-gate.sh`) evaluates three layers:

1. MUST (hard requirements)
   - failure means **not ready for commercial release**
2. SHOULD (important maturity requirements)
   - warnings for near-term hardening backlog
3. CAN (optional improvements)
   - optimization opportunities

## MUST Baseline (v0.1)

- evidence compatibility gate exists and passes (`scripts/ci-proof-gates.sh`)
- risk guardian and patrol scripts exist
- API contract exists (`openapi/trustchain-v1.yaml`)
- API service and smoke script exist (`scripts/api_server.py`, `scripts/api-smoke.sh`)

## SHOULD Baseline (v0.1)

- API roadmap doc exists (`docs/API_ROADMAP_V01.md`)
- rule-gap model doc exists (`docs/RULE_GAP_RISK_MODEL_V01.md`)
- proof SOP doc exists (`docs/PROOF_VERIFICATION_SOP.md`)

## CAN Baseline (v0.1)

- support bundle script exists
- proof index verifiers exist
- community/governance docs exist

## Outputs

`results/commercialization-gate-latest.json`

Key fields:

- `overallStatus`: `commercial-ready` | `pilot-ready` | `not-ready`
- `must.ok`: hard gate result
- `should.warningCount`: maturity warning count
- `actionPlan`: prioritized next actions

## Policy Notes

- This v0.1 gate intentionally focuses on repository-level readiness checks.
- Production infra controls (HA DB, key rotation, SLO, compliance controls) should be tracked in v0.2+ as external environment gates.
