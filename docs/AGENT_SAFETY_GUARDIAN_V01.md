# Agent Safety Guardian v0.3

This document defines the full-chain "Agent Safety Guardian" workflow for internal validation, risk identification, severity tagging, risk registration, and predictive-defense signal generation.

## 1) Goals

- Run reproducible internal self-checks before/during market validation.
- Identify and classify risks from pipeline and patrol signals.
- Persist a machine-readable risk register for longitudinal analysis.
- Emit trend and escalation signals for predictive defense.

## 2) Entry command

```bash
./scripts/agent-safety-guardian.sh --profile balanced
```

Make shortcut:

```bash
make agent-safety-guardian
```

## 3) Execution stages

The guardian runs these stages in one flow:

1. **Doctor self-check** (`scripts/doctor.sh --format json`)  
   Verifies local runtime context and baseline readiness.
2. **Support bundle snapshot** (`scripts/support-bundle.sh`)  
   Produces fresh integrity evidence for patrol scope.
3. **Proof/evidence CI gates** (`scripts/ci-proof-gates.sh`)  
   Validates schema compatibility and batch proof policy controls.
4. **Patrol scan** (`scripts/proof-patrol.sh`)  
   Executes profile-based patrol and emits batch + alert JSON.
5. **Risk synthesis + registry append**  
   Builds final report and updates persistent risk register.

## 4) Key options

```bash
./scripts/agent-safety-guardian.sh \
  --profile balanced \
  --trend-window-hours 24 \
  --escalate-repeat-threshold 2 \
  --output results/agent-safety-guardian-latest.json \
  --register results/agent-risk-register.json
```

- `--trend-window-hours <n>`: sliding window for trend stats (default: 168h)
- `--escalate-repeat-threshold <n>`: escalate warning -> high when same code repeats >= n within trend window (default: 3)
- `--history-limit <n>`: cap stored risk records in register

## 5) Severity model (current)

- `critical`: immediate trust/reliability threats
- `high`: must-fix before wider rollout
- `medium`: action recommended, non-blocking
- `warning`: observability/coverage/process attention

Current mapping includes:

- `binary_forge_missing` -> `medium`
- `support_bundle_failed` -> `high`
- `proof_gates_failed` -> `high`
- `patrol_max_fail_violated` -> `critical`
- `patrol_recent_pass_violated` -> `critical`
- `patrol_min_total_violated` -> `warning` (may be escalated by repeat rule)
- `patrol_strict_no_match` -> `warning` (may be escalated by repeat rule)

## 6) Artifacts

By default, outputs go to `results/`:

- `agent-safety-guardian-latest.json` (full-chain run report)
- `agent-risk-register.json` (persistent risk register)

Report sections:

- `stageChecks`
- `doctor`
- `patrol.batchSummary / patrol.alertSummary`
- `riskAssessment`
- `predictiveDefense`:
  - `trendSummary` (window stats)
  - `escalations` (applied warning->high upgrades)
  - `signals` (high-frequency risk code indicators)
  - `nextActions`

## 7) Suggested operations rhythm

- **Hourly/Daily monitoring**: `balanced`
- **Release gate**: `strict`
- **Cold-start accumulation**: `lenient`

Cron example (UTC hourly):

```bash
0 * * * * cd /path/to/repo && ./scripts/agent-safety-guardian.sh --profile balanced
```

## 8) Predictive defense usage (v0.3)

`agent-risk-register.json` and guardian report are designed for:

- trend analysis (`recentByCode`)
- repeat-risk escalation automation
- risk heat-index tracking (time-decayed weighted score)
- automatic patrol-profile recommendation (`lenient|balanced|strict`)
- future anomaly/prediction model training

v0.2 adds:

- **time-decayed risk scoring** (`predictiveDefense.decayModel`)
  - recent risks weigh more than older risks inside trend window
  - per-risk severity mapped to weights (`warning/medium/high/critical`)
- **risk heat index** (`predictiveDefense.riskHeatIndex`)
  - normalized 0-100 score for current operational pressure
- **auto patrol profile recommendation** (`predictiveDefense.recommendedProfile`)
  - `strict` for high heat or critical trend pattern
  - `balanced` for medium heat
  - `lenient` for low heat

v0.3 adds:

- **optional auto-execution mode for patrol profile switching**
  - `--auto-apply-recommendation`: allow guardian to auto-switch next run profile
  - `--auto-confirm-runs <n>`: require repeated recommendation hits before switching
  - `--auto-state <path>`: persistent state for recommendation streak and applied profile
- **audit trail for profile automation**
  - `predictiveDefense.autoTuning` in report
  - includes `pendingStreak`, `activeProfile`, `nextRunProfile`, `lastDecision`, and switch metadata

Recommended next step:

- add a weekly trend reporter that converts `trendSummary + escalations + riskHeatIndex + profileRecommendation` into ticket-ready remediation plans.
