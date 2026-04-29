#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
RESULTS_CSV="${ROOT_DIR}/internal-admin/outreach/outreach-results.csv"

usage() {
  cat <<'USAGE'
Usage:
  ./internal-admin/outreach/outreach-funnel-summary.sh [--json]

Description:
  Summarizes outreach funnel counts from outreach-results.csv.
USAGE
}

JSON_MODE=0
if [[ "${1:-}" == "--json" ]]; then
  JSON_MODE=1
elif [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$RESULTS_CSV" ]]; then
  echo "Missing results CSV: $RESULTS_CSV" >&2
  exit 1
fi

python3 - "$RESULTS_CSV" "$JSON_MODE" << 'PY'
import csv, json, sys
from collections import Counter

path = sys.argv[1]
json_mode = sys.argv[2] == '1'
statuses = Counter()
by_segment = {}
contacts = set()

with open(path, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        seg = (r.get('segment') or '').strip().strip('"')
        status = (r.get('status') or '').strip().strip('"')
        contact = (r.get('contact') or '').strip().strip('"')
        if not status:
            continue
        statuses[status] += 1
        if seg:
            by_segment.setdefault(seg, Counter())[status] += 1
        if contact:
            contacts.add(contact)

order = ["contacted","replied","demo_booked","first_sale","rejected"]
out = {
    "schemaVersion": "karma.outreach.funnel.v1",
    "totals": {k: statuses.get(k, 0) for k in order},
    "uniqueContacts": len(contacts),
    "segments": {s: {k: c.get(k,0) for k in order} for s, c in sorted(by_segment.items())}
}

if json_mode:
    print(json.dumps(out, ensure_ascii=False, indent=2))
else:
    print("Outreach funnel summary")
    print("----------------------")
    for k in order:
        print(f"{k:12s}: {out['totals'][k]}")
    print(f"uniqueContacts: {out['uniqueContacts']}")
PY
