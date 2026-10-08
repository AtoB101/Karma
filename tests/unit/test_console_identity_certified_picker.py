# -*- coding: utf-8 -*-
"""「选择身份」只列认证过的身份（用户口径 2026-10-09）。

身份在「身份 · 认证」里认证通过之后才进选择栏 —— 没认证的（kyc_status 是
none / pending / rejected）和本人停用的先都收起来，列出来只会让人切过去发现什么都
干不了。两个面板（顶栏 sub-switch-panel / 侧栏 id-picker-panel）同一条口径，不许一处
收一处不收；面板空着的时候就留一句「去哪儿认证」，点一下直达认证页。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
JS = CONSOLE / "scripts/cyber-identity.js"
CORE = CONSOLE / "scripts/i18n-cyber.js"
PACKS = CONSOLE / "scripts/i18n-phrase"
SHIPPED = ("en", "ja", "ko", "es-AR", "es-SV")
HINT = "还没有已认证的子身份 —— 在「身份 · 认证」里认证通过一个，它就会出现在这里。"


def test_both_panels_filter_on_certification():
    js = JS.read_text(encoding="utf-8")
    assert js.count("if (!isCertifiedIdentity(p)) return;") == 2, (
        "两个「选择身份」面板都要按认证状态过滤"
    )
    body = js.split("function isCertifiedIdentity(p) {", 1)[1].split("\n  }", 1)[0]
    assert '"verified"' in body, "判据是 kyc_status === verified"
    assert "disabled" in body, "本人停用的档案也不列"
    assert '"none"' in body, "兜底走 none（缺字段的档案按未认证算）"


def test_uncertified_placeholders_are_gone():
    """以前把「还没建的助理」也列出来（未建立 / dashed 样式）—— 那是没认证的东西，撤掉。"""
    js = JS.read_text(encoding="utf-8")
    assert "ASSISTANT_KLASSES" not in js
    assert '"未建立"' not in js
    assert "r.missing" not in js
    css = (CONSOLE / "styles/cyber-console.css").read_text(encoding="utf-8")
    assert ".id-picker-item.missing" not in css


def test_empty_panel_points_at_the_certification_page():
    js = JS.read_text(encoding="utf-8")
    assert 'hintNode("sub-switch-empty")' in js, "顶栏面板空态要给出提示"
    assert 'hintNode("id-picker-empty")' in js, "侧栏面板空态要给出提示"
    assert 'cyberSwitchPage("identity", "master")' in js, "点提示要直达「身份 · 认证」"
    # 有档案但一张都没认证：不画空分组，只留提示。
    assert "rows.length === 1" in js and "rows.length < 2" in js


def test_hint_text_is_translated_everywhere():
    core = CORE.read_text(encoding="utf-8")
    assert core.count('"scope.empty_uncertified"') == 5, "五个核心语言包都要有这条"
    assert '"scope.empty_uncertified": "%s"' % HINT in core, "中文包与源码里的兜底文案要逐字一致"
    for lang in SHIPPED:
        pack = (PACKS / (lang + ".js")).read_text(encoding="utf-8")
        assert '"%s":' % HINT in pack, "%s 文案表缺这句" % lang
