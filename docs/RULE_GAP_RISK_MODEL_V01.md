# Rule Gap Risk Model v0.1 (Agent Safety Guardian)

This document defines a rule-centric threat lens for TrustChain.
Focus: attackers often exploit valid protocol paths and policy boundaries rather than violating obvious rules.

## 1) Why rule-gap modeling

- Traditional checks catch explicit failures.
- Real attackers maximize gain inside allowed ranges.
- We need warning/alarm capability for "policy abuse patterns" and "rule edge exploitation."

## 2) Rule-gap categories (v0.1)

### A) Policy-edge exhaustion

Behavior:
- repeated near-limit actions designed to drain per-window/daily quota while staying "valid"

Signals:
- rising frequency of policy/coverage warnings
- repeated `patrol_min_total_violated` or `patrol_strict_no_match`
- sustained high risk heat index with no direct critical revert

Guardian mapping:
- `ruleGapSignals[]` with kind `policy_edge_exhaustion`

### B) Observation blind-window abuse

Behavior:
- operate during periods where sample count is low or no bundle matches strict window

Signals:
- repeated low coverage policy violations:
  - `strictNoMatchViolated`
  - `minTotalViolated`
- high recent-pass age pressure

Guardian mapping:
- `ruleGapSignals[]` with kind `observation_blind_window`

### C) Drift between recommendation and execution

Behavior:
- system keeps recommending stricter profile but execution remains lenient/balanced

Signals:
- `profileRecommendation.recommended` differs from active profile for multiple runs
- auto-tuning pending streak keeps increasing without application

Guardian mapping:
- `ruleGapSignals[]` with kind `recommendation_execution_drift`

### D) Repeated warning code escalation

Behavior:
- exploit a warning-level path repeatedly until impact accumulates

Signals:
- same warning code repeats over threshold in trend window
- warning -> high escalation fired

Guardian mapping:
- escalation events in `predictiveDefense.escalations`
- `ruleGapSignals[]` with kind `repeat_warning_exploitation`

## 3) Alerting levels

- `warning`: weak but meaningful rule-gap hint
- `high`: sustained or repeated exploitable pattern
- `critical`: strong indication of active exploitation window

## 4) Machine-readable outputs

The guardian report includes:

- `ruleGapSignals[]`:
  - `id`
  - `kind`
  - `severity`
  - `score`
  - `title`
  - `detail`
  - `evidence`
- `ruleGapSummary`:
  - `count`
  - `bySeverity`
  - `maxScore`

And alert compatibility output:

- `alerts[]` with:
  - `level` (`warning|high|critical`)
  - `source`
  - `message`
  - `recommendedAction`

## 5) Operational policy suggestion

- For validation phase:
  - keep guardian auto mode enabled
  - route `critical` alerts to immediate on-call
  - route `high` alerts to same-day remediation
- For production pilot:
  - fail gate when `ruleGapSummary.maxScore >= 80`
  - force strict profile when drift persists beyond confirmation threshold

