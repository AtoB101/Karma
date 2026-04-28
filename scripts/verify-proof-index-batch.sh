#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/results"
GLOB_PATTERN="support-bundle-*.zip"
FORMAT="text"
OUT_PATH=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/verify-proof-index-batch.sh [--dir <path>] [--glob <pattern>] [--format <text|json|csv>] [--output <path>]

Description:
  Batch-verifies manifestDigest for support bundle proof-index manifests.
  Scans a directory for bundle zip files and runs verify-proof-index on each.

Options:
  --dir <path>       Directory to scan (default: results/)
  --glob <pattern>   Filename glob pattern (default: support-bundle-*.zip)
  --format <fmt>     Output format: text (default), json, or csv
  --output <path>    Optional output file path (prints to stdout if omitted)
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --format)
      [[ $# -lt 2 ]] && { echo "Error: --format requires a value"; exit 1; }
      FORMAT="$2"
      if [[ "$FORMAT" != "text" && "$FORMAT" != "json" && "$FORMAT" != "csv" ]]; then
        echo "Error: --format must be one of text|json|csv"
        exit 1
      fi
      shift 2
      ;;
    --output)
      [[ $# -lt 2 ]] && { echo "Error: --output requires a value"; exit 1; }
      OUT_PATH="$2"
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

if [[ "$TARGET_DIR" != /* ]]; then
  TARGET_DIR="${ROOT_DIR}/${TARGET_DIR}"
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Error: directory not found: $TARGET_DIR"
  exit 1
fi

python3 - "$ROOT_DIR" "$TARGET_DIR" "$GLOB_PATTERN" "$FORMAT" "$OUT_PATH" <<'PY'
import csv
import datetime as dt
import glob
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
target_dir = pathlib.Path(sys.argv[2])
glob_pattern = sys.argv[3]
out_format = sys.argv[4]
out_path = sys.argv[5]

verify_script = root / "scripts" / "verify-proof-index.sh"

matches = sorted(target_dir.glob(glob_pattern))
results = []
for item in matches:
    proc = subprocess.run(
        [str(verify_script), "--path", str(item), "--format", "json"],
        capture_output=True,
        text=True,
    )
    parsed = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = {
                "inputPath": str(item),
                "inputKind": "support_bundle_zip",
                "status": "fail",
                "declaredDigest": None,
                "recomputedDigest": None,
                "reason": f"invalid verifier output: {proc.stdout.strip()}",
            }
    if parsed is None:
        parsed = {
            "inputPath": str(item),
            "inputKind": "support_bundle_zip",
            "status": "fail",
            "declaredDigest": None,
            "recomputedDigest": None,
            "reason": proc.stderr.strip() or "verifier returned no output",
        }
    parsed["exitCode"] = proc.returncode
    results.append(parsed)

summary = {
    "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "targetDir": str(target_dir),
    "glob": glob_pattern,
    "total": len(results),
    "pass": sum(1 for r in results if r.get("status") == "pass"),
    "fail": sum(1 for r in results if r.get("status") != "pass"),
    "results": results,
}

def emit_text(data):
    lines = [
        f"generatedAt: {data['generatedAt']}",
        f"targetDir: {data['targetDir']}",
        f"glob: {data['glob']}",
        f"total: {data['total']}",
        f"pass: {data['pass']}",
        f"fail: {data['fail']}",
        "",
    ]
    for row in data["results"]:
        lines.append(f"- {row.get('status','unknown').upper()} :: {row.get('inputPath')}")
        lines.append(f"  declared:   {row.get('declaredDigest')}")
        lines.append(f"  recomputed: {row.get('recomputedDigest')}")
        if row.get("reason"):
            lines.append(f"  reason:     {row.get('reason')}")
    return "\n".join(lines) + "\n"

def emit_json(data):
    return json.dumps(data, indent=2) + "\n"

def emit_csv(data):
    fieldnames = [
        "path",
        "status",
        "declaredDigest",
        "recomputedDigest",
        "reason",
        "exitCode",
    ]
    from io import StringIO
    buff = StringIO()
    writer = csv.DictWriter(buff, fieldnames=fieldnames)
    writer.writeheader()
    for row in data["results"]:
        writer.writerow(
            {
                "path": row.get("inputPath"),
                "status": row.get("status"),
                "declaredDigest": row.get("declaredDigest"),
                "recomputedDigest": row.get("recomputedDigest"),
                "reason": row.get("reason"),
                "exitCode": row.get("exitCode"),
            }
        )
    return buff.getvalue()

if out_format == "json":
    rendered = emit_json(summary)
elif out_format == "csv":
    rendered = emit_csv(summary)
else:
    rendered = emit_text(summary)

if out_path:
    out_file = pathlib.Path(out_path)
    if not out_file.is_absolute():
        out_file = root / out_file
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(rendered, encoding="utf-8")
    print(f"Batch report written: {out_file}")
else:
    print(rendered, end="")

if summary["fail"] > 0:
    raise SystemExit(2)
PY
