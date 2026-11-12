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


# ── 「接入包」结果卡里「agent 读到的边界」那一块 ──────────────────────────
#
# 真机实测（韩语）：这一整块原来塞在一个 <pre> 里，PRE 默认不翻，于是中文页面对齐、
# 别的语言整片留中文。现在改成一行一个 <span data-i18n-phrase>，每行按自己的原文
# 查表。下面按 i18n-cyber.js 的 compilePatterns 规则（{n} -> ([\s\S]+?)，整串锚定，
# 键与文本都先按空白归一）复算一遍，钉住「这十行在四种语言里真的翻了」。

BOUNDARY = (
    (chr(0x8eab) + chr(0x4efd) + "        {0}" + chr(0xff08) + "{1}" + chr(0xff09),
     "kid02802680", "87745fb3-0fcd-4fdc-b9ea-b0eb8b45e174"),
    (chr(0x540d) + chr(0x5b57) + "        {0}", "claw-001"),
    ("agent       {0}", "claw-001"),
    (chr(0x7c7b) + chr(0x578b) + "        {0}", "life"),
    (chr(0x6388) + chr(0x6743) + chr(0x989d) + chr(0x5ea6) + "    {0} USDC", "1.00"),
    (chr(0x5355) + chr(0x7b14) + chr(0x6700) + chr(0x9ad8) + "    {0} USDC", "1.00"),
    (chr(0x6bcf) + chr(0x65e5) + chr(0x4e0a) + chr(0x9650) + "    {0} USDC", "2.00"),
    (chr(0x4eba) + chr(0x5de5) + chr(0x786e) + chr(0x8ba4) + "    {0}",
     chr(0x8d85) + chr(0x8fc7) + chr(0x5355) + chr(0x7b14) + chr(0x6700) + chr(0x9ad8)
     + chr(0x65f6) + chr(0x627e) + chr(0x6211) + chr(0x786e) + chr(0x8ba4)),
    (chr(0x6743) + chr(0x9650) + "        {0}", "discover_agents, place_order"),
    (chr(0x6709) + chr(0x6548) + chr(0x671f) + chr(0x81f3) + "    {0}", "2026-09-30"),
)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def _render(lang, lineno, src, args):
    """按引擎的规则把这一行翻出来（含 {0} 里那句的二次翻译）。"""
    table = {_norm(s): v for _n, s, v in entries(lang)}
    # 先照原文把值填进去 —— 这就是运行时的文本节点。
    live = src
    for i, a in enumerate(args):
        live = live.replace("{%d}" % i, a)
    key = _norm(live)
    if key in table:
        return table[key]
    pats = sorted(
        ((k, v) for k, v in table.items() if "{" in k),
        key=lambda kv: -len(kv[0]),
    )
    for k, v in pats:
        rx = ""
        i = 0
        while i < len(k):
            m = re.match(r"^\{(\d+)\}", k[i:])
            if m:
                rx += r"([\s\S]+?)"
                i += m.end()
                continue
            rx += re.escape(k[i])
            i += 1
        m = re.match("^" + rx + "$", key)
        if m:
            return re.sub(
                r"\{(\d+)\}",
                lambda mm: _render(lang, lineno, m.group(int(mm.group(1)) + 1), ()),
                v,
            )
    return None


@pytest.mark.parametrize("lang", ("en", "ko", "es-AR", "es-SV"))
def test_handoff_boundary_block_translates_line_by_line(lang):
    bad = []
    for src, *args in BOUNDARY:
        out = _render(lang, 0, src, tuple(args))
        if out is None:
            bad.append("%s \u6ca1\u6709\u8fd9\u4e00\u884c\u7684\u8bd1\u6587\uff1a%s" % (lang, src))
            continue
        left = "".join(sorted(set(HAN.findall(out))))
        if left:
            bad.append("%s \u7ffb\u5b8c\u8fd8\u5269 %s\uff1a%s" % (lang, left, out))
    assert not bad, "\n".join(bad)


def test_handoff_boundary_block_translates_line_by_line_ja():
    bad = []
    for src, *args in BOUNDARY:
        out = _render("ja", 0, src, tuple(args))
        if out is None:
            bad.append("ja \u6ca1\u6709\u8fd9\u4e00\u884c\u7684\u8bd1\u6587\uff1a%s" % src)
            continue
        if out == src.replace("{0}", args[0]).replace("{1}", args[1] if len(args) > 1 else ""):
            bad.append("ja \u8fd9\u4e00\u884c\u539f\u6837\u6ca1\u7ffb\uff1a%s" % out)
    assert not bad, "\n".join(bad)


def test_result_card_tag_is_in_the_packs():
    """\u7ed3\u679c\u5361\u4e0a\u90a3\u4e2a\u7eff\u6807\u7b7e\uff08\u5df2\u751f\u6210\uff09\u4e5f\u5f97\u6709\u8bd1\u6587\uff0c\u5426\u5219\u5168\u90e8\u8bed\u8a00\u90fd\u663e\u4e2d\u6587\u3002"""
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        table = {_norm(s): v for _n, s, v in entries(lang)}
        assert chr(0x5df2) + chr(0x751f) + chr(0x6210) in table, "%s \u7f3a\u300c\u5df2\u751f\u6210\u300d\u7684\u8bd1\u6587" % lang
