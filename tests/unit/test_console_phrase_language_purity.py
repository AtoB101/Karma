"""源文案表（i18n-phrase）的语言纯净度：英文/韩文/西语页面不许夹中文。

真机实测（韩语 / 西语操作台逐页扫 30 个页面）发现的漏法有两种，都非常隐蔽：

* 译文里混进简体中文的全角标点 —— 韩语页「얼굴 인증만（위 ②）。」整句韩文里夹着
  一对全角括号和句号；
* 译文里整词没翻 —— 韩语、日语都把「未激活」原样搬进了句子（「이 키는 「未激活」로
   돌아가며」），英文和西语反而翻对了。

这两种都只在「渲染那一条文案」的时候才看得见，逐页点过去成本很高，所以这里按
文案表全量静态检查：漏一条就红。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHRASES = ROOT / "apps/console" / "scripts" / "i18n-phrase"

#: 语言选择器上的那两个词条本身就是「用本语言写别的语言的名字」，允许保留汉字。
LANGUAGE_LABELS = {"中文", "日本語"}

#: 简体中文全角标点。日语也用全角标点，所以只对「不用全角标点」的语言检查。
CJK_PUNCT = "（）。，、；：！？"
PUNCT_LANGS = ("en", "ko", "es-AR", "es-SV")

#: 这些词是简体中文写法，日语里不这么写 —— 出现在日语译文里就是漏译。
JA_FORBIDDEN_WORDS = ("激活", "额度")
HAN = re.compile("[一-鿿]")
ENTRY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)":\s*"((?:[^"\\]|\\.)*)",?\s*$')


def entries(lang):
    """[(行号, 源文案, 译文)] —— 文案表是一行一条，按行解析就够。"""
    path = PHRASES / (lang + ".js")
    text = path.read_text(encoding="utf-8")
    out = []
    for lineno, line in enumerate(text.split("\n"), 1):
        m = ENTRY.match(line)
        if m:
            out.append((lineno, m.group(1), m.group(2)))
    assert out, "%s 文案表一条都没解析出来（格式变了？）" % lang
    return out


@pytest.mark.parametrize("lang", PUNCT_LANGS)
def test_no_chinese_fullwidth_punctuation_outside_cjk_languages(lang):
    bad = []
    for lineno, _src, val in entries(lang):
        hit = sorted({c for c in val if c in CJK_PUNCT})
        if hit:
            bad.append("%s.js:%d %s | %s" % (lang, lineno, "".join(hit), val[:90]))
    assert not bad, "译文里混进了中文全角标点：\n" + "\n".join(bad)


@pytest.mark.parametrize("lang", ("en", "ko", "es-AR", "es-SV"))
def test_no_han_characters_left_in_non_han_languages(lang):
    bad = []
    for lineno, _src, val in entries(lang):
        left = HAN.findall(val)
        if left and val not in LANGUAGE_LABELS:
            bad.append("%s.js:%d %s | %s" % (lang, lineno, "".join(sorted(set(left))), val[:90]))
    assert not bad, "译文里整词没翻、留着汉字：\n" + "\n".join(bad)


def test_japanese_pack_does_not_keep_simplified_chinese_words():
    bad = []
    for lineno, _src, val in entries("ja"):
        hit = [w for w in JA_FORBIDDEN_WORDS if w in val]
        if hit:
            bad.append("ja.js:%d %s | %s" % (lineno, "/".join(hit), val[:90]))
    assert not bad, "日语译文里留着简体中文词：\n" + "\n".join(bad)


@pytest.mark.parametrize("lang,translated", (
    ("ko", "「미활성」"),
    ("ja", "「未アクティブ」"),
))
def test_unbound_notice_names_the_key_state_in_that_language(lang, translated):
    """「已取消绑定：这把钥匙回到「未激活」…」这句里，钥匙状态必须真的翻了。"""
    rows = [v for _n, s, v in entries(lang) if s.startswith("已取消绑定：这把钥匙回到")]
    assert len(rows) == 1, "%s 里应该只有一条「取消绑定」译文，实际 %d" % (lang, len(rows))
    row = rows[0]
    assert translated in row, "%s 的取消绑定提示没把「未激活」翻过来：%s" % (lang, row[:90])
    assert "未激活" not in row, "%s 的取消绑定提示还留着中文「未激活」" % lang
