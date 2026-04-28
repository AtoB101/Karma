#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"

PROFILE="balanced"
FROM_ENV=0
SKIP_PROOF_GATES=0
SKIP_PATROL=0
SKIP_SUPPORT_BUNDLE=0
OUTPUT_PATH="${RESULTS_DIR}/agent-safety-guardian-latest.json"
REGISTER_PATH="${RESULTS_DIR}/agent-risk-register.json"
HISTORY_LIMIT=200
TREND_WINDOW_HOURS=168
ESCALATE_REPEAT_THRESHOLD=3

usage() {
  cat <<'EOF'
Usage:
  ./scripts/agent-safety-guardian.sh [--profile <strict|balanced|lenient>] [--from-env] [--skip-proof-gates] [--skip-patrol] [--skip-support-bundle] [--output <path>] [--register <path>] [--history-limit <n>] [--trend-window-hours <n>] [--escalate-repeat-threshold <n>]

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
  --history-limit <n>    Keep latest N risk records in register (default: 200)
  --trend-window-hours <n>        Window for trend stats and repeat checks (default: 168)
  --escalate-repeat-threshold <n> Escalate warning->high when same risk code repeats >= n times in trend window (default: 3)
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -lt 2 ]] && { echo "Error: --profile requires a value"; exit 1; }
      PROFILE="$2"
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
mkdir -p "$RESULTS_DIR" "$(dirname "$OUTPUT_PATH")" "$(dirname "$REGISTER_PATH")"

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

python3 - "$DOCTOR_JSON" "$PATROL_BATCH" "$PATROL_ALERT" "$REGISTER_PATH" "$OUTPUT_PATH" "$PROFILE" "$STAMP" "$PROOF_GATES_EXIT" "$PATROL_EXIT" "$SUPPORT_BUNDLE_EXIT" "$HISTORY_LIMIT" "$SKIP_PROOF_GATES" "$SKIP_PATROL" "$SKIP_SUPPORT_BUNDLE" "$TREND_WINDOW_HOURS" "$ESCALATE_REPEAT_THRESHOLD" <<'PY'
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
profile = sys.argv[6]
stamp = sys.argv[7]
proof_gates_exit = int(sys.argv[8])
patrol_exit = int(sys.argv[9])
support_bundle_exit = int(sys.argv[10])
history_limit = int(sys.argv[11])
skip_proof_gates = int(sys.argv[12])
skip_patrol = int(sys.argv[13])
skip_support_bundle = int(sys.argv[14])
trend_window_hours = int(sys.argv[15])
escalate_repeat_threshold = int(sys.argv[16])

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
        row["severity"] = "high"
        row["detail"] = (
            f"{row.get('detail')} Escalated to high: code '{code}' repeated "
            f"{repeated_count} times within {trend_window_hours}h window."
        )
        row["escalation"] = {
            "rule": "warning_to_high_on_repeat",
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
        "windowHours": trend_window_hours,
        "repeatEscalationThreshold": escalate_repeat_threshold,
        "nextActions": [
            "schedule guardian run every 1-6 hours (according to profile strictness)",
            "treat repeated risk codes as leading indicators and enforce targeted remediation",
            "link risk register to alert routing (chatops/on-call) for closed-loop handling",
        ],
    },
}

register_payload = {
    "version": "agent-risk-register-v1",
    "updatedAt": now_iso,
    "profile": profile,
    "summary": {
        "totalRecords": len(records),
        "trendWindowHours": trend_window_hours,
        "recentByCode": recent_code_freq,
    },
    "records": records,
}

register_path.write_text(json.dumps(register_payload, indent=2) + "\n", encoding="utf-8")
output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

print(f"Safety report written: {output_path}")
print(f"Risk register updated: {register_path}")
print(f"Overall: {overall} (new risks: {len(risks)})")
PY
