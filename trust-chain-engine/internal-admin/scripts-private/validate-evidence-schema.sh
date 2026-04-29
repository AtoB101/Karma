#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_PATH=""
FORMAT="text"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/validate-evidence-schema.sh --path <json-file> [--format <text|json>]

Description:
  Validates TrustChain diagnosis evidence JSON for required schema markers
  and critical top-level/snapshot fields.

Options:
  --path <json-file>  Path to diagnosis JSON file to validate
  --format <fmt>      Output format: text (default) or json
  -h, --help          Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path)
      [[ $# -lt 2 ]] && { echo "Error: --path requires a value"; exit 1; }
      TARGET_PATH="$2"
      shift 2
      ;;
    --format)
      [[ $# -lt 2 ]] && { echo "Error: --format requires a value"; exit 1; }
      FORMAT="$2"
      if [[ "$FORMAT" != "text" && "$FORMAT" != "json" ]]; then
        echo "Error: --format must be one of text|json"
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

if [[ -z "$TARGET_PATH" ]]; then
  echo "Error: --path is required"
  usage
  exit 1
fi

if [[ "$TARGET_PATH" != /* ]]; then
  TARGET_PATH="${ROOT_DIR}/${TARGET_PATH}"
fi

if [[ ! -f "$TARGET_PATH" ]]; then
  echo "Error: file not found: $TARGET_PATH"
  exit 1
fi

python3 - "$TARGET_PATH" "$FORMAT" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
out_format = sys.argv[2]

def has_path(obj, key_path):
    cur = obj
    for key in key_path:
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    return True

required_top_level = [
    "traceId",
    "app",
    "exportedAt",
    "network",
    "walletAddress",
    "authSnapshot",
    "requestSnapshot",
    "executionSnapshot",
    "riskSnapshot",
]

required_nested = [
    ("executionSnapshot", "diagnostics"),
    ("executionSnapshot", "transactionHistory"),
    ("riskSnapshot", "summary"),
]

result = {
    "status": "fail",
    "inputPath": str(path),
    "schemaVersion": None,
    "evidenceVersion": None,
    "missingFields": [],
    "warnings": [],
}

try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    result["warnings"].append(f"invalid_json: {exc}")
    if out_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print("status: FAIL")
        print(f"inputPath: {result['inputPath']}")
        print(f"reason: {result['warnings'][0]}")
    raise SystemExit(2)

result["schemaVersion"] = data.get("schemaVersion")
result["evidenceVersion"] = data.get("evidenceVersion")

if not result["schemaVersion"]:
    result["missingFields"].append("schemaVersion")
if not result["evidenceVersion"]:
    result["missingFields"].append("evidenceVersion")

if result["schemaVersion"] and result["schemaVersion"] != "evidence-v1":
    result["warnings"].append(f"unexpected_schemaVersion:{result['schemaVersion']}")
if result["evidenceVersion"] and result["evidenceVersion"] != "evidence-v1":
    result["warnings"].append(f"unexpected_evidenceVersion:{result['evidenceVersion']}")

for key in required_top_level:
    if key not in data:
        result["missingFields"].append(key)

for key_path in required_nested:
    if not has_path(data, key_path):
        result["missingFields"].append(".".join(key_path))

result["status"] = "pass" if not result["missingFields"] else "fail"

if out_format == "json":
    print(json.dumps(result, indent=2))
else:
    print(f"status: {result['status'].upper()}")
    print(f"inputPath: {result['inputPath']}")
    print(f"schemaVersion: {result['schemaVersion']}")
    print(f"evidenceVersion: {result['evidenceVersion']}")
    if result["missingFields"]:
        print(f"missingFields: {json.dumps(result['missingFields'])}")
    if result["warnings"]:
        print(f"warnings: {json.dumps(result['warnings'])}")

if result["status"] != "pass":
    raise SystemExit(2)
PY
