# -*- coding: utf-8 -*-
"""「选择身份」只显示已认证的助理（用户口径 2026-10-10 修订）。

认证通过的（kyc_status=verified 且档案没被本人停用）才会出现在「选择助理身份」的
选项里；未认证 / 复核中 / 未通过的直接不显示。空态仍然给出「去哪儿认证」的出口，
避免用户想切卡却不知道先要认证。

以前那种「未建立」的假占位仍然不许回来。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
JS = CONSOLE / "scripts/cyber-identity.js"
CORE = CONSOLE / "scripts/i18n-cyber.js"
PACKS = CONSOLE / "scripts/i18n-phrase"
CSS = CONSOLE / "styles/cyber-console.css"
SHIPPED = ("en", "ja", "ko", "es-AR", "es-SV")
HINT = "还没有已认证的子身份 —— 在「身份 · 认证」里认证通过一个，它就会出现在这里。"
PENDING_HINT = "还没认证完的身份卡在下面 —— 点一张去「身份 · 认证」把它认证通过，就能切过去了。"


def test_both_panels_share_one_certification_rule():
    js = JS.read_text(encoding="utf-8")
    body = js.split("function isCertifiedIdentity(p) {", 1)[1].split("\n  }", 1)[0]
    assert '"verified"' in body, "判据是 kyc_status === verified"
    assert "disabled" in body, "本人停用的档案也不给切"
    assert '"none"' in body, "兜底走 none（缺字段的档案按未认证算）"
    # 两个面板都先按「有没有这张档案」收一遍，再用认证状态决定显不显示。
    assert js.count("if (!isExistingIdentity(p)) return;") == 2, (
        "两个「选择身份」面板都要先认出「真的有一张档案」"
    )
    assert js.count("if (!isCertifiedIdentity(p)) return;") == 2, (
        "两个「选择身份」面板都要把未认证的助理挡在选择项外"
    )


def test_uncertified_cards_are_not_shown_in_the_pickers():
    js = JS.read_text(encoding="utf-8")
    assert "pending.push(p)" not in js, "选择项里不再收集未认证卡片"
    assert "pending: !certified" not in js
    assert "if (r.pending) return goCertify(r.klass);" not in js
    assert "if (r.dim) { closeSubPanel(); goCertify(r.klass); return; }" not in js
    assert "klass: p[\"class\"]" not in js
    assert "dim: true" not in js
    assert " + kycStatusLabel(p)" not in js, "选择项里不再显示卡在哪一步"


def test_master_row_carries_the_personal_assistant_verification():
    """「个人助理认证」（证件核验）核的是主身份本人 —— 第一行得能认出这个结果。"""
    js = JS.read_text(encoding="utf-8")
    assert "masterVerifyStatus" in js
    assert "getIdentityVerification(oid)" in js, "要回查主身份的证件核验状态"
    assert "masterVerifySuffix()" in js
    assert js.count("masterVerifySuffix()") == 3, "两个面板的第一行都要带上；加上函数定义"
    assert 'tr("个人助理认证", "个人助理认证")' in js


def test_uncertified_placeholders_are_gone():
    """以前把「还没建的助理」也列出来（未建立 / dashed 样式）—— 那是没认证的东西，撤掉。"""
    js = JS.read_text(encoding="utf-8")
    assert "ASSISTANT_KLASSES" not in js
    assert '"未建立"' not in js
    assert "r.missing" not in js
    css = CSS.read_text(encoding="utf-8")
    assert ".id-picker-item.missing" not in css


def test_empty_panel_points_at_the_certification_page():
    js = JS.read_text(encoding="utf-8")
    assert 'hintNode("sub-switch-empty")' in js, "顶栏面板空态要给出提示"
    assert 'hintNode("id-picker-empty")' in js, "侧栏面板空态要给出提示"
    assert 'cyberSwitchPage("identity", sub || "master")' in js, "点提示要直达「身份 · 认证」"
    # 一张档案都没有：不画空分组，只留提示。
    assert "rows.length < 2" in js and "rows.length > 1" in js
    # 有卡但一张都没认证通过：直接给「去哪儿认证」的提示，不再把未认证卡片列在下面。
    assert "var selectable = 0;" not in js
    assert "if (!selectable)" not in js


def test_pending_group_is_not_rendered():
    js = JS.read_text(encoding="utf-8")
    assert 'addHead("pick.role_pending", PENDING_HINT)' not in js


def test_allocation_table_lists_certified_identities_too():
    """额度分配表和「选择身份」同一条口径；例外只给「还挂着额度」的档案留。"""
    js = JS.read_text(encoding="utf-8")
    body = js.split("async function refreshAllocation() {", 1)[1].split("function allocInputs()", 1)[0]
    assert "isCertifiedIdentity(p)" in body, "额度分配也要按认证状态过滤"
    assert "allocated_credits" in body, "没认证但还挂着额度的要继续列（否则清不掉）"
    assert "rows.forEach(" in body and "profiles.forEach(" not in body
    assert "hintNode(" in body, "一张都没有时要给出去哪儿认证"
    assert 'tr("未认证", "未认证")' in body, "例外行要标出来"


def test_hint_text_is_translated_everywhere():
    core = CORE.read_text(encoding="utf-8")
    assert core.count('"scope.empty_uncertified"') == 5, "五个核心语言包都要有这条"
    assert '"scope.empty_uncertified": "%s"' % HINT in core, "中文包与源码里的兜底文案要逐字一致"
    assert core.count('"pick.role_pending"') == 5, "五个核心语言包都要有「没认证完」那一组的前缀"
    assert '"pick.role_pending": "%s"' % PENDING_HINT in core
    for lang in SHIPPED:
        pack = (PACKS / (lang + ".js")).read_text(encoding="utf-8")
        assert '"%s":' % HINT in pack, "%s 文案表缺这句" % lang


def test_pending_rows_are_visibly_dimmed():
    css = CSS.read_text(encoding="utf-8")
    assert ".sub-switch-item.pending" in css
    assert ".id-picker-item.pending" in css
