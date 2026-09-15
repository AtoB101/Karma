# -*- coding: utf-8 -*-
"""操作台把身份 ID 写给用户看时，必须经过显示层。

为什么专门立这条测试：底座里的真 ID 是 ``kid_`` + 24 位十六进制，用户记不住也念不出来。
对外统一显示成 ``Kid1`` + 6 位数字（子身份 ``kid02`` / ``kid03``…），换算在
``cyber-identity.js`` 里，挂在 ``window.KarmaDisplayId`` 上。

2026-09-15 线上实测（真实浏览器 × 生产）抓到两次：
- 主身份卡 ``#idv-master-id`` 把 ``kid_5f0a…`` 原样写了出来，同一时刻侧栏显示的是 ``Kid1202884``；
- 顶栏状态行 ``已连接 · 0x5AcC… · kid_5f0a…`` 同样是原文。

所以钉两条静态检查：写进节点、拼进字符串，两种都必须看得见显示层函数。
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "apps" / "console" / "scripts"

#: 走过显示层（或等价的截断/换算）的标志。
_DISPLAY_HELPERS = ("KarmaDisplayId", "displayId(", "myDisplayId(", "shortId(")

#: ① 直接把身份原文写进节点。
_RAW_WRITE = re.compile(
    r"\.textContent\s*=\s*(?:identity\(\)|id|identityId|identity_id|masterId|master|ident"
    r"|(?:window\.)?KARMA_IDENTITY_ID)\s*(?:\|\||;|\))"
)

#: ② 把身份原文拼进用户可见字符串（状态栏这类）。
_RAW_CONCAT = re.compile(
    r"\+\s*(?:s\.identityId|identityId|identity_id|(?:window\.)?KARMA_IDENTITY_ID|masterId|master_id)\b"
)

_IDENTITY_VARS = (".identityId", ", identityId")


def _displayed(line: str) -> bool:
    return any(helper in line for helper in _DISPLAY_HELPERS)


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith(("*", "//", "/*"))


def _scan(pattern: re.Pattern[str]) -> list[str]:
    offenders: list[str] = []
    for path in sorted(SCRIPTS.glob("*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _is_comment(line) or not pattern.search(line):
                continue
            if _displayed(line):
                continue
            offenders.append(f"  {path.name}:{number}  {line.strip()[:100]}")
    return offenders


def test_console_never_writes_a_raw_identity_id_into_a_node():
    offenders = _scan(_RAW_WRITE)
    assert not offenders, (
        "这些地方把 kid_ 原文直接写进了页面（应该走 KarmaDisplayId.of(..., 0) 显示成 Kid1…）：\n"
        + "\n".join(offenders)
    )


def test_console_never_concatenates_a_raw_identity_id_into_a_message():
    offenders = _scan(_RAW_CONCAT)
    assert not offenders, (
        "这些地方把 kid_ 原文拼进了给用户看的字符串（比如「已连接 · kid_…」）：\n"
        + "\n".join(offenders)
    )