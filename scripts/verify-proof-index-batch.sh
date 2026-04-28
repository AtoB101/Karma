#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/results"
GLOB_PATTERN="support-bundle-*.zip"
FORMAT="text"
OUT_PATH=""
MAX_FAIL=-1
STRICT=0
SINCE=""
UNTIL=""
MIN_TOTAL=0
REQUIRE_RECENT_PASS_HOURS=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/verify-proof-index-batch.sh [--dir <path>] [--glob <pattern>] [--format <text|json|csv>] [--output <path>] [--max-fail <n>] [--strict] [--since <stamp>] [--until <stamp>] [--min-total <n>] [--require-recent-pass <hours>]

Description:
  Batch-verifies manifestDigest for support bundle proof-index manifests.
  Scans a directory for bundle zip files and runs verify-proof-index on each.

Options:
  --dir <path>       Directory to scan (default: results/)
  --glob <pattern>   Filename glob pattern (default: support-bundle-*.zip)
  --format <fmt>     Output format: text (default), json, or csv
  --output <path>    Optional output file path (prints to stdout if omitted)
  --max-fail <n>     Allow up to n failures before non-zero exit (default: -1 = fail on any)
  --strict           Treat empty match set as failure
  --since <stamp>    Include bundles with stamp >= value (YYYYmmddTHHMMSSZ or YYYY-mm-ddTHH:MM:SSZ)
  --until <stamp>    Include bundles with stamp <= value (YYYYmmddTHHMMSSZ or YYYY-mm-ddTHH:MM:SSZ)
  --min-total <n>    Require at least n matched bundles (default: 0 = disabled)
  --require-recent-pass <hours>  Require latest pass within <hours> (relative to now UTC)
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
    --max-fail)
      [[ $# -lt 2 ]] && { echo "Error: --max-fail requires a value"; exit 1; }
      MAX_FAIL="$2"
      if ! [[ "$MAX_FAIL" =~ ^-?[0-9]+$ ]]; then
        echo "Error: --max-fail must be an integer"
        exit 1
      fi
      shift 2
      ;;
    --strict)
      STRICT=1
      shift
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
    --min-total)
      [[ $# -lt 2 ]] && { echo "Error: --min-total requires a value"; exit 1; }
      MIN_TOTAL="$2"
      if ! [[ "$MIN_TOTAL" =~ ^[0-9]+$ ]]; then
        echo "Error: --min-total must be a non-negative integer"
        exit 1
      fi
      shift 2
      ;;
    --require-recent-pass)
      [[ $# -lt 2 ]] && { echo "Error: --require-recent-pass requires a value"; exit 1; }
      REQUIRE_RECENT_PASS_HOURS="$2"
      if ! [[ "$REQUIRE_RECENT_PASS_HOURS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "Error: --require-recent-pass must be a non-negative number of hours"
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

if [[ "$TARGET_DIR" != /* ]]; then
  TARGET_DIR="${ROOT_DIR}/${TARGET_DIR}"
fi

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Error: directory not found: $TARGET_DIR"
  exit 1
fi

python3 - "$ROOT_DIR" "$TARGET_DIR" "$GLOB_PATTERN" "$FORMAT" "$OUT_PATH" "$MAX_FAIL" "$STRICT" "$SINCE" "$UNTIL" "$MIN_TOTAL" "$REQUIRE_RECENT_PASS_HOURS" <<'PY'
import csv
import datetime as dt
import glob
import json
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
target_dir = pathlib.Path(sys.argv[2])
glob_pattern = sys.argv[3]
out_format = sys.argv[4]
out_path = sys.argv[5]
max_fail = int(sys.argv[6])
strict = int(sys.argv[7])
since = sys.argv[8]
until = sys.argv[9]
min_total = int(sys.argv[10])
require_recent_pass_hours = sys.argv[11]

verify_script = root / "scripts" / "verify-proof-index.sh"

STAMP_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
ISO_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$")

def normalize_stamp(value: str) -> str:
    if not value:
        return ""
    if STAMP_RE.match(value):
        return value
    m = ISO_RE.match(value)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}{mo}{d}T{h}{mi}{s}Z"
    raise ValueError("stamp must match YYYYmmddTHHMMSSZ or YYYY-mm-ddTHH:MM:SSZ")

def extract_stamp(name: str):
    if not name.startswith("support-bundle-") or not name.endswith(".zip"):
        return None
    stamp = name[len("support-bundle-"):-len(".zip")]
    if STAMP_RE.match(stamp):
        return stamp
    return None

try:
    since_norm = normalize_stamp(since)
except ValueError as exc:
    print(f"Error: invalid --since value: {exc}", file=sys.stderr)
    raise SystemExit(1)

try:
    until_norm = normalize_stamp(until)
except ValueError as exc:
    print(f"Error: invalid --until value: {exc}", file=sys.stderr)
    raise SystemExit(1)

matches_all = sorted(target_dir.glob(glob_pattern))
matches = []
for item in matches_all:
    name = item.name
    stamp = extract_stamp(name)
    if not stamp:
        matches.append(item)
        continue
    if since_norm and stamp < since_norm:
        continue
    if until_norm and stamp > until_norm:
        continue
    matches.append(item)
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

reason_summary = {}
latest_pass_at = None
for row in results:
    if row.get("status") == "pass":
        path_text = str(row.get("inputPath") or "")
        name = pathlib.Path(path_text).name
        stamp = extract_stamp(name)
        if stamp and (latest_pass_at is None or stamp > latest_pass_at):
            latest_pass_at = stamp
    else:
        reason_key = row.get("reason") or "unknown_reason"
        reason_summary[reason_key] = reason_summary.get(reason_key, 0) + 1

summary = {
    "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "targetDir": str(target_dir),
    "glob": glob_pattern,
    "since": since_norm or None,
    "until": until_norm or None,
    "strict": bool(strict),
    "maxFail": max_fail,
    "minTotal": min_total,
    "requireRecentPassHours": float(require_recent_pass_hours) if require_recent_pass_hours else None,
    "total": len(results),
    "pass": sum(1 for r in results if r.get("status") == "pass"),
    "fail": sum(1 for r in results if r.get("status") != "pass"),
    "latestPassAt": latest_pass_at,
    "reasonSummary": reason_summary,
    "results": results,
}

policy = {
    "strictNoMatchViolated": bool(strict and summary["total"] == 0),
    "maxFailViolated": bool((max_fail >= 0 and summary["fail"] > max_fail) or (max_fail < 0 and summary["fail"] > 0)),
    "minTotalViolated": bool(summary["total"] < min_total),
    "recentPassViolated": False,
}

if require_recent_pass_hours:
    hours = float(require_recent_pass_hours)
    threshold = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    latest_pass_dt = None
    if latest_pass_at:
        latest_pass_dt = dt.datetime.strptime(latest_pass_at, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    policy["recentPassViolated"] = bool(latest_pass_dt is None or latest_pass_dt < threshold)
    summary["recentPassThreshold"] = threshold.strftime("%Y%m%dT%H%M%SZ")
else:
    summary["recentPassThreshold"] = None

summary["policy"] = policy
summary["ok"] = not any(policy.values())

def emit_text(data):
    lines = [
        f"generatedAt: {data['generatedAt']}",
        f"targetDir: {data['targetDir']}",
        f"glob: {data['glob']}",
        f"total: {data['total']}",
        f"pass: {data['pass']}",
        f"fail: {data['fail']}",
        f"latestPassAt: {data.get('latestPassAt')}",
        f"reasonSummary: {json.dumps(data.get('reasonSummary', {}), ensure_ascii=False)}",
        f"policy: {json.dumps(data.get('policy', {}), ensure_ascii=False)}",
        f"ok: {data.get('ok')}",
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

if not summary["ok"]:
    raise SystemExit(2)
PY
