#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
OUTPUT_PATH="${RESULTS_DIR}/rule-gap-adversarial-sim-latest.json"
FORMAT="json"
PROFILE="balanced"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/rule-gap-adversarial-sim.sh [--output <path>] [--format <json|text>] [--profile <strict|balanced|lenient>]

Description:
  Runs adversarial rule-gap simulations that mimic "rule exploitation without explicit rule breaking",
  then emits machine-readable findings for guardian/risk operations.

Options:
  --output <path>   Output report path (default: results/rule-gap-adversarial-sim-latest.json)
  --format <fmt>    Output format: json (default) or text
  --profile <name>  Control posture profile: strict|balanced|lenient (default: balanced)
  -h, --help        Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --format)
      [[ $# -lt 2 ]] && { echo "Error: --format requires a value"; exit 1; }
      FORMAT="$2"
      if [[ "$FORMAT" != "json" && "$FORMAT" != "text" ]]; then
        echo "Error: --format must be json or text"
        exit 1
      fi
      shift 2
      ;;
    --profile)
      [[ $# -lt 2 ]] && { echo "Error: --profile requires a value"; exit 1; }
      PROFILE="$2"
      if [[ "$PROFILE" != "strict" && "$PROFILE" != "balanced" && "$PROFILE" != "lenient" ]]; then
        echo "Error: --profile must be one of strict|balanced|lenient"
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
mkdir -p "$(dirname "$OUTPUT_PATH")"

python3 - "$OUTPUT_PATH" "$FORMAT" "$PROFILE" <<'PY'
import datetime as dt
import json
import pathlib
import sys

output_path = pathlib.Path(sys.argv[1])
fmt = sys.argv[2]
profile = sys.argv[3]

now = dt.datetime.now(dt.timezone.utc)

def clamp(v, low=0.0, high=100.0):
    return max(low, min(high, v))

def control_strength():
    if profile == "strict":
        return {
            "burstThrottle": 0.92,
            "windowCapTightening": 0.90,
            "autoEscalation": 0.85,
        }
    if profile == "lenient":
        return {
            "burstThrottle": 0.30,
            "windowCapTightening": 0.25,
            "autoEscalation": 0.20,
        }
    return {
        "burstThrottle": 0.65,
        "windowCapTightening": 0.60,
        "autoEscalation": 0.55,
    }

def residual_score(raw_score, factors):
    # Convert control factors into mitigation points (max ~70% reduction).
    mitigation_ratio = clamp(sum(factors) / (len(factors) * 1.0), 0.0, 1.0) * 0.70
    return clamp(raw_score * (1.0 - mitigation_ratio))

def scenario_policy_edge_exhaustion(controls):
    # 24 near-limit operations all "valid", creates cumulative exposure.
    ops = 24
    near_limit_ratio = 0.96
    burstiness = 0.82
    raw_score = clamp(ops * 2.2 + near_limit_ratio * 25 + burstiness * 20)
    score = residual_score(raw_score, [controls["burstThrottle"], controls["windowCapTightening"]])
    severity = "critical" if score >= 80 else ("high" if score >= 60 else ("medium" if score >= 35 else "warning"))
    return {
        "id": "sim-policy-edge-exhaustion",
        "title": "Policy edge exhaustion (threshold grinding)",
        "description": "Attacker repeatedly stays just below policy thresholds to maximize extraction.",
        "inputs": {
            "nearLimitOps": ops,
            "nearLimitRatio": near_limit_ratio,
            "burstiness": burstiness,
        },
        "result": {
            "rawScore": round(raw_score, 2),
            "score": round(score, 2),
            "severity": severity,
            "ruleGapKind": "policy_edge_exhaustion",
            "exploitable": score >= 50,
        },
        "mitigation": "Add burst/entropy-aware throttles and tighten per-window cumulative controls.",
    }

def scenario_observation_blind_window(controls):
    min_total_required = 3
    observed_total = 1
    no_match_windows = 4
    recency_hours = 30
    raw_score = clamp((min_total_required - observed_total) * 20 + no_match_windows * 8 + recency_hours * 0.6)
    score = residual_score(raw_score, [controls["windowCapTightening"], controls["autoEscalation"]])
    severity = "critical" if score >= 80 else ("high" if score >= 60 else ("medium" if score >= 35 else "warning"))
    return {
        "id": "sim-observation-blind-window",
        "title": "Observation blind-window abuse",
        "description": "Attacker acts in low-sample windows to avoid meaningful monitoring coverage.",
        "inputs": {
            "minTotalRequired": min_total_required,
            "observedTotal": observed_total,
            "strictNoMatchWindows": no_match_windows,
            "recentPassAgeHours": recency_hours,
        },
        "result": {
            "rawScore": round(raw_score, 2),
            "score": round(score, 2),
            "severity": severity,
            "ruleGapKind": "observation_blind_window",
            "exploitable": score >= 50,
        },
        "mitigation": "Fail-fast on persistent minTotal violations and increase patrol frequency.",
    }

def scenario_recommendation_execution_drift(controls):
    recommended = "strict"
    active = "lenient"
    pending_streak = 2
    confirm_runs = 3
    heat_index = 68.0
    raw_score = clamp((15 if recommended != active else 0) + pending_streak * 12 + (heat_index * 0.6))
    score = residual_score(raw_score, [controls["autoEscalation"], controls["burstThrottle"]])
    severity = "critical" if score >= 80 else ("high" if score >= 60 else ("medium" if score >= 35 else "warning"))
    return {
        "id": "sim-recommendation-execution-drift",
        "title": "Recommendation-execution drift",
        "description": "System recommends stricter posture but effective profile remains lax long enough to be abused.",
        "inputs": {
            "recommendedProfile": recommended,
            "activeProfile": active,
            "pendingStreak": pending_streak,
            "confirmRuns": confirm_runs,
            "riskHeatIndex": heat_index,
        },
        "result": {
            "rawScore": round(raw_score, 2),
            "score": round(score, 2),
            "severity": severity,
            "ruleGapKind": "recommendation_execution_drift",
            "exploitable": score >= 50,
        },
        "mitigation": "Lower confirmation threshold during elevated heat and allow emergency strict override.",
    }

controls = control_strength()
scenarios = [
    scenario_policy_edge_exhaustion(controls),
    scenario_observation_blind_window(controls),
    scenario_recommendation_execution_drift(controls),
]

sev_rank = {"warning": 1, "medium": 2, "high": 3, "critical": 4}
max_sev = "warning"
max_score = 0.0
for s in scenarios:
    if sev_rank[s["result"]["severity"]] > sev_rank[max_sev]:
        max_sev = s["result"]["severity"]
    max_score = max(max_score, s["result"]["score"])

report = {
    "version": "rule-gap-adversarial-sim-v1",
    "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "profile": profile,
    "controls": controls,
    "summary": {
        "scenarioCount": len(scenarios),
        "maxSeverity": max_sev,
        "maxScore": round(max_score, 2),
        "exploitableCount": sum(1 for s in scenarios if s["result"]["exploitable"]),
    },
    "scenarios": scenarios,
}

if fmt == "json":
    rendered = json.dumps(report, indent=2) + "\n"
else:
    lines = [
        f"generatedAt: {report['generatedAt']}",
        f"scenarioCount: {report['summary']['scenarioCount']}",
        f"maxSeverity: {report['summary']['maxSeverity']}",
        f"maxScore: {report['summary']['maxScore']}",
        f"exploitableCount: {report['summary']['exploitableCount']}",
        "",
    ]
    for s in report["scenarios"]:
        lines.append(f"- {s['id']} :: {s['result']['severity'].upper()} score={s['result']['score']}")
        lines.append(f"  kind: {s['result']['ruleGapKind']}")
        lines.append(f"  title: {s['title']}")
        lines.append(f"  mitigation: {s['mitigation']}")
    rendered = "\n".join(lines) + "\n"

output_path.write_text(rendered, encoding="utf-8")
print(f"Adversarial simulation report written: {output_path}")
PY
