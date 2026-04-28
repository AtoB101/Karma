#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"

PROFILE="balanced"
PROFILE_EXPLICIT=0
FROM_ENV=0
SKIP_PROOF_GATES=0
SKIP_PATROL=0
SKIP_SUPPORT_BUNDLE=0
OUTPUT_PATH="${RESULTS_DIR}/agent-safety-guardian-latest.json"
REGISTER_PATH="${RESULTS_DIR}/agent-risk-register.json"
AUTO_STATE_PATH="${RESULTS_DIR}/agent-safety-autotune-state.json"
HISTORY_LIMIT=200
TREND_WINDOW_HOURS=168
ESCALATE_REPEAT_THRESHOLD=3
DECAY_HALF_LIFE_HOURS=48
AUTO_APPLY_RECOMMENDATION=0
AUTO_CONFIRM_RUNS=2
ALERT_THRESHOLD="high"
ALARM_OUTPUT_PATH="${RESULTS_DIR}/agent-safety-alarm-latest.json"
FAIL_ON_ALARM=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/agent-safety-guardian.sh [--profile <strict|balanced|lenient>] [--from-env] [--skip-proof-gates] [--skip-patrol] [--skip-support-bundle] [--output <path>] [--register <path>] [--auto-state <path>] [--history-limit <n>] [--trend-window-hours <n>] [--escalate-repeat-threshold <n>] [--decay-half-life-hours <n>] [--auto-apply-recommendation] [--auto-confirm-runs <n>] [--alert-threshold <warning|medium|high|critical>] [--alarm-output <path>] [--fail-on-alarm]

Description:
  Runs an end-to-end internal safety self-check pipeline and generates:
    1) a full-chain safety report
    2) a persistent risk register for trend analysis and predictive defense

