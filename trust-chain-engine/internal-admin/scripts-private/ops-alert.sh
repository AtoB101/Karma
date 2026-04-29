#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
INPUT_PATH="${RESULTS_DIR}/system-status-latest.json"
OUTPUT_PATH="${RESULTS_DIR}/ops-alert-latest.json"
FORMAT="text"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/ops-alert.sh [--input <path>] [--output <path>] [--format <text|json>]

Description:
  Export alert-friendly JSON artifact from system-status summary.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      [[ $# -lt 2 ]] && { echo "Error: --input requires a value"; exit 1; }
      INPUT_PATH="$2"
      shift 2
      ;;
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

if [[ "$INPUT_PATH" != /* ]]; then
  INPUT_PATH="${ROOT_DIR}/${INPUT_PATH}"
fi
if [[ "$OUTPUT_PATH" != /* ]]; then
  OUTPUT_PATH="${ROOT_DIR}/${OUTPUT_PATH}"
fi
mkdir -p "$(dirname "$OUTPUT_PATH")"

python3 - "$INPUT_PATH" "$OUTPUT_PATH" "$FORMAT" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

input_path = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
fmt = sys.argv[3]

if not input_path.exists():
    print(f"Error: input not found: {input_path}", file=sys.stderr)
    raise SystemExit(1)

status = json.loads(input_path.read_text(encoding="utf-8"))
summary = status.get("summary") or {}
components = status.get("components") or {}

severity = summary.get("alertSeverity", "info")
overall = summary.get("overall", "unknown")
next_actions = list(summary.get("nextActions") or [])

if severity in {"critical", "high"}:
    priority = "P1"
elif severity == "medium":
    priority = "P2"
elif severity == "warning":
    priority = "P3"
else:
    priority = "P4"

alert = {
    "schemaVersion": "trustchain.ops.alert.v1",
    "version": "ops-alert-v1",
    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source": "script:ops-alert.sh",
    "traceId": status.get("traceId") or f"ops-alert-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    "status": overall,
    "severity": severity,
    "priority": priority,
    "summary": {
      "commercialReady": summary.get("commercialReady"),
      "patrolHealthy": summary.get("patrolHealthy"),
      "contractsHealthy": summary.get("contractsHealthy"),
    },
    "components": {
      "commercialGate": components.get("commercialGate", {}),
      "proofPatrol": components.get("proofPatrol", {}),
      "guardian": components.get("guardian", {}),
      "outputContracts": components.get("outputContracts", {}),
    },
    "nextActions": next_actions,
    "routingHints": {
      "channel": "oncall" if severity in {"critical", "high"} else "ops-monitor",
      "notify": severity in {"critical", "high", "medium"},
      "ticketRecommended": severity in {"critical", "high"},
    },
}

output_path.write_text(json.dumps(alert, indent=2) + "\n", encoding="utf-8")

if fmt == "json":
    print(json.dumps(alert, indent=2))
else:
    print(f"status: {alert['status']}")
    print(f"severity: {alert['severity']}")
    print(f"priority: {alert['priority']}")
    print(f"channel: {alert['routingHints']['channel']}")
    print(f"nextActions: {len(alert['nextActions'])}")
    print(f"output: {output_path}")
PY
