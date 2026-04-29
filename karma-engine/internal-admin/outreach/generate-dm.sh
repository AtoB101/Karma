#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
CSV_PATH="${ROOT_DIR}/internal-admin/outreach/seller-leads.csv"
TEMPLATE_PATH="${ROOT_DIR}/internal-admin/outreach/dm-templates.md"

usage() {
  cat <<'USAGE'
Usage:
  ./internal-admin/outreach/generate-dm.sh --segment <segment>

Description:
  Prints the recommended first DM template for a given seller segment.
USAGE
}

SEGMENT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --segment)
      [[ $# -lt 2 ]] && { echo "Error: --segment requires value" >&2; exit 1; }
      SEGMENT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$SEGMENT" ]]; then
  echo "Error: --segment is required" >&2
  usage
  exit 1
fi

python3 - "$CSV_PATH" "$TEMPLATE_PATH" "$SEGMENT" << 'PY'
import csv, re, sys
from pathlib import Path

csv_path = Path(sys.argv[1])
md_path = Path(sys.argv[2])
segment = sys.argv[3].strip()

row = None
with csv_path.open(encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if (r.get('segment') or '').strip() == segment:
            row = r
            break

if row is None:
    raise SystemExit(f"segment not found: {segment}")

priority = (row.get('priority') or '').strip().upper()
label = row.get('label') or segment

content = md_path.read_text(encoding='utf-8')

# Try segment-specific heading first
seg_heading = f"### {segment}"
generic_heading = f"### {priority} class generic"

for heading in (seg_heading, generic_heading):
    idx = content.find(heading)
    if idx >= 0:
        tail = content[idx:].splitlines()[1:]
        lines = []
        for ln in tail:
            if ln.startswith('### '):
                break
            if ln.strip():
                lines.append(ln.strip())
        print(f"[segment={segment}] [priority={priority}] {label}")
        print()
        print("\n".join(lines).strip())
        sys.exit(0)

raise SystemExit(f"No template found for segment={segment} or priority={priority}")
PY
