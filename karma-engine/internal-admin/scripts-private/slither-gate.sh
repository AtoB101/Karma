#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORMAT="text"
OUTPUT_PATH="${ROOT_DIR}/results/slither-gate-latest.txt"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/slither-gate.sh [--format <text|json>] [--output <path>]

Description:
  Runs Slither static analysis if available; returns non-zero on findings.
  If Slither is not installed, exits non-zero with actionable guidance.
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
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      OUTPUT_PATH="$2"
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

if ! command -v slither >/dev/null 2>&1; then
  msg="slither not found. install via: pip install slither-analyzer"
  if [[ "$FORMAT" == "json" ]]; then
    printf '{"status":"fail","reason":"%s"}\n' "$msg" > "$OUTPUT_PATH"
    cat "$OUTPUT_PATH"
  else
    echo "status: fail" | tee "$OUTPUT_PATH"
    echo "reason: $msg" | tee -a "$OUTPUT_PATH"
  fi
  exit 2
fi

cd "$ROOT_DIR"
if [[ "$FORMAT" == "json" ]]; then
  slither . --json "$OUTPUT_PATH" || {
    echo "slither detected issues (see $OUTPUT_PATH)"
    exit 2
  }
  cat "$OUTPUT_PATH"
else
  slither . | tee "$OUTPUT_PATH" >/dev/null
fi

echo "slither-gate: PASS"
