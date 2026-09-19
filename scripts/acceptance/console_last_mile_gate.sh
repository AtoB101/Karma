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
  scripts/cyber-unbind-keys.js
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
# 未激活的钥匙不能花钱：铸造时的标记、网关的拒用、操作台的「未激活」标注，三处都要在。
grep -q 'PENDING_KEY_BINDING' "$ROOT/services/runtime_key_service.py"
grep -q 'pending_activation_block' "$ROOT/api/routes/runtime_gateway.py"
# 一键取消绑定：设置页那张卡片 + 会话取数 + 钱包签名端点，三处都要在。
grep -q 'cyber-unbind-keys.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'runtimeListBoundKeys' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'list-bound-keys' "$CONSOLE/scripts/cyber-unbind-keys.js"
grep -q 'buildUnbindKeyMsg' "$CONSOLE/scripts/cyber-handoff.js"
grep -q 'unbind_key_binding' "$ROOT/api/routes/runtime_gateway.py"
grep -q 'BIND_CODE_TTL_SECONDS = 180' "$ROOT/services/runtime_key_service.py"
grep -q '未激活（等匹配码）' "$CONSOLE/scripts/cyber-handoff.js"
grep -q 'activation_required' "$CONSOLE/scripts/cyber-handoff.js"
# 行业硬指标表单：向导和配对接入必须共用同一份实现，不能各写一套。
grep -q 'karma-service-spec.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'KarmaServiceSpec' "$CONSOLE/scripts/cyber-agents.js"
grep -q 'KarmaServiceSpec' "$CONSOLE/scripts/cyber-pairing.js"
grep -q 'pages/cyber/index.html' "$CONSOLE/index.html"

python3 -m pytest -q tests/unit/test_console_last_mile.py

# Live HTTP write sequence matching the Cyber Console buttons (ASGI in-process).
python3 -m pytest -q tests/unit/test_console_live_write_smoke.py

if command -v node >/dev/null 2>&1; then
  # 语言包必须是能跑起来的 JS：pytest 那边只 grep 文本，包一旦写坏（少个逗号），
  # 切语言整页就会静默退回中文 —— 只有真的解析一遍才拦得住。
  for pack in "$CONSOLE"/scripts/i18n-phrase/*.js; do
    node --check "$pack"
  done
  for js in karma-public-api.js console-sync.js console-wallet-auth.js console-entry-gate.js cyber-actions.js cyber-authorize.js karma-service-spec.js cyber-pairing.js cyber-payments.js cyber-console.js cyber-orders.js cyber-order-flow.js cyber-identity.js cyber-identity-verify.js cyber-bind-requests.js cyber-unbind-keys.js; do
    node --check "$CONSOLE/scripts/$js"
  done
fi

echo "OK   cyber console gate finished"
