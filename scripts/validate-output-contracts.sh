#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"
FORMAT="text"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/validate-output-contracts.sh [--format <text|json>]

Description:
  Validates required top-level output contract fields for latest JSON artifacts.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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

python3 - "$ROOT_DIR" "$RESULTS_DIR" "$FORMAT" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

root = pathlib.Path(sys.argv[1])
results = pathlib.Path(sys.argv[2])
fmt = sys.argv[3]

required = ["schemaVersion", "generatedAt", "source", "traceId"]

checks = [
    ("commercialization-gate", results / "commercialization-gate-latest.json", "trustchain.commercial.gate.v1"),
    ("proof-patrol-alert", results / "proof-patrol-alert-latest.json", "trustchain.proof.patrol.alert.v1"),
    ("agent-guardian-report", results / "agent-safety-guardian-latest.json", "trustchain.guardian.v1"),
    ("agent-guardian-alarm", results / "agent-safety-alarm-latest.json", "trustchain.guardian.alarm.v1"),
    ("agent-risk-register", results / "agent-risk-register.json", "trustchain.risk.register.v1"),
]

rows = []
fail_count = 0
for name, path, expected_schema in checks:
    if not path.exists():
        rows.append({
            "name": name,
            "path": str(path),
            "status": "skipped",
            "reason": "file_not_found",
        })
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail_count += 1
        rows.append({
            "name": name,
            "path": str(path),
            "status": "fail",
            "reason": f"invalid_json:{exc}",
        })
        continue

    missing = [f for f in required if f not in data]
    schema_ok = data.get("schemaVersion") == expected_schema
    if missing or not schema_ok:
        fail_count += 1
        rows.append({
            "name": name,
            "path": str(path),
            "status": "fail",
            "missing": missing,
            "schemaVersion": data.get("schemaVersion"),
            "expectedSchemaVersion": expected_schema,
        })
    else:
        rows.append({
            "name": name,
            "path": str(path),
            "status": "pass",
            "schemaVersion": data.get("schemaVersion"),
            "traceId": data.get("traceId"),
        })

summary = {
    "schemaVersion": "trustchain.output.contract.validation.v1",
    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source": "script:validate-output-contracts.sh",
    "traceId": f"trace-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    "total": len(rows),
    "fail": fail_count,
    "pass": sum(1 for r in rows if r["status"] == "pass"),
    "skipped": sum(1 for r in rows if r["status"] == "skipped"),
    "results": rows,
}

if fmt == "json":
    print(json.dumps(summary, indent=2))
else:
    print(f"total={summary['total']} pass={summary['pass']} fail={summary['fail']} skipped={summary['skipped']}")
    for row in rows:
        print(f"- {row['status'].upper()} :: {row['name']} :: {row['path']}")

if fail_count > 0:
    raise SystemExit(2)
PY
