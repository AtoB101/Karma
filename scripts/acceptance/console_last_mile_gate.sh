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
  scripts/karma-nodes.js
  scripts/cyber-node-panel.js
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
  scripts/cyber-face-vault.js
  scripts/cyber-console-2fa.js
  scripts/cyber-add-identity.js
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
# 已绑定钥匙：展开看最近调用（成功/被拒都留痕）+ 取消绑定留一条站内提醒。
# 这两件事都是「主人事后能对账」的地基：额度汇总回答不了「哪一次被拒」。
grep -q 'runtimeKeyCalls' "$CONSOLE/scripts/karma-public-api.js"
grep -q '/runtime/key-calls' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'runtimeAckNotice' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'data-key-calls' "$CONSOLE/scripts/cyber-unbind-keys.js"
grep -q 'runtimeListNotices' "$CONSOLE/scripts/cyber-unbind-keys.js"
grep -q 'data-ack-notices' "$CONSOLE/scripts/cyber-unbind-keys.js"
grep -q 'runtime_call_logged' "$ROOT/api/routes/runtime_gateway.py"
grep -q 'LOGGED_ACTION_PATHS' "$ROOT/api/routes/runtime_gateway.py"
grep -q 'NOTICE_KEY_UNBOUND' "$ROOT/api/routes/runtime_gateway.py"
grep -q 'RuntimeKeyCallLogModel' "$ROOT/services/runtime_call_log.py"
grep -q 'ConsoleNoticeModel' "$ROOT/services/console_notice.py"
grep -q 'runtime_key_call_log' "$ROOT/db/migrations/versions/0050_runtime_key_calls_notices.py"
grep -q 'console_notices' "$ROOT/db/migrations/versions/0050_runtime_key_calls_notices.py"
# 行业硬指标表单：向导和配对接入必须共用同一份实现，不能各写一套。
grep -q 'karma-service-spec.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'KarmaServiceSpec' "$CONSOLE/scripts/cyber-agents.js"
grep -q 'KarmaServiceSpec' "$CONSOLE/scripts/cyber-pairing.js"
grep -q 'pages/cyber/index.html' "$CONSOLE/index.html"

# 节点层：操作台是静态的，「跟哪台节点说话」由用户自己选、自己换。
# 少任何一块，用户就又被绑死在一台机器上。
grep -q 'id="node-chip"' "$CONSOLE/pages/cyber/index.html"
grep -q 'id="node-menu"' "$CONSOLE/pages/cyber/index.html"
grep -q 'data-karma-nodes-settings' "$CONSOLE/pages/cyber/index.html"
grep -q 'KarmaNodes.effectiveBase' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'KarmaNodes.reportFailure' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'KarmaNodes.effectiveBase' "$CONSOLE/scripts/cyber-console.js"
# 交给 agent 的接入地址必须跟着选中的节点走，不能写死厂商域名。
grep -q 'function runtimeUrl(' "$CONSOLE/scripts/cyber-handoff.js"
grep -q 'function runtimeUrl(' "$CONSOLE/scripts/cyber-authorize.js"
! grep -q 'RUNTIME_URL = "https://karma-network.ai"' "$CONSOLE/scripts/cyber-handoff.js"
! grep -q 'RUNTIME_URL = "https://karma-network.ai"' "$CONSOLE/scripts/cyber-authorize.js"
# 分发层：静态包要有可复验的清单，发布脚本存在于仓库里。
[[ -f "$ROOT/scripts/console_bundle.py" ]]
[[ -f "$ROOT/scripts/publish_console_ipfs.sh" ]]

# L3-3：刷脸即激活 + 追加身份同人比对 + 动额度前过 2FA。
# 激活只剩刷脸：采集 / 加密 / 比对都在本机，服务端拿密文 + 摘要直接置「已激活」；
# 动钱的动作（加额 / 减额 / 取消授权、停用钥匙、取消绑定）都要过一次 6 位码。
grep -q 'cyber-face-vault.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'cyber-console-2fa.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'cyber-add-identity.js' "$CONSOLE/pages/cyber/index.html"
grep -q 'id="k2fa-card"' "$CONSOLE/pages/cyber/index.html"
grep -q 'id="idv-add-identity"' "$CONSOLE/pages/cyber/index.html"
grep -q 'id="mst-activate-status"' "$CONSOLE/pages/cyber/index.html"
grep -q 'activateByFace' "$CONSOLE/scripts/cyber-face-vault.js"
# IIFE 少了 window 参数就静默少一个模块（语法检查拦不住），这里钉结尾形状。
for mod in cyber-face-vault.js cyber-console-2fa.js cyber-add-identity.js; do
  tail -n 1 "$CONSOLE/scripts/$mod" | grep -q '})(window);'
