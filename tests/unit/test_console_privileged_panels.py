"""操作台的三个特权工作面：仲裁台（arbitration）、验证者网络（verifiers）与复核台（reviews）。

它们只对白名单里的人开放，所以前端要做对三件事：

* 入口按 ``/v1/console/capabilities`` 位显隐 —— 不在名单里就整组不画；
* 取数前先看会话，没会话不发请求（发出去只有一条裸 401）；
* **不能**靠「打真接口、看到 403 再藏」：那会让每个普通用户每开一次操作台就往
  安全告警的 ``privileged_action`` 基线里塞一串 403，把真信号淹掉。

判定权威始终在后端（services/actor_guards.py 那三道 require_*）—— 前端少画一个
按钮不算安全，多画一个按钮也过不去。这里钉的是前端的体面与口径一致。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
SCRIPTS = CONSOLE / "scripts"
PAGE = CONSOLE / "pages/cyber/index.html"
BOOT = SCRIPTS / "cyber-console.js"
CSS = CONSOLE / "styles" / "cyber-console.css"
PACK_DIR = SCRIPTS / "i18n-phrase"
SHIPPED_LANGS = ("en", "ja", "ko", "es-AR", "es-SV")

CJK = re.compile(r"[\u4e00-\u9fff]")
JS_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
PACK_ENTRY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:', re.M)

PANELS = {
    "arbitration": {
        "js": "cyber-arbitration.js",
        "cap": "can_operate_arbitration",
        "subs": ("overview", "alerts", "overdue", "arbitrators", "actions"),
    },
    "verifiers": {
        "js": "cyber-verifier-network.js",
        "cap": "can_view_verifier_network",
        "subs": ("nodes", "stats"),
    },
    # 复核台跟的不是白名单，而是「名下有一个 active 的 verifier 类档案」，
    # 但对前端来说它与另两个特权工作面同规矩：入口按能力位画、不打真接口试 403。
    "reviews": {
        "js": "cyber-reviews.js",
        "cap": "can_open_review_queue",
        "subs": ("all", "identity", "entity", "developer", "kyc"),
    },
}


#: 纯运维工作面：整组按能力位显隐（不在名单里连入口都不画）。
CAPS_GATED_PANELS = ("arbitration", "verifiers")


def _group_html(html, page):
    """切出 ``data-group="<page>"`` 那一组，到下一个 nav-group 为止。"""
    start = html.index('<div class="nav-group" data-group="%s"' % page)
    end = html.find('<div class="nav-group"', start + 1)
    return html[start:] if end < 0 else html[start:end]


def test_nav_groups_carry_the_page_hooks():
    html = PAGE.read_text(encoding="utf-8")
    for page, info in PANELS.items():
        group = _group_html(html, page)
        if page in CAPS_GATED_PANELS:
            assert re.search(r'data-group="%s"[^>]*hidden' % page, group), (
                f"{page} 是纯运维工作面，必须默认 hidden（caps 到位后才画）"
            )
        for sub in info["subs"]:
            assert f'data-page="{page}" data-sub="{sub}"' in html, f"缺 {page}/{sub} 子项"
        assert f'<section id="{page}" class="page">' in html, f"缺 {page} 正文 section"
        assert f'scripts/{info["js"]}' in html, f"页面没引入 {info['js']}"


def test_operations_review_desk_is_one_entry_with_cap_gated_subs():
    """运营复核台一个组干两件事（用户口径 2026-10-09：「改为一个，只要运营复核台就行了」）。

    * 组本身**常显** —— 它是岗位入口，藏掉入口，还没开通的人就永远开不了岗；
    * 五个待办子项 + 折叠箭头按 ``can_open_review_queue`` 展开；
    * 侧栏里不许再有第二个复核台入口。
    """
    html = PAGE.read_text(encoding="utf-8")
    group = _group_html(html, "reviews")
    assert "hidden" not in group.split("\n")[0], "运营复核台是岗位入口，整组不许藏起来"
    assert 'data-workspace-role="ops_reviewer"' in group, "运营复核台要走岗位入口那条路"
    assert '<div class="nav-subs" hidden>' in group, "五个待办子项默认收起来（caps 到位才展开）"
    assert 'class="nav-caret" hidden' in group, "子项收着的时候折叠箭头也别画"
    assert 'data-group="ops-reviewer"' not in html, "入口只能有一个"
    boot = BOOT.read_text(encoding="utf-8")
    assert 'data-group=\\"reviews\\"' in boot, "boot 要单独处理运营复核台的子项显隐"
    assert "can_open_review_queue" in boot
    css = CSS.read_text(encoding="utf-8")
    assert ".nav-group.open .nav-subs[hidden] { display: none; }" in css, (
        "[hidden] 要压过 .nav-group.open .nav-subs 那条 display:flex"
    )


def test_panels_are_gated_by_capabilities_not_by_probing_403():
    for info in PANELS.values():
        js = (SCRIPTS / info["js"]).read_text(encoding="utf-8")
        assert "KarmaConsoleCaps" in js, f"{info['js']} 必须按能力位判断入口"
        assert info["cap"] in js, f"{info['js']} 没有读 {info['cap']}"
        assert "function permitted()" in js
        # 先看会话，再发请求；状态行给的是能翻的话，不是服务端英文原文。
        assert "function authed()" in js and "if (!authed()) {" in js, f"{info['js']} 要先看会话"
        assert "status === 401" in js and "status === 403" in js, f"{info['js']} 状态行要按状态给话"


def test_boot_loads_caps_and_owns_nav_visibility():
    boot = BOOT.read_text(encoding="utf-8")
    assert "/v1/console/capabilities" in boot
    assert "window.KarmaConsoleCaps" in boot
    assert "karma-caps-ready" in boot, "caps 到位要广播，面板才好跟着刷新"
    assert "function applyPrivilegedNavVisibility" in boot
    assert 'querySelectorAll(".nav-group[data-group]")' in boot
    for name in ("karma-wallet-connected", "karma-profile-switched", "karma-session-restored"):
        assert f'"{name}"' in boot, f"会话变化 {name} 时要重拉能力位"


def test_hidden_attribute_beats_the_flex_layout():
    css = CSS.read_text(encoding="utf-8")
    assert ".nav-group[hidden] { display: none !important; }" in css, (
        ".nav-group 自己写了 display:flex，会盖掉 [hidden] 的 UA 默认值"
    )


def test_page_keys_for_the_new_panels_exist_in_every_core_pack():
    i18n = (SCRIPTS / "i18n-cyber.js").read_text(encoding="utf-8")
    for page in PANELS:
        for suffix in ("title", "sub"):
            key = '"page.%s.%s"' % (page, suffix)
            assert i18n.count(key) == 5, f"{key} 不是在 5 份核心包里都有"
        nav = '"nav.%s"' % page
        assert i18n.count(nav) == 5, f"{nav} 不是在 5 份核心包里都有"


def test_every_chinese_literal_in_the_panels_is_translated_in_all_packs():
    for info in PANELS.values():
        path = SCRIPTS / info["js"]
        literals = {
            m.group(1)
            for m in JS_STRING.finditer(path.read_text(encoding="utf-8"))
            if CJK.search(m.group(1))
        }
        assert literals, f"{info['js']} 应该带中文文案"
        for lang in SHIPPED_LANGS:
            keys = set(PACK_ENTRY.findall((PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")))
            missing = sorted(s for s in literals if s not in keys)
            assert not missing, f"{lang} 译表缺 {info['js']} 的：{missing}"


def test_every_element_id_the_panels_touch_exists_in_the_page():
    html = PAGE.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    for info in PANELS.values():
        src = (SCRIPTS / info["js"]).read_text(encoding="utf-8")
        for used in sorted(set(re.findall(r'byId\("([^"]+)"\)', src))):
            assert used in ids, f"{info['js']} 摸的 #{used} 在页面上不存在"


def test_boot_registers_the_two_page_keys_for_the_heading():
    boot = BOOT.read_text(encoding="utf-8")
    for page in PANELS:
        assert f'{page}: ["page.{page}.title", "page.{page}.sub"]' in boot