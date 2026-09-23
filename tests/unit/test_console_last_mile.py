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


def test_switching_identity_always_lands_on_that_identitys_page():
    """切身份 = 换页面：人在别的页面上切也要真的跟过去，侧栏也要有落点。

    两处一起坏过：``followIdentityPage()`` 先看「是不是已经在身份页」才肯翻页，
    人在账单页切身份就一动不动；侧栏「身份 · 认证」里又少了子身份那一项
    （``life`` 没有落点，高亮只能退回父项，看起来像没切成功）。
    """
    html = CYBER.read_text(encoding="utf-8")
    assert 'data-page="identity" data-sub="life"' in html, "侧栏缺子身份那一项，切过去没有落点"
    js = (CONSOLE / "scripts/cyber-identity.js").read_text(encoding="utf-8")
    block = re.search(r"function followIdentityPage\(\)\s*\{.*?\n  \}", js, re.S)
    assert block, "cyber-identity.js must keep followIdentityPage()"
    body = block.group(0)
    assert 'classList.contains("active")' not in body, "「不在身份页就不翻页」把切身份卡死了"
    assert 'cyberSwitchPage("identity"' in body, "切身份要落到这张身份自己那一页"
    # 点当前那张卡也要落页：刚建好的子身份自动就是当前身份，点了没反应像坏了一样。
    assert "if (r.id === active) return followIdentityPage();" in js
    # 侧栏那一项的文字要走源文案表：五份都得有，少一份就掉回中文。
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (CONSOLE / "scripts/i18n-phrase" / f"{lang}.js").read_text(encoding="utf-8")
        assert '"子身份 · 每个 agent 一张卡":' in pack, f"{lang} 缺侧栏子身份那一项的译文"


