#!/usr/bin/env bash
# Static gate: Console last-mile wiring (API client + action scripts + page hooks).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CONSOLE="$ROOT/apps/console"
required=(
  scripts/console-bootstrap.js
  scripts/console-connect.js
  scripts/console-actions.js
  scripts/karma-public-api.js
  pages/payments/index.html
  pages/receiving/index.html
  pages/trade/index.html
)

for f in "${required[@]}"; do
  [[ -f "$CONSOLE/$f" ]] || { echo "MISSING $CONSOLE/$f"; exit 1; }
done

for path in \
  "$CONSOLE/index.html" \
  "$CONSOLE/pages/payments/index.html" \
  "$CONSOLE/pages/receiving/index.html" \
  "$CONSOLE/pages/disputes/index.html" \
  "$CONSOLE/pages/evidence/index.html" \
  "$CONSOLE/pages/trade/index.html"; do
  grep -q 'console-bootstrap.js' "$path" || { echo "Page missing console-bootstrap.js: $path"; exit 1; }
done

grep -q 'settlementLock' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'data-console-action' "$CONSOLE/pages/payments/index.html"
grep -q 'data-console-action' "$CONSOLE/pages/receiving/index.html"

python3 -m pytest -q tests/unit/test_console_last_mile.py

if command -v node >/dev/null 2>&1; then
  for js in console-bootstrap.js console-connect.js console-actions.js karma-public-api.js; do
    node --check "$CONSOLE/scripts/$js"
  done
fi

echo "OK   console last-mile gate finished"
