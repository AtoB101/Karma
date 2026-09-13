#!/usr/bin/env bash
# Static gate: Cyber Console wiring (API client + console scripts + page hooks).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CONSOLE="$ROOT/apps/console"
required=(
  index.html
  pages/cyber/index.html
  scripts/karma-public-api.js
  scripts/console-sync.js
  scripts/console-wallet-auth.js
  scripts/console-entry-gate.js
  scripts/cyber-actions.js
  scripts/cyber-authorize.js
  scripts/cyber-console.js
  scripts/cyber-globe-bg.js
  scripts/cyber-identity.js
  scripts/i18n-cyber.js
  styles/cyber-console.css
)

for f in "${required[@]}"; do
  [[ -f "$CONSOLE/$f" ]] || { echo "MISSING $CONSOLE/$f"; exit 1; }
done

grep -q 'settlementLock' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'karmaResolveApiBase' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'cyber-console.css' "$CONSOLE/pages/cyber/index.html"
grep -q 'pages/cyber/index.html' "$CONSOLE/index.html"

python3 -m pytest -q tests/unit/test_console_last_mile.py

# Live HTTP write sequence matching the Cyber Console buttons (ASGI in-process).
python3 -m pytest -q tests/unit/test_console_live_write_smoke.py

if command -v node >/dev/null 2>&1; then
  for js in karma-public-api.js console-sync.js console-wallet-auth.js console-entry-gate.js cyber-actions.js cyber-authorize.js cyber-console.js; do
    node --check "$CONSOLE/scripts/$js"
  done
fi

echo "OK   cyber console gate finished"
