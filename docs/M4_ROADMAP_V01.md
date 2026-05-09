# M4 Roadmap v0.1 (Productionization and Interop)

This document formalizes M4 after M3 completion.
Goal: evolve Karma proof/evidence flow from "operationally usable" to "production-grade and machine-enforceable."

## M4 scope

- Standardize evidence schema version signaling and compatibility checks.
- Add CI-friendly machine validators for diagnosis exports.
- Improve long-run operations readiness for proof verification pipelines.

## M4 phases

### M4.0 — Evidence schema compatibility baseline

Deliverables:

1. Exported diagnosis JSON carries stable schema marker:
   - `schemaVersion = "evidence-v1"` (canonical)
   - `evidenceVersion = "evidence-v1"` (legacy compatibility alias)
2. Add machine validator script:
   - `scripts/validate-evidence-schema.sh`
   - validates required top-level sections and key nested fields
   - supports text/json output and non-zero exit on incompatibility
3. Add command entry:
   - `make validate-evidence-schema`
4. Update docs:
   - `docs/EVIDENCE_SCHEMA_V01.md`
   - `docs/COMMANDS.md`

Acceptance:
- validator returns PASS for current exporter output
- validator returns FAIL when required schema marker/sections are missing

### M4.1 — CI gate for evidence compatibility

Target:
- provide a CI recipe (or script wrapper) that fails PR checks when exported diagnosis JSON violates schema compatibility.

Deliverables (implemented):
- CI gate wrapper script:
  - `scripts/ci-proof-gates.sh`
  - checks evidence schema marker/required fields via `validate-evidence-schema.sh`
  - checks proof-index batch policy gates via `verify-proof-index-batch.sh`
- deterministic sample evidence for CI:
  - `docs/samples/karma-evidence-sample-v1.json`
- GitHub Actions integration:
  - `forge-ci.yml` adds `proof-gates` job on PR/workflow_dispatch
- local parity:
  - `scripts/ci-local.sh` now runs proof gates by default
  - `--skip-proof-gates` can bypass for debugging
  - Make target: `make ci-proof-gates`

Acceptance:
- PR fails when sample evidence violates schema compatibility.
- PR fails when batch proof policy gate is violated.
- local `./scripts/ci-local.sh` and CI gate produce consistent pass/fail behavior.

### M4.2 — Ops-grade patrol profile

Target:
- convert existing batch proof checks into scheduled patrol policy profiles.

Deliverables (implemented):
- patrol wrapper script:
  - `scripts/proof-patrol.sh`
  - profile-based policies: `strict | balanced | lenient`
  - emits two artifacts:
    - batch summary JSON (from `verify-proof-index-batch.sh`)
    - alert-oriented JSON (`status/severity/policy/reasonSummary/nextActions`)
- predefined policy bundles:
  - strict: `--strict --max-fail 0 --min-total 3 --require-recent-pass 24`
  - balanced: `--strict --max-fail 1 --min-total 2 --require-recent-pass 72`
  - lenient: `--max-fail 2 --min-total 1 --require-recent-pass 168`
- Make target:
  - `make proof-patrol` (defaults to balanced profile)
- operator docs:
  - command examples + cron-friendly usage in `docs/COMMANDS.md`
  - handling guidance in `docs/PROOF_VERIFICATION_SOP.md`

Acceptance:
- patrol returns non-zero when batch policy gate fails.
- patrol always emits alert JSON with `status` and `severity`.
- profile switch changes thresholds without editing batch script internals.

## Notes

- M4.0 focuses on backward compatibility and machine readability, minimizing break risk.
- M4.1 and M4.2 build on existing M3 scripts and reports instead of replacing them.

## M4.3 — Agent Safety Guardian (self-check + risk registry + predictive defense v0.2)

Target:
- introduce a full-chain safety guardian that continuously records, identifies, and grades risk signals
  during validation/staging runs, and writes a registry suitable for trend analysis/predictive defense.

Deliverables (implemented):
- guardian orchestrator script:
  - `scripts/agent-safety-guardian.sh`
  - runs:
    1) local environment doctor self-check (`doctor.sh`)
    2) support-bundle integrity snapshot (`support-bundle.sh`)
    3) CI-style proof/evidence gate (`ci-proof-gates.sh`)
    4) proof patrol (`proof-patrol.sh`)
    5) risk recognition + grading + registry export
- outputs:
  - `results/agent-safety-guardian-latest.json`
  - persistent risk register:
    - `results/agent-risk-register.json`
- risk grading model:
  - severity levels: `critical | high | medium | warning`
  - includes policy violation mapping and environment/pipeline risk categories
- predictive-defense v0.2:
  - trend window statistics (`--trend-window-hours`)
  - repeat-risk escalation threshold (`--escalate-repeat-threshold`)
  - auto-escalate warning -> high when the same risk code repeats above threshold in trend window
  - time-decay weighted risk scoring (recent risks contribute more)
  - `riskHeatIndex` (0-100) for quick patrol pressure judgement
  - `recommendedPatrolProfile` auto-suggestion (`lenient | balanced | strict`)
  - machine-readable output fields:
    - `predictiveDefense.trendSummary`
    - `predictiveDefense.escalations`
    - `predictiveDefense.signals`
    - `predictiveDefense.decayModel`
    - `predictiveDefense.riskHeatIndex`
    - `predictiveDefense.recommendedPatrolProfile`
- Make target:
  - `make agent-safety-guardian`

Acceptance:
- guardian report contains structured risk objects with `riskId/category/code/severity/source`.
- guardian emits non-zero when high-severity integrity/pipeline policies fail.
- registry contains rolling history and per-code trend summary.
- predictive-defense section includes repeat-risk escalation, heat index, and auto patrol-profile recommendation.
