#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_PATH=""
FORMAT="text"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/verify-proof-index.sh --path <proof-index.json|support-bundle.zip> [--format <text|json>]

Description:
  Recomputes and verifies proof-index manifestDigest integrity.
  Supports direct proof-index.json file or support-bundle zip input.

Options:
  --path <path>       Input path to proof-index.json or support-bundle zip (required)
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
        echo "Error: --format must be 'text' or 'json'"
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

ABS_PATH="$TARGET_PATH"
if [[ "$ABS_PATH" != /* ]]; then
  ABS_PATH="${ROOT_DIR}/${ABS_PATH}"
fi

if [[ ! -f "$ABS_PATH" ]]; then
  echo "Error: file not found: $ABS_PATH"
  exit 1
fi

python3 - "$ABS_PATH" "$FORMAT" <<'PY'
import hashlib
import json
import pathlib
import sys
import zipfile

target_path = pathlib.Path(sys.argv[1])
fmt = sys.argv[2]

def output(data):
    if fmt == "json":
        print(json.dumps(data, indent=2))
    else:
        print(f"inputPath: {data['inputPath']}")
        print(f"inputKind: {data['inputKind']}")
        print(f"status: {data['status']}")
        print(f"declaredDigest: {data['declaredDigest']}")
        print(f"recomputedDigest: {data['recomputedDigest']}")
        if data["reason"]:
            print(f"reason: {data['reason']}")

def fail(reason, *, declared=None, recomputed=None, input_kind="unknown"):
    result = {
        "inputPath": str(target_path),
        "inputKind": input_kind,
        "status": "fail",
        "declaredDigest": declared,
        "recomputedDigest": recomputed,
        "reason": reason,
    }
    output(result)
    raise SystemExit(2)

if target_path.suffix.lower() == ".zip":
    input_kind = "support_bundle_zip"
    try:
        with zipfile.ZipFile(target_path, "r") as zf:
            try:
                raw = zf.read("proof-index.json").decode("utf-8")
            except KeyError:
                fail("proof-index.json not found in zip", input_kind=input_kind)
    except zipfile.BadZipFile:
        fail("invalid zip file", input_kind=input_kind)
else:
    input_kind = "proof_index_json"
    try:
        raw = target_path.read_text(encoding="utf-8")
    except Exception as exc:
        fail(f"cannot read file: {exc}", input_kind=input_kind)

try:
    index = json.loads(raw)
except json.JSONDecodeError as exc:
    fail(f"invalid JSON: {exc}", input_kind=input_kind)

declared = index.get("manifestDigest")
if not declared or not isinstance(declared, str):
    fail("manifestDigest missing", declared=declared, input_kind=input_kind)

base = dict(index)
base.pop("manifestDigest", None)
canonical = json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
recomputed = hashlib.sha256(canonical).hexdigest()
ok = recomputed == declared

result = {
    "inputPath": str(target_path),
    "inputKind": input_kind,
    "status": "pass" if ok else "fail",
    "declaredDigest": declared,
    "recomputedDigest": recomputed,
    "reason": None if ok else "manifestDigest mismatch",
}
output(result)
if not ok:
    raise SystemExit(2)
PY
