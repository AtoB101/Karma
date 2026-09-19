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
  scripts/karma-service-spec.js
  scripts/cyber-pairing.js
  scripts/cyber-bind-requests.js
  scripts/cyber-payments.js
  scripts/cyber-console.js
  scripts/cyber-order-flow.js
  scripts/cyber-globe-bg.js
  scripts/cyber-identity.js
  scripts/cyber-identity-verify.js
  scripts/i18n-cyber.js
  styles/cyber-console.css
)

for f in "${required[@]}"; do
  [[ -f "$CONSOLE/$f" ]] || { echo "MISSING $CONSOLE/$f"; exit 1; }
done

grep -q 'settlementLock' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'karmaResolveApiBase' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'cyber-console.css' "$CONSOLE/pages/cyber/index.html"
grep -q 'cyber-identity-verify.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'cyber-pairing.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'attachPairingRuntimeKey' "$CONSOLE/scripts/karma-public-api.js"
# 接入确认：设置页那张卡片 + 会话鉴权取数，少一个主人就看不见待确认请求。
grep -q 'cyber-bind-requests.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'runtimeListPendingBinds' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'list-pending-binds' "$CONSOLE/scripts/cyber-bind-requests.js"
# 行业硬指标表单：向导和配对接入必须共用同一份实现，不能各写一套。
grep -q 'karma-service-spec.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'KarmaServiceSpec' "$CONSOLE/scripts/cyber-agents.js"
grep -q 'KarmaServiceSpec' "$CONSOLE/scripts/cyber-pairing.js"
grep -q 'pages/cyber/index.html' "$CONSOLE/index.html"

python3 -m pytest -q tests/unit/test_console_last_mile.py

# Live HTTP write sequence matching the Cyber Console buttons (ASGI in-process).
python3 -m pytest -q tests/unit/test_console_live_write_smoke.py

if command -v node >/dev/null 2>&1; then
  for js in karma-public-api.js console-sync.js console-wallet-auth.js console-entry-gate.js cyber-actions.js cyber-authorize.js karma-service-spec.js cyber-pairing.js cyber-payments.js cyber-console.js cyber-orders.js cyber-order-flow.js cyber-identity.js cyber-identity-verify.js cyber-bind-requests.js; do
    node --check "$CONSOLE/scripts/$js"
  done
fi

echo "OK   cyber console gate finished"
