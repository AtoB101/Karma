#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
OUTPUT_PATH="${RESULTS_DIR}/system-status-latest.json"
FORMAT="text"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/system-status.sh [--output <path>] [--format <text|json>]

Description:
  Aggregates operational status from latest readiness, proof, and guardian artifacts.
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
      if [[ "$FORMAT" != "text" && "$FORMAT" != "json" ]]; then
        echo "Error: --format must be text or json"
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

python3 - "$ROOT_DIR" "$RESULTS_DIR" "$OUTPUT_PATH" "$FORMAT" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

root = pathlib.Path(sys.argv[1])
results = pathlib.Path(sys.argv[2])
out = pathlib.Path(sys.argv[3])
fmt = sys.argv[4]

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: pathlib.Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

commercial = load_json(results / "commercialization-gate-latest.json")
patrol = load_json(results / "proof-patrol-alert-latest.json")
guardian = load_json(results / "agent-safety-guardian-latest.json")
contracts = load_json(results / "output-contracts-validation-latest.json")

status = {
    "schemaVersion": "trustchain.system.status.v1",
    "version": "system-status-v1",
    "generatedAt": now,
    "source": "script:system-status.sh",
    "traceId": f"system-status-{now}",
    "components": {
        "commercialGate": {
            "status": (commercial or {}).get("overallStatus", "unknown"),
            "mustOk": ((commercial or {}).get("must") or {}).get("ok"),
            "updatedAt": (commercial or {}).get("generatedAt"),
        },
        "proofPatrol": {
            "status": (patrol or {}).get("status", "unknown"),
            "severity": (patrol or {}).get("severity", "unknown"),
            "updatedAt": (patrol or {}).get("generatedAt"),
            "latestPassAt": (patrol or {}).get("latestPassAt"),
        },
        "guardian": {
            "overall": ((guardian or {}).get("riskAssessment") or {}).get("overall", "unknown"),
            "riskCount": ((guardian or {}).get("riskAssessment") or {}).get("riskCount"),
            "heatIndex": ((guardian or {}).get("predictiveDefense") or {}).get("riskHeatIndex"),
            "profile": (guardian or {}).get("profile"),
            "updatedAt": (guardian or {}).get("generatedAt"),
        },
        "outputContracts": {
            "fail": (contracts or {}).get("fail"),
            "pass": (contracts or {}).get("pass"),
            "skipped": (contracts or {}).get("skipped"),
            "updatedAt": (contracts or {}).get("generatedAt"),
        },
    },
    "summary": {
        "commercialReady": (commercial or {}).get("overallStatus") == "commercial-ready",
        "patrolHealthy": (patrol or {}).get("status") == "pass",
        "contractsHealthy": ((contracts or {}).get("fail", 1) == 0),
    },
}

healthy_flags = [
    status["summary"]["commercialReady"],
    status["summary"]["patrolHealthy"],
    status["summary"]["contractsHealthy"],
]
if all(healthy_flags):
    overall = "healthy"
elif any(healthy_flags):
    overall = "degraded"
else:
    overall = "critical"
status["summary"]["overall"] = overall

runbook = []
severity = "info"
if not status["summary"]["commercialReady"]:
    severity = "critical"
    runbook.append("Run: make commercialization-gate -- investigate MUST failures first.")
if not status["summary"]["patrolHealthy"]:
    severity = "high" if severity != "critical" else severity
    runbook.append("Run: make proof-patrol and inspect proof-patrol-alert-latest.json reasonSummary.")
if not status["summary"]["contractsHealthy"]:
    severity = "high" if severity != "critical" else severity
    runbook.append("Run: make validate-output-contracts and patch producers missing required fields.")
guardian_overall = ((guardian or {}).get("riskAssessment") or {}).get("overall")
if guardian_overall == "fail":
    severity = "critical"
    runbook.append("Run: make agent-safety-guardian and triage newRisks by severity immediately.")
elif guardian_overall == "warning" and severity not in {"critical", "high"}:
    severity = "medium"
    runbook.append("Review guardian warning risks and tighten patrol profile if trend worsens.")

if not runbook:
    runbook.append("Status healthy. Continue periodic patrol and contract validation cadence.")

status["summary"]["alertSeverity"] = severity
status["summary"]["nextActions"] = runbook

out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

if fmt == "json":
    print(json.dumps(status, indent=2))
else:
    print(f"overall: {overall}")
    print(f"alertSeverity: {status['summary']['alertSeverity']}")
    print(f"commercialReady: {status['summary']['commercialReady']}")
    print(f"patrolHealthy: {status['summary']['patrolHealthy']}")
    print(f"contractsHealthy: {status['summary']['contractsHealthy']}")
    print("nextActions:")
    for idx, step in enumerate(status["summary"]["nextActions"], start=1):
        print(f"  {idx}. {step}")
    print(f"output: {out}")
PY