Options:
  --profile <name>       Patrol profile: strict|balanced|lenient (default: balanced)
  --from-env             Load .env for doctor/preflight where applicable
  --skip-proof-gates     Skip ci-proof-gates stage
  --skip-patrol          Skip proof-patrol stage
  --skip-support-bundle  Skip support-bundle generation stage
  --output <path>        Safety report path (default: results/agent-safety-guardian-latest.json)
  --register <path>      Persistent risk register path (default: results/agent-risk-register.json)
  --auto-state <path>    Auto-tuning state file for profile switching (default: results/agent-safety-autotune-state.json)
  --history-limit <n>    Keep latest N risk records in register (default: 200)
  --trend-window-hours <n>        Window for trend stats and repeat checks (default: 168)
  --escalate-repeat-threshold <n> Escalate warning->high when same risk code repeats >= n times in trend window (default: 3)
  --decay-half-life-hours <n>     Half-life for time-decay risk scoring/heat index (default: 48)
  --auto-apply-recommendation     Enable automatic profile switch via persistent state
  --auto-confirm-runs <n>         Required consecutive recommendation runs before switching profile (default: 2)
  --alert-threshold <level>       Trigger alarms at/above level: warning|medium|high|critical (default: high)
  --alarm-output <path>           Alarm artifact output path (default: results/agent-safety-alarm-latest.json)
  --fail-on-alarm                 Exit non-zero when alarms are triggered
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -lt 2 ]] && { echo "Error: --profile requires a value"; exit 1; }
      PROFILE="$2"
      PROFILE_EXPLICIT=1
      if [[ "$PROFILE" != "strict" && "$PROFILE" != "balanced" && "$PROFILE" != "lenient" ]]; then
        echo "Error: --profile must be one of strict|balanced|lenient"
        exit 1
      fi
      shift 2
      ;;
    --from-env)
      FROM_ENV=1
      shift
      ;;
    --skip-proof-gates)
      SKIP_PROOF_GATES=1
      shift
      ;;
    --skip-patrol)
      SKIP_PATROL=1
      shift
      ;;
    --skip-support-bundle)
      SKIP_SUPPORT_BUNDLE=1
      shift
      ;;
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --register)
      [[ $# -lt 2 ]] && { echo "Error: --register requires a value"; exit 1; }
      REGISTER_PATH="$2"
      shift 2
      ;;
    --auto-state)
      [[ $# -lt 2 ]] && { echo "Error: --auto-state requires a value"; exit 1; }
      AUTO_STATE_PATH="$2"
      shift 2
      ;;
    --history-limit)
      [[ $# -lt 2 ]] && { echo "Error: --history-limit requires a value"; exit 1; }
      HISTORY_LIMIT="$2"
      if ! [[ "$HISTORY_LIMIT" =~ ^[0-9]+$ ]]; then
        echo "Error: --history-limit must be a non-negative integer"
        exit 1
      fi
      shift 2
      ;;
    --trend-window-hours)
      [[ $# -lt 2 ]] && { echo "Error: --trend-window-hours requires a value"; exit 1; }
      TREND_WINDOW_HOURS="$2"
      if ! [[ "$TREND_WINDOW_HOURS" =~ ^[0-9]+$ ]]; then
        echo "Error: --trend-window-hours must be a non-negative integer"
        exit 1
      fi
      shift 2
      ;;
    --escalate-repeat-threshold)
      [[ $# -lt 2 ]] && { echo "Error: --escalate-repeat-threshold requires a value"; exit 1; }
      ESCALATE_REPEAT_THRESHOLD="$2"
      if ! [[ "$ESCALATE_REPEAT_THRESHOLD" =~ ^[0-9]+$ ]]; then
        echo "Error: --escalate-repeat-threshold must be a non-negative integer"
        exit 1
      fi
      shift 2
      ;;
    --decay-half-life-hours)
      [[ $# -lt 2 ]] && { echo "Error: --decay-half-life-hours requires a value"; exit 1; }
      DECAY_HALF_LIFE_HOURS="$2"
      if ! [[ "$DECAY_HALF_LIFE_HOURS" =~ ^[0-9]+$ ]]; then
        echo "Error: --decay-half-life-hours must be a non-negative integer"
        exit 1
      fi
      shift 2
      ;;
    --auto-apply-recommendation)
      AUTO_APPLY_RECOMMENDATION=1
      shift
      ;;
    --auto-confirm-runs)
      [[ $# -lt 2 ]] && { echo "Error: --auto-confirm-runs requires a value"; exit 1; }
      AUTO_CONFIRM_RUNS="$2"
      if ! [[ "$AUTO_CONFIRM_RUNS" =~ ^[0-9]+$ ]]; then
        echo "Error: --auto-confirm-runs must be a non-negative integer"
        exit 1
      fi
      shift 2
      ;;
    --alert-threshold)
      [[ $# -lt 2 ]] && { echo "Error: --alert-threshold requires a value"; exit 1; }
      ALERT_THRESHOLD="$2"
      if [[ "$ALERT_THRESHOLD" != "warning" && "$ALERT_THRESHOLD" != "medium" && "$ALERT_THRESHOLD" != "high" && "$ALERT_THRESHOLD" != "critical" ]]; then
        echo "Error: --alert-threshold must be one of warning|medium|high|critical"
        exit 1
      fi
      shift 2
      ;;
    --alarm-output)
      [[ $# -lt 2 ]] && { echo "Error: --alarm-output requires a value"; exit 1; }
      ALARM_OUTPUT_PATH="$2"
      shift 2
      ;;
    --fail-on-alarm)
      FAIL_ON_ALARM=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ "$OUTPUT_PATH" != /* ]]; then
  OUTPUT_PATH="${ROOT_DIR}/${OUTPUT_PATH}"
fi
if [[ "$REGISTER_PATH" != /* ]]; then
  REGISTER_PATH="${ROOT_DIR}/${REGISTER_PATH}"
fi
if [[ "$AUTO_STATE_PATH" != /* ]]; then
  AUTO_STATE_PATH="${ROOT_DIR}/${AUTO_STATE_PATH}"
fi
if [[ "$ALARM_OUTPUT_PATH" != /* ]]; then
  ALARM_OUTPUT_PATH="${ROOT_DIR}/${ALARM_OUTPUT_PATH}"
fi
mkdir -p "$RESULTS_DIR" "$(dirname "$OUTPUT_PATH")" "$(dirname "$REGISTER_PATH")" "$(dirname "$AUTO_STATE_PATH")" "$(dirname "$ALARM_OUTPUT_PATH")"

if [[ "$AUTO_APPLY_RECOMMENDATION" -eq 1 && "$PROFILE_EXPLICIT" -eq 0 && -f "$AUTO_STATE_PATH" ]]; then
  AUTO_PROFILE="$(python3 - "$AUTO_STATE_PATH" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)
profile = data.get("activeProfile")
print(profile if profile in {"strict", "balanced", "lenient"} else "")
PY
)"
  if [[ -n "$AUTO_PROFILE" ]]; then
    PROFILE="$AUTO_PROFILE"
  fi
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DOCTOR_JSON="${TMP_DIR}/doctor.json"
PATROL_BATCH="${TMP_DIR}/patrol-batch.json"
PATROL_ALERT="${TMP_DIR}/patrol-alert.json"
PROOF_GATES_LOG="${TMP_DIR}/proof-gates.log"
SUPPORT_BUNDLE_LOG="${TMP_DIR}/support-bundle.log"

echo "==> [1/4] doctor self-check"
DOCTOR_ARGS=(--port 8790 --format json --output "$DOCTOR_JSON")
if [[ "$FROM_ENV" -eq 1 ]]; then
  DOCTOR_ARGS=(--from-env "${DOCTOR_ARGS[@]}")
fi
./scripts/doctor.sh "${DOCTOR_ARGS[@]}" >/dev/null

SUPPORT_BUNDLE_EXIT=0
if [[ "$SKIP_SUPPORT_BUNDLE" -eq 0 ]]; then
  echo "==> [2/4] support bundle integrity snapshot"
  set +e
  ./scripts/support-bundle.sh --port 8790 --operator "safety-guardian" --reviewer "safety-guardian" --ticket "SAFETY-${STAMP}" >"$SUPPORT_BUNDLE_LOG" 2>&1
  SUPPORT_BUNDLE_EXIT=$?
  set -e
fi

PROOF_GATES_EXIT=0
if [[ "$SKIP_PROOF_GATES" -eq 0 ]]; then
  echo "==> [3/4] proof/evidence CI-style gates"
  set +e
  ./scripts/ci-proof-gates.sh --format json >"$PROOF_GATES_LOG" 2>&1
  PROOF_GATES_EXIT=$?
  set -e
fi

PATROL_EXIT=0
if [[ "$SKIP_PATROL" -eq 0 ]]; then
  echo "==> [4/4] patrol risk scan (${PROFILE})"
  set +e
  ./scripts/proof-patrol.sh \
    --profile "$PROFILE" \
    --batch-output "$PATROL_BATCH" \
    --alert-output "$PATROL_ALERT" \
    --no-summary
  PATROL_EXIT=$?
  set -e
fi

python3 - "$DOCTOR_JSON" "$PATROL_BATCH" "$PATROL_ALERT" "$REGISTER_PATH" "$OUTPUT_PATH" "$ALARM_OUTPUT_PATH" "$AUTO_STATE_PATH" "$PROFILE" "$STAMP" "$PROOF_GATES_EXIT" "$PATROL_EXIT" "$SUPPORT_BUNDLE_EXIT" "$HISTORY_LIMIT" "$SKIP_PROOF_GATES" "$SKIP_PATROL" "$SKIP_SUPPORT_BUNDLE" "$TREND_WINDOW_HOURS" "$ESCALATE_REPEAT_THRESHOLD" "$DECAY_HALF_LIFE_HOURS" "$AUTO_APPLY_RECOMMENDATION" "$AUTO_CONFIRM_RUNS" "$ALERT_THRESHOLD" "$FAIL_ON_ALARM" <<'PY'
import datetime as dt
import json
import pathlib
import sys
import uuid

doctor_path = pathlib.Path(sys.argv[1])
patrol_batch_path = pathlib.Path(sys.argv[2])
patrol_alert_path = pathlib.Path(sys.argv[3])
register_path = pathlib.Path(sys.argv[4])
output_path = pathlib.Path(sys.argv[5])
alarm_output_path = pathlib.Path(sys.argv[6])
auto_state_path = pathlib.Path(sys.argv[7])
profile = sys.argv[8]
stamp = sys.argv[9]
proof_gates_exit = int(sys.argv[10])
patrol_exit = int(sys.argv[11])
support_bundle_exit = int(sys.argv[12])
history_limit = int(sys.argv[13])
skip_proof_gates = int(sys.argv[14])
skip_patrol = int(sys.argv[15])
skip_support_bundle = int(sys.argv[16])
trend_window_hours = int(sys.argv[17])
escalate_repeat_threshold = int(sys.argv[18])
decay_half_life_hours = int(sys.argv[19]) if len(sys.argv) > 19 else 48
auto_apply_recommendation = int(sys.argv[20]) if len(sys.argv) > 20 else 0
auto_confirm_runs = int(sys.argv[21]) if len(sys.argv) > 21 else 2
alert_threshold = (sys.argv[22] if len(sys.argv) > 22 else "high").lower()
fail_on_alarm = int(sys.argv[23]) if len(sys.argv) > 23 else 0
decision_history_limit = 200

now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
now_dt = dt.datetime.now(dt.timezone.utc)
doctor = json.loads(doctor_path.read_text(encoding="utf-8"))

def parse_iso8601(value):
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)

patrol_batch = None
if patrol_batch_path.exists():
    patrol_batch = json.loads(patrol_batch_path.read_text(encoding="utf-8"))
patrol_alert = None
if patrol_alert_path.exists():
    patrol_alert = json.loads(patrol_alert_path.read_text(encoding="utf-8"))

def risk(code, title, severity, category, detail, source):
    return {
        "riskId": f"risk-{uuid.uuid4()}",
        "detectedAt": now_iso,
        "category": category,
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "source": source,
        "status": "open",
        "tags": ["agent-safety-guardian", f"profile:{profile}"],
    }

risks = []

checks = {
    "doctor": "pass",
    "supportBundle": "pass" if support_bundle_exit == 0 else "fail",
    "proofGates": "skipped" if skip_proof_gates else ("pass" if proof_gates_exit == 0 else "fail"),
    "patrol": "skipped" if skip_patrol else ("pass" if patrol_exit == 0 else "fail"),
}

binaries = (doctor.get("binaries") or {})
if binaries.get("forge") != "yes":
    risks.append(
        risk(
            "binary_forge_missing",
            "Forge binary missing",
            "medium",
            "environment",
            "Foundry forge is unavailable; contract-level deep checks may be incomplete.",
            "doctor.binaries.forge",
        )
    )

if checks["supportBundle"] == "fail":
    risks.append(
        risk(
            "support_bundle_failed",
            "Support bundle generation failed",
            "high",
            "pipeline",
            "Support bundle stage failed; integrity snapshot may be stale.",
            "support-bundle.sh",
        )
    )

if checks["proofGates"] == "fail":
    risks.append(
        risk(
            "proof_gates_failed",
            "Proof/evidence CI gates failed",
            "high",
            "integrity",
            "CI-style proof/evidence gate returned non-zero exit.",
            "ci-proof-gates.sh",
        )
    )

if patrol_batch:
    policy = patrol_batch.get("policy", {}) or {}
    if policy.get("maxFailViolated"):
        risks.append(
            risk(
                "patrol_max_fail_violated",
                "Proof patrol max-fail policy violated",
                "critical",
                "integrity",
                "Patrol failures exceeded the configured max-fail threshold.",
                "proof-patrol.policy.maxFailViolated",
            )
        )
    if policy.get("recentPassViolated"):
        risks.append(
            risk(
                "patrol_recent_pass_violated",
                "No recent passing patrol within required window",
                "critical",
                "reliability",
                "Latest pass is older than required recency threshold.",
                "proof-patrol.policy.recentPassViolated",
            )
        )
    if policy.get("minTotalViolated"):
        risks.append(
            risk(
                "patrol_min_total_violated",
                "Patrol sample size below minimum",
                "warning",
                "coverage",
                "Matched support bundles are below min-total threshold.",
                "proof-patrol.policy.minTotalViolated",
            )
        )
    if policy.get("strictNoMatchViolated"):
        risks.append(
            risk(
                "patrol_strict_no_match",
                "Strict mode no-match violation",
                "warning",
                "coverage",
                "Strict policy requires at least one matched bundle in scope.",
                "proof-patrol.policy.strictNoMatchViolated",
            )
        )

if patrol_alert and patrol_alert.get("status") == "fail" and not risks:
    risks.append(
        risk(
            "patrol_failed_generic",
            "Patrol failed without mapped policy code",
            "high",
            "integrity",
            "Patrol failed; inspect reasonSummary for detailed causes.",
            "proof-patrol.alert",
        )
    )

existing = {"version": "agent-risk-register-v1", "updatedAt": now_iso, "records": []}
if register_path.exists():
    try:
        existing = json.loads(register_path.read_text(encoding="utf-8"))
    except Exception:
        pass

records = list(existing.get("records") or [])

# Predictive defense baseline:
# 1) compute recent frequency by code inside trend window
# 2) escalate fresh warning risks when the same code repeatedly appears
trend_start_dt = now_dt - dt.timedelta(hours=trend_window_hours)
recent_code_freq = {}
for row in records:
    code = row.get("code") or "unknown"
    detected_at_dt = parse_iso8601(row.get("detectedAt"))
    if detected_at_dt and detected_at_dt >= trend_start_dt:
        recent_code_freq[code] = recent_code_freq.get(code, 0) + 1

for row in risks:
    if row.get("severity") != "warning":
        continue
    if escalate_repeat_threshold <= 0:
        continue
    code = row.get("code") or "unknown"
    repeated_count = recent_code_freq.get(code, 0) + 1
    if repeated_count >= escalate_repeat_threshold:
        from_severity = row["severity"]
        row["severity"] = "high"
        row["escalated"] = True
        row["detail"] = (
            f"{row.get('detail')} Escalated to high: code '{code}' repeated "
            f"{repeated_count} times within {trend_window_hours}h window."
        )
        row["escalation"] = {
            "rule": "warning_to_high_on_repeat",
            "fromSeverity": from_severity,
            "toSeverity": "high",
            "threshold": escalate_repeat_threshold,
            "windowHours": trend_window_hours,
            "repeatCount": repeated_count,
        }

records.extend(risks)
records = records[-history_limit:]

code_freq = {}
for row in records:
    c = row.get("code") or "unknown"
    code_freq[c] = code_freq.get(c, 0) + 1

recent_code_freq = {}
for row in records:
    code = row.get("code") or "unknown"
    detected_at_dt = parse_iso8601(row.get("detectedAt"))
    if detected_at_dt and detected_at_dt >= trend_start_dt:
        recent_code_freq[code] = recent_code_freq.get(code, 0) + 1

predictions = []
for code, freq in sorted(recent_code_freq.items(), key=lambda x: x[1], reverse=True)[:5]:
    if freq < 2:
        continue
    level = "high" if freq >= max(4, escalate_repeat_threshold) else "medium"
    predictions.append(
        {
            "code": code,
            "frequency": freq,
            "windowHours": trend_window_hours,
            "predictedEscalation": level,
            "recommendedDefense": "tighten patrol profile and increase check frequency for this risk code",
        }
    )

severity_weight = {
    "critical": 1.00,
    "high": 0.70,
    "medium": 0.40,
    "warning": 0.20,
}

half_life_hours = max(1, decay_half_life_hours)
decayed_score_by_code = {}
decayed_total_score = 0.0
recent_critical = 0
for row in records:
    detected_at_dt = parse_iso8601(row.get("detectedAt"))
    if not detected_at_dt or detected_at_dt < trend_start_dt:
        continue
    age_hours = max(0.0, (now_dt - detected_at_dt).total_seconds() / 3600.0)
    decay_factor = 0.5 ** (age_hours / half_life_hours)
    sev = (row.get("severity") or "warning").lower()
    weight = severity_weight.get(sev, 0.20)
    contribution = weight * decay_factor
    code = row.get("code") or "unknown"
    decayed_score_by_code[code] = decayed_score_by_code.get(code, 0.0) + contribution
    decayed_total_score += contribution
    if sev == "critical":
        recent_critical += 1

heat_index = min(100.0, round(decayed_total_score * 25.0, 2))
escalation_count = sum(1 for r in risks if r.get("escalated"))
if recent_critical > 0 or heat_index >= 70.0 or escalation_count > 0:
    recommended_profile = "strict"
elif heat_index >= 35.0:
    recommended_profile = "balanced"
else:
    recommended_profile = "lenient"

if recommended_profile == profile:
    recommendation_reason = "current patrol profile already matches calculated risk heat"
else:
    recommendation_reason = (
        f"switch profile from {profile} to {recommended_profile} "
        f"(heatIndex={heat_index}, recentCritical={recent_critical}, escalations={escalation_count})"
    )

severity_rank = {"warning": 1, "medium": 2, "high": 3, "critical": 4}
alert_rank = severity_rank.get(alert_threshold, 3)

def rule_finding(rule_id, severity, title, exploit_path, detail, mitigation):
    return {
        "ruleId": rule_id,
        "severity": severity,
        "title": title,
        "exploitPath": exploit_path,
        "detail": detail,
        "mitigation": mitigation,
    }

rule_findings = []
if checks["proofGates"] == "skipped":
    rule_findings.append(
        rule_finding(
            "rule-gate-bypass-proof-gates-skipped",
            "critical",
            "Proof gate is bypassed",
            "attacker waits for maintenance/debug runs and submits malformed evidence",
            "ci-proof-gates stage is skipped, removing schema and policy validation barrier.",
            "enforce proof gates in all non-debug runs and trigger pager alert when skipped",
        )
    )
if checks["patrol"] == "skipped":
    rule_findings.append(
        rule_finding(
            "rule-gate-bypass-patrol-skipped",
            "high",
            "Patrol stage is bypassed",
            "attacker exploits stale bundles without continuous integrity patrol",
            "proof-patrol stage is skipped, reducing rolling integrity coverage.",
            "require patrol for production validation windows and add no-patrol SLA alarms",
        )
    )
if patrol_batch:
    policy = patrol_batch.get("policy", {}) or {}
    if policy.get("minTotalViolated"):
        rule_findings.append(
            rule_finding(
                "rule-coverage-min-total",
                "high",
                "Coverage floor violated",
                "attacker times malicious activity when sample volume is below threshold",
                "min-total guardrail failed; observed sample set is insufficient for confidence.",
                "raise sampling cadence and block go-live when min-total stays violated",
            )
        )
    if policy.get("recentPassViolated"):
        rule_findings.append(
            rule_finding(
                "rule-freshness-recent-pass",
                "critical",
                "Freshness guard violated",
                "attacker reuses stale proof baseline while recent failures stay unobserved",
                "recent-pass policy indicates no fresh successful patrol in required window.",
                "escalate to strict profile and require immediate fresh-pass recovery",
            )
        )
auto_state = {
    "version": "agent-safety-autotune-v1",
    "updatedAt": now_iso,
    "activeProfile": profile,
    "pendingRecommendation": recommended_profile,
    "pendingStreak": 0,
    "confirmRuns": auto_confirm_runs,
    "lastAppliedAt": None,
    "lastDecision": "manual_mode",
    "decisionHistory": [],
}
if auto_state_path.exists():
    try:
        loaded_auto_state = json.loads(auto_state_path.read_text(encoding="utf-8"))
        if isinstance(loaded_auto_state, dict):
            auto_state.update(loaded_auto_state)
    except Exception:
        pass

auto_state["updatedAt"] = now_iso
auto_state["confirmRuns"] = auto_confirm_runs
auto_state["activeProfile"] = profile
decision_history = list(auto_state.get("decisionHistory") or [])
decision_event = {
    "at": now_iso,
    "fromProfile": profile,
    "recommendedProfile": recommended_profile,
    "decision": "manual_mode",
    "pendingStreak": int(auto_state.get("pendingStreak", 0)),
}

if auto_apply_recommendation:
    if recommended_profile != profile:
        if auto_state.get("pendingRecommendation") == recommended_profile:
            auto_state["pendingStreak"] = int(auto_state.get("pendingStreak", 0)) + 1
        else:
            auto_state["pendingRecommendation"] = recommended_profile
            auto_state["pendingStreak"] = 1
        if int(auto_state.get("pendingStreak", 0)) >= max(1, auto_confirm_runs):
            auto_state["activeProfile"] = recommended_profile
            auto_state["lastAppliedAt"] = now_iso
            auto_state["lastDecision"] = "switched"
            auto_state["pendingStreak"] = 0
            decision_event["decision"] = "switched"
            decision_event["toProfile"] = recommended_profile
        else:
            auto_state["lastDecision"] = "awaiting_confirmation"
            decision_event["decision"] = "awaiting_confirmation"
            decision_event["toProfile"] = profile
    else:
        auto_state["pendingRecommendation"] = recommended_profile
        auto_state["pendingStreak"] = 0
        auto_state["lastDecision"] = "no_change"

if auto_apply_recommendation and auto_state.get("lastDecision") == "awaiting_confirmation":
    rule_findings.append(
        rule_finding(
            "rule-autotune-confirmation-window",
            "medium",
            "Auto-tuning confirmation window open",
            "attacker exploits interim window before stricter profile activates",
            "recommendation is pending and has not reached confirmation threshold yet.",
            "reduce confirm runs during high-risk windows or force strict override",
        )
    )
if auto_apply_recommendation and auto_state.get("activeProfile") == "lenient" and recommended_profile == "strict":
    rule_findings.append(
        rule_finding(
            "rule-posture-mismatch-lenient-vs-strict",
            "high",
            "Active posture mismatches risk recommendation",
            "attacker operates during low-friction controls despite high-risk signals",
            "active profile remains lenient while model recommends strict posture.",
            "force immediate strict profile and open incident ticket",
        )
    )

alarms = []
for finding in rule_findings:
    if severity_rank.get(finding.get("severity", "warning"), 1) >= alert_rank:
        alarms.append(
            {
                "kind": "rule_vulnerability",
                "ruleId": finding["ruleId"],
                "severity": finding["severity"],
                "title": finding["title"],
                "exploitPath": finding["exploitPath"],
                "detail": finding["detail"],
                "mitigation": finding["mitigation"],
            }
        )

for r in risks:
    if severity_rank.get(r.get("severity", "warning"), 1) >= alert_rank:
        alarms.append(
            {
                "kind": "operational_risk",
                "ruleId": None,
                "severity": r.get("severity"),
                "title": r.get("title"),
                "exploitPath": None,
                "detail": r.get("detail"),
                "mitigation": "inspect guardian riskAssessment and apply profile/coverage hardening",
            }
        )
        decision_event["decision"] = "no_change"
        decision_event["toProfile"] = profile
else:
    decision_event["decision"] = "manual_mode"
    decision_event["toProfile"] = profile

decision_event["pendingStreak"] = int(auto_state.get("pendingStreak", 0))
decision_history.append(decision_event)
auto_state["decisionHistory"] = decision_history[-decision_history_limit:]

overall = "pass" if not risks else ("warning" if all(r["severity"] == "warning" for r in risks) else "fail")

report = {
    "reportVersion": "agent-safety-guardian-v1",
    "generatedAt": now_iso,
    "profile": profile,
    "stageChecks": checks,
    "doctor": {
        "repoRoot": doctor.get("repoRoot"),
        "gitBranch": doctor.get("gitBranch"),
        "binaries": doctor.get("binaries"),
        "environment": doctor.get("environment"),
        "preflight": ((doctor.get("checks") or {}).get("preflight")),
    },
    "patrol": {
        "batchSummary": patrol_batch,
        "alertSummary": patrol_alert,
    },
    "riskAssessment": {
        "overall": overall,
        "riskCount": len(risks),
        "bySeverity": {
            "critical": sum(1 for r in risks if r["severity"] == "critical"),
            "high": sum(1 for r in risks if r["severity"] == "high"),
            "medium": sum(1 for r in risks if r["severity"] == "medium"),
            "warning": sum(1 for r in risks if r["severity"] == "warning"),
        },
        "newRisks": risks,
    },
    "predictiveDefense": {
        "signals": predictions,
        "trendSummary": {
            "windowHours": trend_window_hours,
            "recentByCode": recent_code_freq,
            "recentTotal": sum(recent_code_freq.values()),
        },
        "timeDecayModel": {
            "halfLifeHours": half_life_hours,
            "severityWeight": severity_weight,
            "decayedScoreByCode": {k: round(v, 6) for k, v in decayed_score_by_code.items()},
            "decayedTotalScore": round(decayed_total_score, 6),
        },
        "riskHeatIndex": heat_index,
        "escalations": [
            {
                "code": r.get("code"),
                "fromSeverity": (r.get("escalation") or {}).get("fromSeverity"),
                "toSeverity": (r.get("escalation") or {}).get("toSeverity"),
                "repeatCount": (r.get("escalation") or {}).get("repeatCount"),
            }
            for r in risks
            if r.get("escalated")
        ],
        "profileRecommendation": {
            "current": profile,
            "recommended": recommended_profile,
            "reason": recommendation_reason,
        },
        "autoTuning": {
            "enabled": bool(auto_apply_recommendation),
            "confirmRuns": max(1, auto_confirm_runs),
            "statePath": str(auto_state_path),
            "activeProfile": auto_state.get("activeProfile"),
            "pendingRecommendation": auto_state.get("pendingRecommendation"),
            "pendingStreak": auto_state.get("pendingStreak"),
            "lastDecision": auto_state.get("lastDecision"),
            "lastAppliedAt": auto_state.get("lastAppliedAt"),
            "decisionHistorySize": len(auto_state.get("decisionHistory") or []),
            "latestDecision": (auto_state.get("decisionHistory") or [None])[-1],
            "nextRunProfile": auto_state.get("activeProfile") if auto_apply_recommendation else profile,
        },
        "ruleRiskAnalysis": {
            "findingCount": len(rule_findings),
            "findings": rule_findings,
        },
        "windowHours": trend_window_hours,
        "repeatEscalationThreshold": escalate_repeat_threshold,
        "nextActions": [
            "schedule guardian run every 1-6 hours (according to profile strictness)",
            "treat repeated risk codes as leading indicators and enforce targeted remediation",
            "link risk register to alert routing (chatops/on-call) for closed-loop handling",
        ],
    },
}

alarm_payload = {
    "version": "agent-safety-alarm-v1",
    "generatedAt": now_iso,
    "profile": profile,
    "alertThreshold": alert_threshold,
    "alarmCount": len(alarms),
    "alarms": alarms,
    "riskHeatIndex": heat_index,
    "recommendedProfile": recommended_profile,
}

register_payload = {
    "version": "agent-risk-register-v1",
    "updatedAt": now_iso,
    "profile": profile,
    "summary": {
        "totalRecords": len(records),
        "trendWindowHours": trend_window_hours,
        "recentByCode": recent_code_freq,
        "riskHeatIndex": heat_index,
        "recommendedProfile": recommended_profile,
    },
    "records": records,
}

register_path.write_text(json.dumps(register_payload, indent=2) + "\n", encoding="utf-8")
auto_state_path.write_text(json.dumps(auto_state, indent=2) + "\n", encoding="utf-8")
output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
alarm_output_path.write_text(json.dumps(alarm_payload, indent=2) + "\n", encoding="utf-8")

print(f"Safety report written: {output_path}")
print(f"Risk register updated: {register_path}")
print(f"Alarm artifact written: {alarm_output_path}")
print(f"Overall: {overall} (new risks: {len(risks)})")
if fail_on_alarm and len(alarms) > 0:
    raise SystemExit(2)
PY
