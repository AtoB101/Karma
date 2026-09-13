"""操作台主流程：先连钱包 → 主身份 → 锁仓 / 减少锁仓 → 子身份。

这一组是静态接线检查（页面 + 脚本），真正的行为验证在浏览器里做；
放在这里是为了让「用户第一眼看到什么」这件事有回归保护，
别下次改版又把入口门禁或者减少锁仓的占用检查删掉了。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
HTML = CONSOLE / "pages/cyber/index.html"
GATE_JS = CONSOLE / "scripts/console-entry-gate.js"
CONSOLE_JS = CONSOLE / "scripts/cyber-console.js"
IDENTITY_JS = CONSOLE / "scripts/cyber-identity.js"
AUTH_JS = CONSOLE / "scripts/console-wallet-auth.js"
CSS = CONSOLE / "styles/cyber-console.css"


def test_console_requires_a_wallet_before_showing_the_desk():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="entry-gate"' in html, "操作台必须先有一道连接钱包的入口门"
    assert "连接钱包，进入操作台" in html
    assert "不会接触你的私钥" in html, "门禁上要说清不碰私钥"

    js = GATE_JS.read_text(encoding="utf-8")
    assert "console-entry-gate.js" in html, "门禁脚本必须被页面加载"
    for evt in (
        "karma-wallet-connected",
        "karma-session-restored",
        "karma-wallet-disconnected",
        "karma-session-expired",
    ):
        assert evt in js, f"门禁必须跟着 {evt} 走"
    assert 'classList.add("gated")' in js and 'classList.remove("gated")' in js
    # 失败开放：没有 JS 时不加 .gated，操作台照常可见，不会白屏。
    assert "body.gated .app" in CSS.read_text(encoding="utf-8")


def test_first_screen_shows_who_you_are_and_how_much_is_locked():
    html = HTML.read_text(encoding="utf-8")
    for needle in (
        'id="id-home"',
        'id="id-home-master"',
        'id="id-home-wallet"',
        'id="btn-switch-identity"',
        'id="btn-reduce-lock"',
        'id="lock-amount"',
        'data-action="lock-capacity"',
        'data-lock-preset="50"',
        'id="id-home-subs"',
    ):
        assert needle in html, f"主身份抬头卡缺少 {needle}"
    assert html.index('id="id-home"') < html.index('class="grid metrics"'), (
        "主身份抬头要在总览第一屏，而不是埋在下半页"
    )


def test_display_ids_are_kid1_for_the_master_and_kid02_for_subs():
    js = IDENTITY_JS.read_text(encoding="utf-8")
    block = js[js.index("function displayId(") : js.index("window.KarmaDisplayId")]
    assert '"Kid1"' in block, "主身份要显示成 Kid1 开头"
    assert '"kid" + (n < 10 ? "0" + n : String(n))' in block, "子身份要显示成 kid02 / kid03"
    assert "digitSeed" in js, "6 位数字要由真 ID 推导，刷新后不变"
    assert "window.KarmaDisplayId" in js
    # 顶栏那个身份芯片也要用显示编号，不能继续吐 kid_ 十六进制。
    auth = AUTH_JS.read_text(encoding="utf-8")
    assert "chip.textContent = identityId ? displayId(identityId) : \"未连接\"" in auth


def test_less_lock_is_refused_while_orders_hold_the_money():
    js = CONSOLE_JS.read_text(encoding="utf-8")
    block = js[js.index("async function reduceLockAction()") : js.index("function bindIdentityHome()")]
    assert "reserved" in block and "reducible" in block, "减少锁仓要先扣掉订单占用"
    assert "请在订单执行结算后再减仓" in block, "占用中要告诉用户为什么减不了"
    assert "confirm-warn" in block
    plan = js[js.index("function planReduce(") : js.index("function renderReduceConfirm(")]
    assert "sort(function (a, b) { return a.free - b.free; })" in plan, (
        "合约只能整笔撤销：从最小的开始凑，溢出最少"
    )
    assert "onchainEscrowRevoke" in js[js.index("async function runReduce(") : js.index("async function reduceLockAction()")]


def test_numbers_land_on_every_card_that_shows_them():
    js = CONSOLE_JS.read_text(encoding="utf-8")
    block = js[js.index("map.forEach(function (row) {") : js.index("/* 刷新完直接把数字写出来")]
    assert "document.querySelectorAll(row[0])" in block, "同一个数字挂在多张卡上时要全部更新"
    sync = (CONSOLE / "scripts/console-sync.js").read_text(encoding="utf-8")
    assert "nodes.forEach(function (n) { n.textContent = value; });" in sync