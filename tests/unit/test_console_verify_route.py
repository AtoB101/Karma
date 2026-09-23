"""身份核验页：两条通道要说清楚「走哪条」，核验本身只留三步。

这一页原来有两处让用户站着猜：

1. 「官方实名核验（服务商）」与「个人助理认证（人工复核）」两张卡并排摆着，
   没有一行字说该走哪条 —— 服务商没接入时那张卡还长得跟能用一样；
2. 核验流程被切成 5 段（① 证件 ② 刷脸 ③ 识别 ④ 本地加密 ⑤ 提交），
   其中「④ 本地加密」根本不是用户要做的一步，它只是提交那一刻发生的事。

现在的契约（静态可查，真机由 tests/playwright/console_verify_route_live.cjs 验）：

- 三步：① 证件 / ② 刷脸 / ③ 本地加密并提交；④⑤ 两段不再单独存在；
- 服务商通道：没接入或没配置齐 = 卡片 ``is-off`` 变灰 + ``aria-disabled="true"``；
- 人工复核那张卡在页头标出「当前路径 / 备用路径」，跟着服务商状态走；
- 两个被 JS 写过的状态位（``idv-enc-state`` / ``idv-send-state``）不能在折叠时弄丢。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
HTML = CONSOLE / "pages/cyber/index.html"
PROVIDER_JS = CONSOLE / "scripts/cyber-identity-provider.js"
CSS = CONSOLE / "styles/cyber-console.css"
PACK_DIR = CONSOLE / "scripts/i18n-phrase"
SHIPPED_LANGS = ("en", "ja", "ko", "es-AR", "es-SV")


def _verify_card() -> str:
    html = HTML.read_text(encoding="utf-8")
    start = html.index('id="idv-verify"')
    end = html.index("个体助理认证：个体工商户", start)
    return html[start:end]


def test_master_verification_is_three_steps():
    card = _verify_card()
    steps = [s for s in ('<li id="idv-step-doc">', '<li id="idv-step-face">', '<li id="idv-step-read">')]
    for step in steps:
        assert step in card, f"核验步骤缺 {step}"
    assert card.count('<li id="idv-step-') == 3, "主身份核验只留三步，多一个就又是那套五段流程"
    html = HTML.read_text(encoding="utf-8")
    assert 'id="idv-step-enc"' not in html, "「④ 本地加密」不再单独成段"
    assert 'id="idv-step-send"' not in html, "「⑤ 提交」不再单独成段"
    assert "<b>③ 本地加密并提交</b>" in card, "最后一步要说清是「加密并提交」，不是「识别」"


def test_the_two_status_bits_written_by_the_script_survive_the_fold():
    """JS 往这两个 span 里写「已加密 xx KB」「已提交」，折叠时弄丢就没人更新界面了。"""
    card = _verify_card()
    assert 'id="idv-enc-state"' in card
    assert 'id="idv-send-state"' in card
    js = (CONSOLE / "scripts/cyber-identity-verify.js").read_text(encoding="utf-8")
    assert 'byId("idv-enc-state")' in js
    assert 'byId("idv-send-state")' in js


def test_the_provider_card_greys_out_when_there_is_no_provider():
    js = PROVIDER_JS.read_text(encoding="utf-8")
    assert "function markRoute()" in js, "「走哪条」要由一个函数统一决定"
    assert 'card.classList.toggle("is-off", !on)' in js, "没接入服务商时那张卡要变灰"
    assert 'card.setAttribute("aria-disabled"' in js, "灰掉的同时要让读屏软件也知道"
    assert 'byId("idv-verify-route")' in js, "人工复核那张卡要标出当前/备用"
    assert 'on ? "备用路径" : "当前路径"' in js, "标法只有一份，别在两处各写一套"
    render = js.index("function render() {")
    assert "markRoute();" in js[render:render + 200], "每次渲染都要重新判定通道"


def test_the_page_carries_the_route_badge_and_the_grey_style():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="idv-verify-route"' in html, "页头要留出标「当前路径」的位置"
    css = CSS.read_text(encoding="utf-8")
    assert ".card.is-off" in css, "灰掉要有样式，不能只加个类名"


def test_every_language_pack_carries_the_route_copy():
    for lang in SHIPPED_LANGS:
        pack = (PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")
        for phrase in ("当前路径", "备用路径"):
            assert f'"{phrase}":' in pack, f"{lang} 缺译文：{phrase}"