done
grep -q 'confirmSamePerson' "$CONSOLE/scripts/cyber-add-identity.js"
grep -q 'KarmaFaceVault' "$CONSOLE/scripts/cyber-master-page.js"
grep -q 'Karma2FA' "$CONSOLE/scripts/karma-public-api.js"
grep -q 'X-Karma-2FA-Code' "$CONSOLE/scripts/karma-public-api.js"
# 服务端：额度入口与钥匙撤销 / 解绑都要复核验证码；两张新表要有迁移。
grep -q 'require_code' "$ROOT/api/routes/capacity.py"
grep -q 'require_code' "$ROOT/api/routes/runtime_gateway.py"
grep -q 'face-activate' "$ROOT/api/routes/identity_verification.py"
grep -q 'face-consistency' "$ROOT/api/routes/identity_role_profiles.py"
grep -q 'console_two_factors' "$ROOT/db/migrations/versions/0057_console_2fa_and_face.py"
grep -q 'def verify_code' "$ROOT/services/console_2fa.py"
grep -q 'def activate_by_face' "$ROOT/services/face_activation.py"

# L3-4：钥匙必须指名 agent（不记名钥匙整条路关掉）。铸钥匙少一个 agent 名字，
# 服务端就 400 —— 页面上那个框是唯一入口，掉了等于用户点不出钥匙。
grep -q 'id="ag-agent"' "$CONSOLE/pages/cyber/index.html"
grep -q 'agent_binding: f.agent' "$CONSOLE/scripts/cyber-actions.js"
grep -q 'agent_id: f.agent' "$CONSOLE/scripts/cyber-actions.js"
grep -q '已停用（不记名钥匙）' "$CONSOLE/scripts/cyber-handoff.js"
grep -q 'runtime_require_agent_binding' "$ROOT/config/settings.py"
grep -q 'require_agent_binding' "$ROOT/services/runtime_key_service.py"
grep -q 'require_agent_binding' "$ROOT/api/routes/runtime_gateway.py"
# agent 侧：申请接入 + 逐请求签名 + 等主人输码，三件工具缺一不可。
grep -q 'def karma_runtime_bind_key' "$ROOT/packages/karma-openclaw/karma_openclaw/runtime_tools.py"
grep -q 'def sign_runtime_request' "$ROOT/packages/karma-openclaw/karma_openclaw/agent_binding.py"

python3 -m pytest -q tests/unit/test_console_last_mile.py
python3 -m pytest -q tests/unit/test_console_2fa.py
python3 -m pytest -q tests/unit/test_face_activation.py
python3 -m pytest -q tests/unit/test_console_face_add_identity.py
python3 -m pytest -q tests/unit/test_console_nodes.py
# 身份核验页只剩三步 + 服务商通道没接入时要看得出是灰的。
python3 -m pytest -q tests/unit/test_console_verify_route.py
python3 -m pytest -q tests/unit/test_console_distribution.py

# Live HTTP write sequence matching the Cyber Console buttons (ASGI in-process).
python3 -m pytest -q tests/unit/test_console_live_write_smoke.py

if command -v node >/dev/null 2>&1; then
  # 语言包必须是能跑起来的 JS：pytest 那边只 grep 文本，包一旦写坏（少个逗号），
  # 切语言整页就会静默退回中文 —— 只有真的解析一遍才拦得住。
  for pack in "$CONSOLE"/scripts/i18n-phrase/*.js; do
    node --check "$pack"
  done
  for js in karma-public-api.js console-sync.js console-wallet-auth.js console-entry-gate.js cyber-actions.js cyber-authorize.js karma-service-spec.js cyber-pairing.js cyber-payments.js cyber-console.js cyber-orders.js cyber-order-flow.js cyber-identity.js cyber-identity-verify.js cyber-bind-requests.js cyber-unbind-keys.js cyber-reviews.js; do
    node --check "$CONSOLE/scripts/$js"
  done
  for js in karma-nodes.js cyber-node-panel.js cyber-handoff.js; do
    node --check "$CONSOLE/scripts/$js"
  done
  for js in cyber-face-vault.js cyber-console-2fa.js cyber-add-identity.js; do
    node --check "$CONSOLE/scripts/$js"
  done
  # 节点层的行为（选节点 / 探活 / 容灾 / 自定义节点校验）跑一遍真代码。
  node "$ROOT/tests/js/test_karma_nodes.cjs"
  # 每次请求都要有截止时间：没有它，选到一台连不通的节点会把整个操作台挂住。
  node "$ROOT/tests/js/test_console_fetch.cjs"

  # 真机验证（可选）：装了 playwright 才跑。开一个真实浏览器把节点层从头走一遍，
  # 没装就跳过 —— 上面那些检查已经覆盖了行为，这一支只是多一层「浏览器里真的行」。
  if node -e "require.resolve('playwright')" >/dev/null 2>&1; then
    node "$ROOT/tests/playwright/console_nodes_live.cjs"
    # 身份核验页：真浏览器里数一数几步、看一眼灰没灰、六门语言逐个切。
    node "$ROOT/tests/playwright/console_verify_route_live.cjs"
    # 复核台那句「打不开队列」：真浏览器里走一遍 403 再逐个语言比对（L3-2 之后重写过）。
    node "$ROOT/tests/playwright/console_reviews_copy_live.cjs"
    # 刷脸即激活 / 追加身份 / 动额度过 2FA：真浏览器里走一遍，六门语言逐字比对。
    node "$ROOT/tests/playwright/console_2fa_face_live.cjs"
  else
    echo "(skip) 没装 playwright：真机验证跳过（npm i -D playwright）"
  fi
fi

echo "OK   cyber console gate finished"
