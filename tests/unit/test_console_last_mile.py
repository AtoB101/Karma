"""Console: the public web surface is the Cyber Console (apps/console/pages/cyber/)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
CYBER = CONSOLE / "pages/cyber/index.html"
I18N = CONSOLE / "scripts/i18n-cyber.js"
CONSOLE_JS = CONSOLE / "scripts/cyber-console.js"

LEGACY_PAGES = (
    "pages/dashboard.html",
    "pages/mvvs-dashboard.html",
    "pages/bilateral-status.html",
    "pages/openclaw-connect.html",
    "pages/security-funds.html",
    "pages/verifier-explorer.html",
    "pages/agents/index.html",
    "pages/disputes/index.html",
    "pages/evidence/index.html",
    "pages/payments/index.html",
    "pages/receiving/index.html",
    "pages/settings/index.html",
    "pages/trade/index.html",
)


def test_karma_public_api_exports_write_helpers():
    text = (CONSOLE / "scripts/karma-public-api.js").read_text(encoding="utf-8")
    for name in (
        "settlementLock",
        "settlementBuyerAccept",
        "settlementDispute",
        "createPaymentCode",
        "launchTradeOrder",
        "tradeLaunchSigningPreview",
        "lockCapacity",
    ):
        assert name in text, f"missing karmaPublicApi helper {name}"


def test_karma_public_api_resolves_same_origin_base():
    text = (CONSOLE / "scripts/karma-public-api.js").read_text(encoding="utf-8")
    assert "karmaResolveApiBase" in text
    # an explicitly empty base must survive as "" (same origin), not fall back to localhost
    assert 'raw === undefined || raw === null' in text


def test_legacy_console_pages_are_gone():
    for rel in LEGACY_PAGES:
        assert not (CONSOLE / rel).exists(), f"legacy console page still present: {rel}"


def test_cyber_console_is_the_only_ui():
    html = CYBER.read_text(encoding="utf-8")
    assert "../../styles/cyber-console.css" in html
    assert "../../scripts/karma-public-api.js" in html
    for gone in ("console-actions.js", "console-bootstrap.js", "console-trade.js", "dashboard.js"):
        assert gone not in html, f"cyber console still loads removed script: {gone}"


def test_index_redirects_to_cyber_console():
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    assert "pages/cyber/index.html" in html


def _shipped_langs():
    """Languages i18n-cyber.js is willing to advertise in the picker."""
    match = re.search(r"SHIPPED_LANGS\s*=\s*\[([^\]]*)\]", I18N.read_text(encoding="utf-8"))
    assert match, "i18n-cyber.js must declare SHIPPED_LANGS"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_language_picker_lists_exactly_the_shipped_langs():
    """A language may only be offered when its pack renders the whole page.

    ja/ko/es/fr/de/pt-BR keep partial packs (32 of 224 keys), so older builds
    listed them while the page stayed English. The HTML fallback and the runtime
    list must agree, otherwise the drift comes back.
    """
    html = CYBER.read_text(encoding="utf-8")
    select = re.search(r'<select id="cyberLang".*?</select>', html, re.S)
    assert select, "the console lost its language picker"
    options = re.findall(r'<option value="([^"]+)"', select.group(0))
    assert options == _shipped_langs()


def test_language_picker_labels_come_from_the_pack_registry():
    text = I18N.read_text(encoding="utf-8")
    block = re.search(r"const LANG_LABELS\s*=\s*\{(.*?)\n  \};", text, re.S)
    assert block, "i18n-cyber.js must declare LANG_LABELS"
    for code in _shipped_langs():
        key = re.escape(code)
        assert re.search(r'(?:"%s"|%s)\s*:' % (key, key), block.group(1)), f"missing label for {code}"
    js = CONSOLE_JS.read_text(encoding="utf-8")
    assert "SHIPPED_LANGS" in js, "the picker must read SHIPPED_LANGS, not a local copy"
    assert "LANG_LABELS" in js, "the picker must read LANG_LABELS, not a local copy"


def test_identity_card_translates_the_ledger_enums():
    """The card used to print identity_class: "user" and verification_status raw.

    Those are ledger words (user/business/agent, unverified/basic/enhanced) and
    are not the public role-profile list, so the card showed a value that matched
    nothing else in the product.
    """
    js = (CONSOLE / "scripts/cyber-identity.js").read_text(encoding="utf-8")
    for cls in ("user", "business", "agent"):
        assert re.search(r"\b%s:\s*\"" % cls, js), f"card view must label identity_class {cls}"
    for state in ("unverified", "basic", "enhanced"):
        assert re.search(r"\b%s:\s*\"" % state, js), f"card view must label verification_status {state}"
    assert "card.identity_class ||" not in js, "the card still prints the raw identity_class"
    assert "card.verification_status ||" not in js, "the card still prints the raw verification_status"


def test_agent_handoff_panel_exists():
    """The 交付包 is what an owner hands to an agent: env + runtime key + checks."""
    html = CYBER.read_text(encoding="utf-8")
    assert "../../scripts/cyber-handoff.js" in html, "the console must load the handoff module"
    assert 'id="ag-handoff-card"' in html, "the console must render a handoff panel"
    js = (CONSOLE / "scripts/cyber-handoff.js").read_text(encoding="utf-8")
    for needle in (
        "data-agent-handoff",
        "KARMA_AGENT_ID",
        "KARMA_API_KEY",
        "KARMA_RUNTIME_URL",
        "KARMA_RUNTIME_KEY",
        "p1-status",
        "ownerRevokeAgent",
    ):
        assert needle in js, f"the handoff module is missing {needle}"
    # The Runtime Key signature must be rebuilt the way Python formats floats and
    # UTC timestamps, otherwise the mint 403s (see the same fix in cyber-actions).
    assert "pyFloatStr" in js and "pyUtcIso" in js
    agents = (CONSOLE / "scripts/cyber-agents.js").read_text(encoding="utf-8")
    assert "data-agent-handoff" in agents, "every onboarded agent needs a 交给 agent button"


def test_bills_page_exposes_the_sub_identity_view():
    """主身份总账 ↔ 子身份明细：records stay separate, the sum stays one card."""
    html = CYBER.read_text(encoding="utf-8")
    assert 'id="bill-scope"' in html, "the bills page needs a 视角 selector"
    assert 'id="bill-ledger"' in html, "the bills page needs a per-profile ledger host"
    js = (CONSOLE / "scripts/cyber-actions.js").read_text(encoding="utf-8")
    for needle in ("listRoleProfiles", "getProfileLedger", "getAllocations", "#bill-ledger"):
        assert needle in js, f"the bills view is missing {needle}"
    # The per-profile numbers come from the allocation rows, not from arithmetic on
    # the master row, so a sub-identity can never show the master's balance.
    assert "allocated_credits" in js and "in_progress_credits" in js


def test_sub_identity_scope_has_a_single_source_of_truth():
    """One switcher drives every surface: switcher → bills → tasks → receipts.

    The console used to keep a sidebar switcher, a bills dropdown and a topbar
    button that each wrote their own state, so "which identity am I acting as"
    had no single answer. The topbar now always names the master card and the
    active view, and the same scope object answers for every module.
    """
    html = CYBER.read_text(encoding="utf-8")
    for node in ('id="sub-scope-bar"', 'id="sub-scope-master"', 'id="sub-scope-active"',
                 'id="btn-switch-sub"', 'id="sub-switch-panel"'):
        assert node in html, f"the topbar is missing {node}"

    identity_js = (CONSOLE / "scripts/cyber-identity.js").read_text(encoding="utf-8")
    assert "window.KarmaIdentitySwitcher" in identity_js
    for name in ("getActiveProfileId", "setActiveProfileId", "getProfiles"):
        assert name in identity_js, f"the switcher must expose {name}"

    # The bills dropdown is the same scope as the sidebar/topbar selector.
    actions = (CONSOLE / "scripts/cyber-actions.js").read_text(encoding="utf-8")
    assert "KarmaIdentitySwitcher" in actions
    # 回执 also obeys the scope instead of leaking another sub-identity's rows.
    assert "listReceiptsForTask" in actions and "getSettlement" in actions

    # Task/dispute filters are strict: unattributed rows stay with the master card.
    sync = (CONSOLE / "scripts/console-sync.js").read_text(encoding="utf-8")
    assert "s.profile_id !== apid" in sync
    assert "data-profile-scope-note" in sync

    # The master id is known the moment SIWE returns, so it must be drawn before
    # the protected profile read — otherwise the bar lags the 已连接 status.
    block = re.search(r"async function refresh\(\)\s*\{.*?\n  \}", identity_js, re.S)
    assert block, "cyber-identity.js must keep its refresh()"
    body = block.group(0)
    assert body.index("renderScopeBar") < body.index("listRoleProfiles")
    # 额度分配 is built from the profile list, so it must be rebuilt whenever
    # that list changes; a new sub-identity otherwise had no row to type into.
    assert body.count("refreshAllocation") >= 2, "refresh() must rebuild the allocation rows"


def test_capacity_release_stays_a_master_operation():
    """POST /capacity/{id}/release only stamps the master row and moves master
    credits; a sub-identity's quota moves with PUT /allocations. Sending a
    profile_id therefore released the wrong pool, so the client never sends one
    and refuses the action while a sub-identity scope is active."""
    text = (CONSOLE / "scripts/karma-public-api.js").read_text(encoding="utf-8")
    for fn in ("lockCapacity", "releaseCapacity"):
        block = re.search(r"async function %s\(.*?\n  \}" % fn, text, re.S)
        assert block, f"missing {fn}"
        assert "profile_id" not in block.group(0), f"{fn} must not send profile_id"
    console = (CONSOLE / "scripts/cyber-console.js").read_text(encoding="utf-8")
    assert "activeProfileId" in console, "释放 must refuse to run in a sub-identity view"


def test_locking_and_allocating_are_one_click_after_siwe():
    """连接钱包后：锁仓有快捷金额，额度分配有剩余额度和一键按钮。

    Both writes resolve their actor from the SIWE bearer token alone
    (POST /v1/capacity/{id}/lock and PUT /v1/capacity/{id}/allocations), so the
    console can finish either one from a single click — no second signature and
    no second screen. The 起步引导 is what tells the owner the two moves exist.
    """
    html = CYBER.read_text(encoding="utf-8")
    assert 'id="lock-amount"' in html, "the manual amount box must stay"
    assert 'data-lock-preset="50"' in html and 'data-lock-preset="100"' in html
    assert 'id="launch-guide"' in html, "the owner needs a next-step card right after SIWE"
    for step in ("launch-lock-state", "launch-alloc-state", "launch-sdk-state"):
        assert step in html, f"the guide is missing {step}"

    console = CONSOLE_JS.read_text(encoding="utf-8")
    assert "data-lock-preset" in console, "快捷锁仓 chips must be wired"
    assert "lockPreset" in console and "renderLaunchGuide" in console
    for name in ("karma-wallet-connected", "karma-session-restored", "karma-capacity-changed"):
        assert name in console, "the guide must follow the session, not a manual refresh"
    # A preset click must lock by itself, so the amount has to reach the action.
    assert "lockCapacityAction(amountOverride)" in console
    # SIWE auto-creates the card's own ledger agent. Counting it made step 3 read
    # 「1 个 agent 已接入」the moment the wallet connected.
    assert "a.agent_id !== a.owner_identity_id" in console, "自身台账 agent 不算已接入"
    # The guide counts onboarded agents, so onboarding has to tell it to re-read.
    assert "karma-agent-connected" in console, "the guide must refresh when an agent is onboarded"
    agents = (CONSOLE / "scripts/cyber-agents.js").read_text(encoding="utf-8")
    assert "karma-agent-connected" in agents, "onboarding must announce the new agent"

    identity = (CONSOLE / "scripts/cyber-identity.js").read_text(encoding="utf-8")
    assert "pm-alloc-remain" in identity, "额度分配 must show the remaining quota"
    assert "pm-alloc-even" in identity and "pm-alloc-clear" in identity
    assert "allocRemaining" in identity
    # The form is submitted as a whole snapshot: an emptied row has to be sent as
    # 0, otherwise the server keeps its old quota and 清零 silently does nothing.
    assert "? v : 0" in identity, "empty allocation rows must be submitted as 0"
    assert "sub-switch-grant" in identity and "focusAllocRow" in identity, "子身份面板 needs 一键授权"

    css = (CONSOLE / "styles/cyber-console.css").read_text(encoding="utf-8")
    assert ".lock-quick .chip" in css and ".sub-switch-grant" in css


def test_the_lock_card_shows_what_the_chain_can_actually_move():
    """「已授权额度 170」不等于「能划走 170」：同一个钱包的账单共用一条 ERC-20 授权。

    ``/v1/escrow/{id}`` 现在带 ``backing``（secured / unsecured / chain_checked），
    操作台必须把「真划得动」和「还没担保」分开说 —— 否则用户下单被 409 拒掉时，
    页面上还写着「已授权额度 170」，没人知道问题出在哪。
    """
    console = CONSOLE_JS.read_text(encoding="utf-8")
    assert "escrow.backing" in console, "锁仓卡要读链上担保口径"
    assert "backing.chain_checked" in console, "读不到链时不能把担保说成 0"
    assert "可划动" in console and "未担保" in console
    assert "额度不足（钱包余额或授权不足）" in console, "单张账单的旧提示要保留"


def test_the_console_prompts_for_the_activation_code_from_settings():
    """匹配码激活的入口不能藏在某个 agent 的交付包里。

    agent 申请绑定公钥后，主人要做的事只有一件：把 agent 显示的那串码抄进来 + 钱包签名。
    以前这只有点开「交付包」才看得到，等于没提示 —— 所以「设置」页现在常驻一张
    「接入确认」卡片，另有侧栏红点和一次弹窗把人叫过来。
    """
    html = CYBER.read_text(encoding="utf-8")
    assert 'id="ag-bind-requests"' in html, "设置页要有接入确认卡片"
    assert 'id="bind-requests"' in html, "卡片里要留出渲染待确认请求的位置"
    assert 'id="btn-bind-refresh"' in html, "要有手动刷新按钮"
    assert "cyber-bind-requests.js" in html, "页面必须加载这个模块"
    # 签名消息只有一份实现：新模块必须排在 cyber-handoff.js 之后并复用它。
    assert html.index('src="../../scripts/cyber-handoff.js"') < html.index(
        'src="../../scripts/cyber-bind-requests.js"'
    ), "新模块要排在 cyber-handoff.js 之后才有 KarmaHandoff 可用"

    js = (CONSOLE / "scripts/cyber-bind-requests.js").read_text(encoding="utf-8")
    for needle in (
        "runtimeListPendingBinds",
        "list-pending-binds",
        "KarmaHandoff",
        "buildConfirmBindMsg",
        "buildRejectBindMsg",
        "has-pending",
        "bind-modal",
        "personal_sign",
    ):
        assert needle in js, f"接入确认模块缺 {needle}"
    # 服务端按同一格式重建签名消息：这里再拼一套，两边改一处就静默失配。
    assert "Karma Runtime Key Bind Confirm" not in js
    assert "Karma Runtime Key Bind Reject" not in js
    # 看一眼提示不该惊动钱包：轮询走会话鉴权，签名只在点确认/拒绝时发生。
    assert '"/runtime/confirm-bind-key"' not in js, "取数用会话版，别再打钱包签名版"

    handoff = (CONSOLE / "scripts/cyber-handoff.js").read_text(encoding="utf-8")
    for exported in ("normalizeCode", "buildConfirmBindMsg", "buildRejectBindMsg", "walletProvider"):
        assert exported + ":" in handoff, f"KarmaHandoff 要出口 {exported}"

    css = (CONSOLE / "styles/cyber-console.css").read_text(encoding="utf-8")
    assert ".nav .nav-main.has-pending" in css and ".bind-modal" in css


def test_every_language_pack_carries_the_activation_code_copy():
    """六种语言都要有这一段的文案，否则切语言立刻掉回中文。"""
    samples = (
        "接入确认 · 匹配码",
        "刷新待确认请求",
        "连接钱包后，这里会显示待确认的接入请求。",
        "暂无待确认的接入请求。agent 申请接入后会出现在这里。",
        "正在读取待确认请求…",
        "读取待确认请求失败：{0}",
        "有待确认的接入请求",
        "申请接入的 agent：{0}",
        "有 {0} 个 agent 正在申请接入这把密钥（还没生效）",
        "有 {0} 个接入申请已经过期（匹配码 3 分钟有效）：让 agent 重新申请一次，会把新的匹配码给你。",
        "输入 agent 显示的匹配码",
        "有 agent 在申请接入",
        "去输入匹配码",
        "稍后处理",
        "签名模块未加载，请刷新页面后再试。",
        "已确认绑定，这个 agent 之后每个请求都要私钥签名。",
    )
    phrase_dir = CONSOLE / "scripts" / "i18n-phrase"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (phrase_dir / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"

def test_a_key_minted_for_an_agent_is_marked_not_activated_in_the_handoff():
    """铸造给 agent 的钥匙在操作台要标成「未激活」，不能让人以为铸完就能花。

    服务端把这种钥匙停在 ``agent_pending``：没输匹配码之前，动钱的调用一律 403。
    操作台不把这件事说出来，用户就会以为是 agent 坏了。
    """
    handoff = (CONSOLE / "scripts/cyber-handoff.js").read_text(encoding="utf-8")
    assert "activation_required" in handoff, "交付包要读服务端的激活标记"
    assert "activationHintText" in handoff, "未激活提示要单独成句（拼进 note 会翻不到）"
    assert "未激活（等匹配码）" in handoff, "密钥列表要标出未激活"
    assert "activation_deadline" not in handoff, "时限只在匹配码上，钥匙本身不该有激活期限"
    assert "匹配码 3 分钟内有效" in handoff, "要说清匹配码只有 3 分钟"
    assert "state.activationHint = \"\";" in handoff, "切换 agent 时要清掉上一把钥匙的提示"

    # 配对交付卡铸的是同一类钥匙（agent_binding 非空），文案也得说清楚未激活。
    pairing = (CONSOLE / "scripts/cyber-pairing.js").read_text(encoding="utf-8")
    assert "activation_deadline" not in pairing, "配对卡也不写激活期限（只有匹配码 3 分钟）"
    assert "匹配码 3 分钟内有效" in pairing, "配对卡要说清匹配码只有 3 分钟"
    assert "这把钥匙在激活之前动不了钱" in pairing


def test_the_backend_locks_keys_that_are_minted_for_an_agent():
    """铸造 → 激活这段窗口期不能是不记名令牌：网关必须先拒。

    这是「盗 key 也花不出钱」的一半 —— 另一半是绑定后的逐请求验签。
    """
    root = CONSOLE.parent.parent  # apps/console -> apps -> repo root
    service = (root / "services/runtime_key_service.py").read_text(encoding="utf-8")
    gateway = (root / "api/routes/runtime_gateway.py").read_text(encoding="utf-8")

    assert 'PENDING_KEY_BINDING = "agent_pending"' in service
    assert "ACTIVATION_WINDOW_SECONDS" not in service, "钥匙本身不该再有激活期限"
    assert "BIND_CODE_TTL_SECONDS = 180" in service, "时限只在匹配码上：3 分钟"
    assert "def unbind_key_binding(" in service, "一键取消绑定要有服务端实现"
    assert "def list_bound_runtime_keys(" in service
    assert "def pending_activation_block(" in service, "拒用判定要只有一个口径"
    # 铸造时指给 agent 的钥匙落到未激活位
    assert "if binding_mode == \"service\" and (agent_binding or \"\").strip():" in service

    assert "pending_activation_block(" in gateway, "网关要用这套判定"
    assert "PENDING_ACTIVATION_ALLOWED_PATHS" in gateway
    # 只放行「读自己状态」，动作端点必须拦
    assert '"/runtime/permissions"' in gateway
    assert "status_code=403, detail=blocked" in gateway
    assert "activation_required" in gateway
    assert "activation_deadline" not in gateway, "激活期限已经从回执里删掉"
    assert "unbind_key_binding(" in gateway, "一键取消绑定要落在网关上"
    assert "list_bound_runtime_keys(" in gateway


def test_every_language_pack_carries_the_not_activated_copy():
    """未激活那几句话六种语言都要有，否则切语言立刻掉回中文。"""
    samples = (
        "未激活（等匹配码）",
        "这把钥匙现在还没激活：没走完这一步，谁都拿它花不了钱。",
        "第一次动用这把钥匙的钱之前，agent 会申请绑定自己的公钥并把 8 位匹配码给你；"
        "你到「设置 → 接入确认」输码 + 钱包签名确认，它才能真正付款（在那之前一律被拒）。",
        "这把钥匙还没激活，现在不能动钱。agent 用 /runtime/bind-key 申请接入后会把 8 位匹配码给你，"
        "你到「设置 → 接入确认」输码 + 钱包签名确认之后它才生效；匹配码 3 分钟内有效，"
        "过期就让 agent 重新申请一次（钥匙不用重铸）。",
        "这把钥匙在激活之前动不了钱：agent 领取时会申请绑定公钥，把 8 位匹配码给你；"
        "你在「设置 → 接入确认」输码 + 钱包签名确认之后它才生效。匹配码 3 分钟内有效，"
        "过期就让 agent 重新申请一次，钥匙不用重铸。",
    )
    phrase_dir = CONSOLE / "scripts" / "i18n-phrase"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (phrase_dir / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack and f'"{s}":' not in pack.replace("\\", "\\")]
        assert not missing, f"{lang} 缺译文：{missing}"

def test_the_console_can_unbind_an_agent_from_settings():
    """接入确认管「进得来」，一键取消绑定管「退得掉」—— 两个出口都得在设置页。

    钥匙绑上 agent 公钥之后就一直在代表主人花钱。没有这个按钮，用户唯一的出路是吊销
    整把钥匙；服务端 ``/runtime/unbind-key`` 摘掉公钥让钥匙回到「未激活」，
    ``/runtime/list-bound-keys`` 走会话鉴权把「现在谁在代表我花钱」列出来。
    """
    html = CYBER.read_text(encoding="utf-8")
    assert 'id="ag-bound-keys"' in html, "设置页要有「已授权 · 一键取消绑定」卡片"
    assert 'id="bound-keys"' in html, "卡片里要留出渲染位置"
    assert 'id="btn-bound-refresh"' in html, "要有手动刷新按钮"
    assert "cyber-unbind-keys.js" in html, "页面必须加载这个模块"
    assert html.index('src="../../scripts/cyber-handoff.js"') < html.index(
        'src="../../scripts/cyber-unbind-keys.js"'
    ), "新模块要排在 cyber-handoff.js 之后才有 KarmaHandoff 可用"

    js = (CONSOLE / "scripts" / "cyber-unbind-keys.js").read_text(encoding="utf-8")
    for needle in (
        "runtimeListBoundKeys",
        "list-bound-keys",
        "runtimeUnbindKey",
        "KarmaHandoff",
        "buildUnbindKeyMsg",
        "data-unbind-key",
        "personal_sign",
    ):
        assert needle in js, f"取消绑定模块缺 {needle}"
    # 看一眼列表不该惊动钱包：取数走会话版，签名只在点「取消绑定」时发生。
    assert '"/runtime/list-bind-requests"' not in js, "取数用会话版，别再打钱包签名版"
    # 签名消息只有一份实现（服务端按同一格式重建）：这里再拼一套就静默失配。
    assert "Karma Runtime Key Unbind" not in js

    api = (CONSOLE / "scripts" / "karma-public-api.js").read_text(encoding="utf-8")
    for needle in ("runtimeListBoundKeys", "runtimeUnbindKey", "/runtime/list-bound-keys", "/runtime/unbind-key"):
        assert needle in api, f"API 客户端缺 {needle}"

    handoff = (CONSOLE / "scripts" / "cyber-handoff.js").read_text(encoding="utf-8")
    assert "buildUnbindKeyMsg: buildUnbindKeyMsg" in handoff, "KarmaHandoff 要出口取消绑定的签名消息"
    assert "Karma Runtime Key Unbind" in handoff, "签名串要和 services/runtime_wallet.py 对齐"

    css = (CONSOLE / "styles/cyber-console.css").read_text(encoding="utf-8")
    assert "#ag-bound-keys" in css, "新卡片要有自己的样式"


def test_every_language_pack_carries_the_unbind_copy():
    """取消绑定那一整段六种语言都要有，否则切语言立刻掉回中文。"""
    samples = (
        "已授权 · 一键取消绑定",
        "刷新已绑定的钥匙",
        "连接钱包后，这里会显示已经绑定 agent 的钥匙。",
        "正在读取已绑定的钥匙…",
        "暂时没有绑定 agent 的钥匙。agent 申请接入、你在「接入确认」输码确认之后，它才会出现在这里。",
        "已绑定 agent、正在代表你花钱的钥匙：{0} 把",
        "正在代表你花钱的 agent：{0}",
        "公钥指纹：{0} · 单笔上限 {1} USDC · 每日上限 {2} USDC · 到期 {3}",
        "权限：{0}",
        "钥匙 ID：{0}",
        "取消绑定（要钱包签名）",
        "取消绑定失败：{0}",
        "取消绑定后，这个 agent 立刻不能再代表你花钱（这把钥匙谁都花不了）。要用就让 agent 重新申请一次接入。确定吗？",
        "已取消绑定：这把钥匙回到「未激活」，agent 想再花钱得重新申请一次接入。",
    )
    phrase_dir = CONSOLE / "scripts" / "i18n-phrase"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (phrase_dir / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"
