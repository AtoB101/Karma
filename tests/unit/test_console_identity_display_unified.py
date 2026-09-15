# -*- coding: utf-8 -*-
"""身份编号显示口径门禁：全站只能有一套写法。

为什么要有这个文件：用户报过「kid 显示的不统一」。线上实测同一个「生活助理」身份，
同一块屏幕上同时出现四种写法：

    左侧功能区   kid03680644
    顶栏身份芯片 Kid1202884                    ← 切了身份它不跟着变，还挂着主身份
    主身份额度表 生活助理 · kid03680644        ← 名字在前
    交易对方    kid_5f0aa8ccf7…               ← 真 ID 原文截断

四种写法指的是同一类东西，用户会以为那是四个不同的身份，也会以为「切换没成功」。

钉住的规则（实现只有一处：cyber-identity.js 的 window.KarmaDisplayId）：
  1. 前缀只有一个，全小写 kid：主身份 kid1 + 6 位数字，子身份 kid02 / kid03 + 6 位数字；
  2. 拿不到排位的身份统一降级成 kid… + 真 ID 后 4 位（KarmaDisplayId.remote）；
  3. 编号和名称同时出现时，一律「编号 · 名称」；
  4. 顶栏那颗身份芯片必须跟着「切换身份」变，不许锁死在主身份。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "apps" / "console" / "scripts"
PAGE = ROOT / "apps" / "console" / "pages" / "cyber" / "index.html"

IDENTITY_JS = SCRIPTS / "cyber-identity.js"
AUTH_JS = SCRIPTS / "console-wallet-auth.js"
MASTER_JS = SCRIPTS / "cyber-master-page.js"

#: 展示层之外，还要显示「别人的身份号」的模块。
REMOTE_CALLERS = (
    "cyber-orders.js",
    "cyber-payments.js",
    "cyber-order-flow.js",
    "cyber-reviews.js",
)

_KID_LITERAL = re.compile(r"Kid1")
_RAW_KID = re.compile(r"kid_")
_HEX24 = re.compile(r"kid_[0-9a-f]{24}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_lines(path: Path):
    """只吐真正会被执行的行：注释里提到 kid_ 原文是允许的。"""
    in_block = False
    for number, line in enumerate(_read(path).splitlines(), start=1):
        stripped = line.lstrip()
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped[2:]:
                in_block = True
            continue
        if stripped.startswith("//"):
            continue
        yield number, line


def test_only_one_prefix_and_it_is_lowercase():
    """主身份一律 kid1 开头；再冒出 Kid1 就是又有人自己拼了一个。"""
    offenders = [
        "%s:%d  %s" % (path.name, n, line.strip()[:90])
        for path in sorted(SCRIPTS.glob("*.js"))
        for n, line in _code_lines(path)
        if _KID_LITERAL.search(line)
    ]
    assert not offenders, "身份编号前缀只允许全小写 kid：\n" + "\n".join(offenders)


def test_display_layer_is_the_single_source_of_truth():
    js = _read(IDENTITY_JS)
    block = js[js.index("function displayId(") : js.index("function remoteId(")]
    assert '"kid1" + digitSeed(id)' in block, "主身份要写成 kid1 + 6 位数字"
    assert '"kid" + (n < 10 ? "0" + n : String(n))' in block, "子身份要写成 kid02 / kid03"
    assert re.search(r"window\.KarmaDisplayId = \{ of: displayId, remote: remoteId", js), (
        "必须导出 remote()，否则各模块又会自己截一段 kid_ 原文贴到界面上"
    )


def test_raw_kid_ids_never_reach_the_ui():
    """界面里不许出现 kid_ 原文（展示层剥离前缀的那处正则除外）。"""
    offenders = []
    for path in sorted(SCRIPTS.glob("*.js")):
        for number, line in _code_lines(path):
            if not _RAW_KID.search(line):
                continue
            if "replace(/^kid_?/i" in line:
                continue
            offenders.append("%s:%d  %s" % (path.name, number, line.strip()[:90]))
    assert not offenders, (
        "这些地方把 kid_ 原文写到了用户看得见的位置（应走 KarmaDisplayId.of / .remote）：\n"
        + "\n".join(offenders)
    )


def test_other_peoples_ids_go_through_the_shared_fallback():
    for name in REMOTE_CALLERS:
        js = _read(SCRIPTS / name)
        assert "KarmaDisplayId.remote" in js, (
            "%s 里别人的身份号必须走 KarmaDisplayId.remote（kid…+ 后 4 位），不能各截各的" % name
        )


def test_number_comes_before_the_name_everywhere():
    """「编号 · 名称」是唯一顺序：一处编号在前、一处名字在前，看着就是不统一。"""
    master = _read(MASTER_JS)
    block = master[master.index("function titleOf(") : master.index("function activationLabel(")]
    assert "return label(p.profile_id, i + 1) + " in block, "额度表必须编号在前、名称在后"
    identity = _read(IDENTITY_JS)
    plabel = identity[
        identity.index("function profileLabel(") : identity.index("function profilePosition(")
    ]
    assert 'displayId(p.profile_id, pos) + " · "' in plabel, "身份标签也必须编号在前"


def test_topbar_chip_follows_the_identity_switch():
    js = _read(IDENTITY_JS)
    block = js[js.index("function renderCurrentIdentity()") : js.index("// ---- 涉密 ----")]
    assert "top-identity-chip" in block, "顶栏身份芯片要在切身份的路径上更新"
    auth = _read(AUTH_JS)
    assert "if (!(idSwitcher && idSwitcher.renderCurrent))" in auth, (
        "钱包模块不能在身份模块渲染完之后再把主身份写回芯片"
    )


def test_input_placeholders_show_a_real_looking_id():
    html = _read(PAGE)
    assert "kid_xxx" not in html, "输入框示例别再写 kid_xxx"
    assert _HEX24.search(html), "输入框示例要给一个和真 ID 同形的例子（kid_ + 24 位十六进制）"
