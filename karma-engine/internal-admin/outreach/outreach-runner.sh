#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
CSV_PATH="${ROOT_DIR}/internal-admin/outreach/seller-leads.csv"

usage() {
  cat <<'USAGE'
Usage:
  ./internal-admin/outreach/outreach-runner.sh [--segment <S|A|R|D|C>] [--limit <n>]

Description:
  Prints a prioritized outreach list based on seller-leads.csv for manual campaigns.

Options:
  --segment <code>   Filter by priority segment (S/A/R/D/C). Default: all.
  --limit <n>        Limit number of rows.
  -h, --help         Show help.
USAGE
}

SEGMENT_FILTER=""
LIMIT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --segment)
      [[ $# -lt 2 ]] && { echo "Error: --segment requires value" >&2; exit 1; }
      SEGMENT_FILTER="${2}";
      shift 2;;
    --limit)
      [[ $# -lt 2 ]] && { echo "Error: --limit requires value" >&2; exit 1; }
      LIMIT="${2}";
      shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

if [[ ! -f "$CSV_PATH" ]]; then
  echo "Missing seller leads CSV: $CSV_PATH" >&2
  exit 1
fi

python3 - "$CSV_PATH" "$SEGMENT_FILTER" "$LIMIT" << 'PY'
import csv, sys
from pathlib import Path

csv_path = Path(sys.argv[1])
segment_filter = (sys.argv[2] or '').strip().upper()
limit = int(sys.argv[3]) if (len(sys.argv) > 3 and sys.argv[3]) else None

rows = []
with csv_path.open(encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        seg = (row.get('priority') or '').strip().upper()
        if segment_filter and seg != segment_filter:
            continue
        rows.append(row)

if limit is not None:
    rows = rows[:limit]

for i, r in enumerate(rows, 1):
    print(f"{i}. [{r.get('priority','?')}] {r.get('label','')}  (segment={r.get('segment','')})")
PY
