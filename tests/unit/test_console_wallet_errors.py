"""连接钱包的失败必须「有话说」。

以前 signIn 抛网络类错误（跨域被拦 / 插件拦截 / 离线）时拿不到 HTTP 状态码，
状态栏就什么也不写，永远停在「获取登录挑战…」——用户看到的只是「点了没反应」。
这些断言把「任何一步失败都要有可见原因」钉住。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTH_JS = ROOT / "apps/console/scripts/console-wallet-auth.js"


def _src() -> str:
    return AUTH_JS.read_text(encoding="utf-8")


def _fn(name: str, end_marker: str) -> str:
    src = _src()
    start = src.index("function " + name)
    return src[start : src.index(end_marker, start)]


def test_network_failures_are_not_swallowed():
    src = _src()
    assert "function isNetworkError(" in src
    assert "function failText(" in src
    assert "function remember(" in src
    # 旧写法：只有拿得到 HTTP 状态码才提示，网络错误就静默。
    assert "if (e && e.status) {" not in _fn("connectWith", "function connect()"), (
        "connectWith 又会静默吞掉没有状态码的错误"
    )


def test_every_connect_step_reports_a_reason():
    sign_in = _fn("signIn", "function applyIdentityToUi")
    assert sign_in.count("setStatus(failText(") >= 2, "挑战/验签失败都要写状态栏"
    connect_with = _fn("connectWith", "function connect()")
    assert "setStatus(\"连接失败：" in connect_with
    assert "setStatus(\"钱包未返回账户\"" in connect_with or "钱包未返回账户" in connect_with


def test_network_error_message_names_the_api_origin():
    src = _src()
    block = src[src.index("function failText(") : src.index("function remember(")]
    assert "apiBase()" in block, "要告诉用户页面连不上哪个接口地址"
    assert "广告拦截" in block or "拦截" in block


def test_the_modal_offers_copyable_diagnostics():
    src = _src()
    assert "function diagLines(" in src
    assert "data-kw-diag" in src
    assert 'closest("[data-kw-diag]")' in src, "诊断按钮必须真的接到复制动作上"
    for key in ("页面：", "接口：", "检测到钱包：", "最近错误："):
        assert key in src


def test_desktop_empty_state_points_at_the_other_browser():
    src = _src()
    assert "插件只在自己安装的那个浏览器里生效" in src
    assert "请用那个浏览器打开本页" in src


def test_wallets_without_request_are_still_usable():
    """老插件只挂 sendAsync / send，没有 request，以前会被当成「没装钱包」。"""
    src = _src()
    legacy = _fn("legacyEntries", "function entries()")
    assert "asRequestProvider(" in legacy
    assert "typeof p.request === \"function\"" not in legacy, "判断要收进适配器里"
    # 适配器本身要把 jsonrpc 的错误翻成 Promise reject，并把 code 带出来
    adapter = src[src.index("function asRequestProvider(") : src.index("function legacyEntries(")]
    assert "typeof p.request === \"function\"" in adapter
    assert "sendAsync" in adapter, "必须接受只有 sendAsync 的老插件"
    assert "new Promise(" in adapter

    assert "res.error" in adapter
    assert "e.code = res.error.code" in adapter
    # 兜底出账：entries() 要按原始 provider 去重，避免同一个钱包出现两次
    entries_fn = _fn("entries", "function findEntryByName")
    assert "raw" in entries_fn, "适配后的 provider 是新对象，去重必须回到原始 provider"


def test_diagnostics_say_whether_the_extensions_exist_at_all():
    src = _src()
    diag = src[src.index("function diagLines(") : src.index("function b64(")]
    assert "window.ethereum" in diag, "要能看出页面里到底有没有插件注入"
    assert "页面环境：" in diag
    assert "内嵌" in diag


def test_desktop_empty_state_blames_the_environment_it_can_see():
    src = _src()
    assert "function pageContext(" in src
    ctx = src[src.index("function pageContext(") : src.index("function diagLines(")]
    assert "inIframe" in ctx
    assert "isSecureContext" in ctx
    empty = src[src.index("function emptyDesktopText(") : src.index("var CATALOG")]
    assert "内嵌" in empty, "被别的页面嵌着要单独说清楚"
    assert "内置浏览器" in empty, "桌面 App 内置浏览器装不了插件，要单独说清楚"


def test_connect_waits_for_a_late_injected_wallet():
    """刚装好插件的人，插件注入比脚本晚一点；先等一拍再报「没装钱包」。"""
    src = _src()
    start = src.index("function connect()")
    connect = src[start : src.index("function disconnect()", start)]
    assert "setTimeout(" in connect
    assert "eip6963:requestProvider" in connect
    assert "openModal()" in connect
