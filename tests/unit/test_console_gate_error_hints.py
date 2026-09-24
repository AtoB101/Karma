"""服务端的英文闸门 detail，到用户那里必须是人话，而且每种语言都得有。

真机：向导点「生成」只显示 "HTTP 400: agent_binding is required: every runtime key
must name the agent it is issued to, and that agent must activate it in Console with
the 8-character matching code before the key can spend anything" —— 一整句英文 API
原文。用户既不知道错在哪，也不知道下一步点哪儿。

现在 karma-public-api.js 把已知闸门映射成一句可执行的中文，原文留在 err.detail
（并打 console.warn）；那一句中文再按常规被 i18n-phrase 翻成各自语言。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
API_JS = (CONSOLE / "scripts" / "karma-public-api.js").read_text(encoding="utf-8")
PHRASES = CONSOLE / "scripts" / "i18n-phrase"
LANGS = ("en", "ja", "ko", "es-AR", "es-SV")

HINT = re.compile(r'hint:\s*"((?:[^"\\]|\\.)*)"')


def hints():
    return HINT.findall(API_JS)


def test_known_gate_details_get_human_advice():
    assert hints(), "GATE_HINTS 里一条人话都没有？"
    for needle in (
        "agent_binding is required",
        "agent_id requires agent_binding",
        "agent_id must match agent_binding",
        "automation policy not saved",
    ):
        assert needle in API_JS, f"这条服务端闸门没映射成人话：{needle}"
    # 原文不能丢：给用户看人话，给排查看原文。
    assert "err.detail = msg;" in API_JS
    assert "err.message = hint;" in API_JS
    assert 'console.warn("[karma] " + err.serverMessage);' in API_JS


def test_hints_are_actionable_and_single_line():
    for h in hints():
        assert len(h) >= 10, f"这条人话太短，看不出下一步：{h}"
        assert "\n" not in h, "文案是按整串查表的，不能带换行"
        assert h.endswith("。"), h


@pytest.mark.parametrize("lang", LANGS)
def test_every_language_pack_carries_the_hints(lang):
    pack = (PHRASES / (lang + ".js")).read_text(encoding="utf-8")
    for h in hints():
        assert '"%s"' % h in pack, f"{lang} 缺这条译文：{h}"
    if lang == "ja":
        # 别的语言的「没翻干净」由 test_console_phrase_language_purity 拦；
        # 日语包保留汉字不算违规，所以要单独确认它真的翻了。
        for h in hints():
            row = re.search(r'"%s":\s*"([^"]*)"' % re.escape(h), pack)
            assert row and row.group(1) != h, f"ja 只是把中文键抄了一遍：{h}"
