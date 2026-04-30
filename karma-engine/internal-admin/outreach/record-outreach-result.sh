#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
RESULTS_CSV="${ROOT_DIR}/internal-admin/outreach/outreach-results.csv"
LEADS_CSV="${ROOT_DIR}/internal-admin/outreach/seller-leads.csv"

usage() {
  cat <<'USAGE'
Usage:
  ./internal-admin/outreach/record-outreach-result.sh \
    --segment <segment> --contact <id> --status <contacted|replied|demo_booked|first_sale|rejected> [--note <text>]

Description:
  Appends one outreach outcome row to outreach-results.csv.
USAGE
}

SEGMENT=""
CONTACT=""
STATUS=""
NOTE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --segment)
      SEGMENT="$2"; shift 2;;
    --contact)
      CONTACT="$2"; shift 2;;
    --status)
      STATUS="$2"; shift 2;;
    --note)
      NOTE="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown arg: $1" >&2; usage; exit 1;;
  esac
done

[[ -z "$SEGMENT" || -z "$CONTACT" || -z "$STATUS" ]] && { echo "Error: missing required args" >&2; usage; exit 1; }

case "$STATUS" in
  contacted|replied|demo_booked|first_sale|rejected) ;;
  *)
    echo "Error: invalid status '$STATUS'" >&2
    exit 1
    ;;
esac

if [[ ! -f "$RESULTS_CSV" ]]; then
  echo "timestamp,segment,priority,label,contact,status,note" > "$RESULTS_CSV"
fi

meta=$(python3 - "$LEADS_CSV" "$SEGMENT" << 'PY'
import csv, sys
from pathlib import Path
leads = Path(sys.argv[1])
segment = sys.argv[2]
with leads.open(encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if (r.get('segment') or '').strip() == segment:
            print((r.get('priority') or '').strip() + "\t" + (r.get('label') or '').strip())
            raise SystemExit(0)
print("\t")
PY
)

priority="${meta%%$'\t'*}"
label="${meta#*$'\t'}"

timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

escape_csv() {
  local s="$1"
  s="${s//\"/\"\"}"
  printf '"%s"' "$s"
}

printf "%s,%s,%s,%s,%s,%s,%s\n" \
  "$timestamp" \
  "$(escape_csv "$SEGMENT")" \
  "$(escape_csv "$priority")" \
  "$(escape_csv "$label")" \
  "$(escape_csv "$CONTACT")" \
  "$(escape_csv "$STATUS")" \
  "$(escape_csv "$NOTE")" >> "$RESULTS_CSV"

echo "Recorded outreach result: segment=$SEGMENT contact=$CONTACT status=$STATUS"