def test_pieced_together_identity_lines_translate_as_whole_sentences():
    """拼出来的句子要自己占一个文本节点，否则整句进不了文案表。

    实测（英文页面）：侧栏写着「hgf · 生活助理 · 挂在 kid1202884」，子身份行的
    「人脸 未采集」—— 两处都是中文。原因是源文案表只按「整个文本节点」查表：
    身份名和「挂在 …」挤在一个节点里就成了半句话，而「人脸 未采集」没有对应词条。
    """
    js = (CONSOLE / "scripts/cyber-identity.js").read_text(encoding="utf-8")
    assert 'identityTitle(p) + " · 挂在 "' not in js, "「挂在 {0}」要单独成节点，不能拼进身份名里"
    assert '"· 挂在 " + displayId(master, 0)' in js, "侧栏仍要写「· 挂在 {0}」这句原文"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (CONSOLE / "scripts/i18n-phrase" / f"{lang}.js").read_text(encoding="utf-8")
        assert '"· 挂在 {0}":' in pack, f"{lang} 缺「· 挂在 {{0}}」的译文"
        assert '"人脸 {0}":' in pack, f"{lang} 缺「人脸 {{0}}」的译文（子身份行会半中半英）"


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
        "展开「查看最近调用」可以看这把钥匙最近做了什么（含被拒的原因）；取消绑定是不可逆动作，做完会在操作台留一条站内提醒。",
        "查看最近调用",
        "收起最近调用",
        "正在读取调用记录…",
        "还没有调用记录。agent 用这把钥匙发起动作后，这里会逐条留下痕迹。",
        "最近调用记录（最新在前）",
        "动作 {0} · 结果 {1}{2}{3} · 时间 {4}",
        "成功",
        "被拒（HTTP {0}）",
        "异常（HTTP {0}）",
        " · 金额 {0} USDC",
        "站内提醒",
        "站内提醒（{0} 条未读）",
        "未读",
        "知道了（不再提醒）",
        "正在标记…",
        "取消绑定已完成：{0} 不能再代表你花钱，这把钥匙谁都花不了。",
        "接入已确认：{0} 现在可以在额度与权限内代表你花钱。",
        "标记已读失败：{0}",
        "读取调用记录失败：{0}",
        "接口未加载，请刷新页面后再试。",
        "有未读的钥匙提醒",
    )
    phrase_dir = CONSOLE / "scripts" / "i18n-phrase"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (phrase_dir / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"


def test_the_console_can_expand_a_bound_key_and_show_recent_calls():
    """「最近调用」把「额度花了多少」补成「哪一次花掉/被拒」。

    只给额度汇总时，主人看不到被拒的调用 —— 而那恰恰是「这个 agent 是不是在乱试」
    的唯一线索。所以卡片要能展开，服务端要有一条会话鉴权的逐条记录出口。
    """
    html = CYBER.read_text(encoding="utf-8")
    assert "展开「查看最近调用」" in html, "卡片要写明可以展开看调用记录"

    # 面板只有一份实现（cyber-key-calls.js），两处宿主共用：设置页那张卡片
    # + 交付包的密钥清单。各拼一套的话，改一处就静默失配。
    js = (CONSOLE / "scripts" / "cyber-key-calls.js").read_text(encoding="utf-8")
    for needle in ("runtimeKeyCalls", "key-calls", "data-key-calls", "CALL_LIMIT",
                   "KarmaKeyCalls", "buttonHtml", "panelHtml", "register"):
        assert needle in js, f"调用记录模块缺 {needle}"
    # 面板里那一行是拼出来的（带端点/时间），DOM 翻译引擎认不出整句：
    # 不在切语言时自己重画，就会把上一种语言的行留在英文页面上。
    assert "karma-lang-changed" in js, "切语言要重画面板，否则留上一种语言的残留"
    assert "rerenderAll" in js, "重画要走宿主注册的回调"

    unbind = (CONSOLE / "scripts" / "cyber-unbind-keys.js").read_text(encoding="utf-8")
    for needle in ("KarmaKeyCalls", "buttonHtml", "panelHtml"):
        assert needle in unbind, f"「一键取消绑定」卡片没接上面板：{needle}"

    handoff_js = (CONSOLE / "scripts" / "cyber-handoff.js").read_text(encoding="utf-8")
    for needle in ("KarmaKeyCalls", "keyCallsActions", "keyCallsPanel", "ag-key-item"):
        assert needle in handoff_js, f"交付包的密钥清单没接上面板：{needle}"

    assert 'src="../../scripts/cyber-key-calls.js"' in html, "页面必须加载共用面板模块"
    assert html.index("cyber-key-calls.js") < html.index("cyber-handoff.js"), (
        "面板模块要排在两个宿主前面，否则宿主拿不到 KarmaKeyCalls"
    )

    api = (CONSOLE / "scripts" / "karma-public-api.js").read_text(encoding="utf-8")
    for needle in ("runtimeKeyCalls", "runtimeListNotices", "runtimeAckNotice",
                   "/runtime/key-calls", "/runtime/list-notices", "/runtime/ack-notice"):
        assert needle in api, f"API 客户端缺 {needle}"

    css = (CONSOLE / "styles/cyber-console.css").read_text(encoding="utf-8")
    assert "#ag-bound-keys li" in css, "调用记录列表要可读，不能挤成一行"


def test_unbinding_leaves_a_console_notice_the_owner_must_ack():
    """取消绑定是不可逆动作：服务端落一条站内提醒，前端给出口 + 侧栏红点。

    邮件通道要 SMTP 凭据（现网没有），所以先用站内：关掉页面再回来仍然看得见，
    点过才消。
    """
    gateway = (ROOT / "api/routes/runtime_gateway.py").read_text(encoding="utf-8")
    for needle in ("NOTICE_KEY_UNBOUND", "NOTICE_KEY_BOUND", "_notice_safe", "unread_notice_count"):
        assert needle in gateway, f"网关缺站内提醒接线：{needle}"

    notice = (ROOT / "services/console_notice.py").read_text(encoding="utf-8")
    assert "ConsoleNoticeModel" in notice, "站内提醒要落到 ConsoleNoticeModel"
    assert "def notice_view(" in notice

    calls = (ROOT / "services/runtime_call_log.py").read_text(encoding="utf-8")
    assert "RuntimeKeyCallLogModel" in calls
    assert "def call_view(" in calls

    migrations = sorted((ROOT / "db/migrations/versions").glob("0050_*.py"))
    assert migrations, "新表要有迁移"
    mig = migrations[0].read_text(encoding="utf-8")
    for table in ("runtime_key_call_log", "console_notices"):
        assert table in mig, f"迁移缺 {table}"

    js = (CONSOLE / "scripts" / "cyber-unbind-keys.js").read_text(encoding="utf-8")
    for needle in ("runtimeListNotices", "runtimeAckNotice", "data-ack-notices", "paintNoticeDot"):
        assert needle in js, f"站内提醒前端缺 {needle}"

    css = (CONSOLE / "styles/cyber-console.css").read_text(encoding="utf-8")
    assert "has-notice" in css, "侧栏要有「有未读提醒」的红点样式"
    assert "#ag-bound-keys.attention" in css, "有未读提醒时卡片要跟着高亮"


def test_alembic_revision_ids_fit_the_version_column():
    """revision id 必须塞得进 alembic_version.version_num。

    alembic 自建这张表时把 version_num 定成 VARCHAR(32)，Postgres 严格执行宽度：
    超长的那一笔会在「盖章」时抛 StringDataRightTruncation —— 表全建完、事务回滚，
    部署卡在中间，看上去像「迁移写坏了」。文件名可以很长，revision id 不行。

    0043 之前的老迁移长度也超了，但它们早于线上 Postgres 基线（SQLite 不校验长度），
    所以只盯「Postgres 实际还会跑到」的这一段。0050 起这一列已放宽到 255。
    """
    versions = sorted((ROOT / "db/migrations/versions").glob("*.py"))
    blob = "\n".join(p.read_text(encoding="utf-8") for p in versions)
    cap = 255 if "version_num TYPE VARCHAR(255)" in blob else 32

    checked = 0
    too_long = {}
    for migration in versions:
        match = re.search(
            r'^revision\s*=\s*["\']([^"\']+)', migration.read_text(encoding="utf-8"), re.M
        )
        if not match or match.group(1)[:4] < "0043":
            continue
        checked += 1
        if len(match.group(1)) > cap:
            too_long[migration.name] = len(match.group(1))

    assert checked >= 8, "Postgres 基线之后的迁移至少要能被数到"
    assert not too_long, f"revision id 超过 {cap} 字符，线上写不进 alembic_version：{too_long}"


def test_every_language_pack_carries_the_review_queue_copy():
    """复核页「先连钱包」这段提示六种语言都要有。

    以前没连钱包就点进复核页，页面上会挂一句服务端原文
    「HTTP 401: Authentication required」：不是译文，也没说下一步做什么。
    现在没会话就不发请求，只在状态行留一句能翻的话。
    """
    samples = (
        "请先用右上角「连接钱包」完成认证，再来打开复核队列。",
        "还没认证：请先用右上角「连接钱包」完成认证。",
        "没有权限：这个身份还不是复核岗（verifier）。",
        # L3-2 之后复核岗有了第二条入口（质押即开通），这句提示必须跟着后端走；
        # 它还得是**一句话**，别拆成几段拼 —— 拼出来的句子查不到译表。
        (
            "这个身份还打不开复核队列：队列只对复核岗（verifier）开放。"
            "复核岗有两条路：平台点名开通，或者平台开放申请后用已锁仓的 USDC 质押开通"
            " —— 押金一走，这个岗就自动停。"
        ),
    )
    phrase_dir = CONSOLE / "scripts" / "i18n-phrase"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (phrase_dir / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"
        # 后端那句 403 换了措辞，语言包里的 key 也得跟着换 —— 否则它在页面上是中文原文。
        assert "GOVERNANCE_OPEN_JOIN" in pack, f"{lang} 里的治理岗提示还是旧措辞"

    js = (CONSOLE / "scripts" / "cyber-reviews.js").read_text(encoding="utf-8")
    assert "function authed()" in js, "复核页要先看会话再发请求"
    assert "if (!authed()) {" in js, "没会话就返回，别打裸 401"
    assert 'say(st, T("请先用右上角「连接钱包」完成认证，再来打开复核队列。"), null);' in js
    assert "status === 401" in js and "status === 403" in js, "状态行不要再摊服务端英文原文"
    # 这个文件是 (function () { ... })()，没有 global 形参：写成 global.KARMA_ACCESS_TOKEN
    # 会抛 ReferenceError，被 try/catch 吞掉之后永远判定「没连钱包」，连上也不再恢复。
    assert "global.KARMA_ACCESS_TOKEN" not in js, "cyber-reviews.js 里没有 global 形参，要用 window.*"


def test_every_language_pack_carries_the_agent_bound_key_copy():
    """钥匙必须指名 agent —— 这段文案六种语言都要有。

    L3-4 把「不记名钥匙」这条路整条关掉了：设置页多了一个 Agent ID 输入框，不填就
    铸不出钥匙；铸出来的钥匙是「未激活」，要 agent 申请接入 + 主人输 8 位匹配码才生效。
    语言包缺这几句，切语言立刻掉回中文。
    """
    samples = (
        "每把钥匙都要指名一个 agent：铸出来是「未激活」，agent 申请接入后拿到 8 位匹配码，你在下面「接入确认」里输码，它才能动钱。",
        "请填 Agent ID：每把钥匙都要指名一个 agent。不指名就等于铸一把不记名钥匙 —— 谁捡到谁能花，所以这条路已经关掉了。",
        "已停用（不记名钥匙）",
    )
    phrase_dir = CONSOLE / "scripts" / "i18n-phrase"
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (phrase_dir / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"

    html = CYBER.read_text(encoding="utf-8")
    assert 'id="ag-agent"' in html, "设置页要有 Agent ID 输入框"
    js = (CONSOLE / "scripts/cyber-actions.js").read_text(encoding="utf-8")
    assert "agent_binding: f.agent" in js, "铸钥匙要把 agent 名字写进钱包签名消息"
    assert "agent_id: f.agent" in js, "铸钥匙要指名 agent（服务端会 400 拦下来）"
    handoff = (CONSOLE / "scripts/cyber-handoff.js").read_text(encoding="utf-8")
    assert '"service"' in handoff and "已停用（不记名钥匙）" in handoff, "存量不记名钥匙要标出来"
