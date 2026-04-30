#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT_DIR}/results"

TARGET_DIR="${RESULTS_DIR}"
GLOB_PATTERN="support-bundle-*.zip"
PROFILE="balanced"
SINCE=""
UNTIL=""
BATCH_OUTPUT="${RESULTS_DIR}/proof-patrol-batch-latest.json"
ALERT_OUTPUT="${RESULTS_DIR}/proof-patrol-alert-latest.json"
PRINT_SUMMARY=1

usage() {
  cat <<'EOF'
Usage:
  ./scripts/proof-patrol.sh [--profile <strict|balanced|lenient>] [--dir <path>] [--glob <pattern>] [--since <stamp>] [--until <stamp>] [--batch-output <path>] [--alert-output <path>] [--no-summary]

Description:
  Runs scheduled proof-index patrol using policy profiles, then emits
  an alert-friendly JSON summary for cron/monitor integrations.

Options:
  --profile <name>      Policy profile: strict|balanced|lenient (default: balanced)
  --dir <path>          Target directory for support bundles (default: results/)
  --glob <pattern>      Bundle glob pattern (default: support-bundle-*.zip)
  --since <stamp>       Optional lower bound (YYYYmmddTHHMMSSZ or ISO8601)
  --until <stamp>       Optional upper bound (YYYYmmddTHHMMSSZ or ISO8601)
  --batch-output <path> Where to write raw batch JSON summary
  --alert-output <path> Where to write alert-friendly JSON summary
  --no-summary          Do not print rendered batch summary to stdout
  -h, --help            Show this help message
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
    --dir)
      [[ $# -lt 2 ]] && { echo "Error: --dir requires a value"; exit 1; }
      TARGET_DIR="$2"
      shift 2
      ;;
    --glob)
      [[ $# -lt 2 ]] && { echo "Error: --glob requires a value"; exit 1; }
      GLOB_PATTERN="$2"
      shift 2
      ;;
    --since)
      [[ $# -lt 2 ]] && { echo "Error: --since requires a value"; exit 1; }
      SINCE="$2"
      shift 2
      ;;
    --until)
      [[ $# -lt 2 ]] && { echo "Error: --until requires a value"; exit 1; }
      UNTIL="$2"
      shift 2
      ;;
    --batch-output)
      [[ $# -lt 2 ]] && { echo "Error: --batch-output requires a value"; exit 1; }
      BATCH_OUTPUT="$2"
      shift 2
      ;;
    --alert-output)
      [[ $# -lt 2 ]] && { echo "Error: --alert-output requires a value"; exit 1; }
      ALERT_OUTPUT="$2"
      shift 2
      ;;
    --no-summary)
      PRINT_SUMMARY=0
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

if [[ "$TARGET_DIR" != /* ]]; then
  TARGET_DIR="${ROOT_DIR}/${TARGET_DIR}"
fi
if [[ "$BATCH_OUTPUT" != /* ]]; then
  BATCH_OUTPUT="${ROOT_DIR}/${BATCH_OUTPUT}"
fi
if [[ "$ALERT_OUTPUT" != /* ]]; then
  ALERT_OUTPUT="${ROOT_DIR}/${ALERT_OUTPUT}"
fi

mkdir -p "$(dirname "$BATCH_OUTPUT")" "$(dirname "$ALERT_OUTPUT")"

STRICT_FLAG=1
MAX_FAIL=1
MIN_TOTAL=2
RECENT_PASS_HOURS=72

case "$PROFILE" in
  strict)
    STRICT_FLAG=1
    MAX_FAIL=0
    MIN_TOTAL=3
    RECENT_PASS_HOURS=24
    ;;
  balanced)
    STRICT_FLAG=1
    MAX_FAIL=1
    MIN_TOTAL=2
    RECENT_PASS_HOURS=72
    ;;
  lenient)
    STRICT_FLAG=0
    MAX_FAIL=2
    MIN_TOTAL=1
    RECENT_PASS_HOURS=168
    ;;
esac

BATCH_ARGS=(
  --dir "$TARGET_DIR"
  --glob "$GLOB_PATTERN"
  --format json
  --output "$BATCH_OUTPUT"
  --max-fail "$MAX_FAIL"
  --min-total "$MIN_TOTAL"
  --require-recent-pass "$RECENT_PASS_HOURS"
)
if [[ "$STRICT_FLAG" -eq 1 ]]; then
  BATCH_ARGS+=(--strict)
fi
if [[ -n "$SINCE" ]]; then
  BATCH_ARGS+=(--since "$SINCE")
fi
if [[ -n "$UNTIL" ]]; then
  BATCH_ARGS+=(--until "$UNTIL")
fi

set +e
./scripts/verify-proof-index-batch.sh "${BATCH_ARGS[@]}"
BATCH_EXIT=$?
set -e

python3 - "$BATCH_OUTPUT" "$ALERT_OUTPUT" "$PROFILE" "$BATCH_EXIT" <<'PY'
import datetime as dt
import json
import pathlib
import sys

batch_path = pathlib.Path(sys.argv[1])
alert_path = pathlib.Path(sys.argv[2])
profile = sys.argv[3]
batch_exit = int(sys.argv[4])

data = json.loads(batch_path.read_text(encoding="utf-8"))
policy = data.get("policy", {}) or {}
ok = bool(data.get("ok"))

if ok:
    severity = "info"
else:
    if policy.get("recentPassViolated") or policy.get("maxFailViolated"):
        severity = "critical"
    else:
        severity = "warning"

trace_id = f"trace-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-proof-patrol"
alert = {
    "schemaVersion": "karma.proof.patrol.alert.v1",
    "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source": "script:proof-patrol.sh",
    "traceId": trace_id,
    "version": "proof-patrol-alert-v1",
    "profile": profile,
    "status": "pass" if ok else "fail",
    "severity": severity,
    "batchExitCode": batch_exit,
    "targetDir": data.get("targetDir"),
    "glob": data.get("glob"),
    "total": data.get("total"),
    "pass": data.get("pass"),
    "fail": data.get("fail"),
    "latestPassAt": data.get("latestPassAt"),
    "recentPassThreshold": data.get("recentPassThreshold"),
    "policy": policy,
    "reasonSummary": data.get("reasonSummary", {}),
    "nextActions": [
        "run ./scripts/verify-proof-index-batch.sh --format json for full details",
        "run make support-bundle to refresh sample artifacts",
        "inspect proof-index mismatch reasons in reasonSummary when fail > 0",
    ],
}

alert_path.write_text(json.dumps(alert, indent=2) + "\n", encoding="utf-8")
print(f"Alert summary written: {alert_path}")
PY

if [[ "$PRINT_SUMMARY" -eq 1 ]]; then
  python3 - "$BATCH_OUTPUT" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print("proof patrol summary:")
print(f"  ok: {data.get('ok')}")
print(f"  total/pass/fail: {data.get('total')}/{data.get('pass')}/{data.get('fail')}")
print(f"  latestPassAt: {data.get('latestPassAt')}")
print(f"  policy: {json.dumps(data.get('policy', {}), ensure_ascii=False)}")
PY
fi

exit "$BATCH_EXIT"
