# -*- coding: utf-8 -*-
"""操作台把身份 ID 写进页面时，必须经过显示层。

为什么专门立一条测试：底座里的真 ID 是 ``kid_`` + 24 位十六进制，用户记不住也念不出来。
对外统一显示成 ``Kid1`` + 6 位数字（子身份 ``kid02`` / ``kid03``…），换算在
``cyber-identity.js`` 里，挂在 ``window.KarmaDisplayId`` 上。

2026-09-15 线上实测抓到一次：主身份卡 ``#idv-master-id`` 直接把 ``kid_5f0a…`` 原样写了出来，
而侧栏同一时刻显示的是 ``Kid1202884`` —— 同一个身份两个样子。所以钉一条静态检查：
凡是把「身份变量」直接塞进 ``textContent`` 的地方，必须看得见显示层函数。
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "apps" / "console" / "scripts"

#: 直接把身份原文写进节点的写法（左边是身份变量名，不是排版好的字符串）。
_RAW_WRITE = re.compile(
    r"\.textContent\s*=\s*(?:identity\(\)|id|identityId|identity_id|masterId|master|ident"
    r"|(?:window\.)?KARMA_IDENTITY_ID)\s*(?:\|\||;|\))"
)

#: 只要这一行出现过任意一个，就说明走过了显示层或等价的截断，不算裸写。
_DISPLAY_HELPERS = ("KarmaDisplayId", "displayId(", "myDisplayId(", "shortId(", "shortAddr(")


def test_console_never_writes_a_raw_identity_id():
    offenders: list[str] = []
    for path in sorted(SCRIPTS.glob("*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not _RAW_WRITE.search(line):
                continue
            if any(helper in line for helper in _DISPLAY_HELPERS):
                continue
            offenders.append(f"  {path.name}:{number}  {line.strip()[:100]}")
    assert not offenders, (
        "这些地方把 kid_ 原文直接写进了页面（应该走 KarmaDisplayId.of(..., 0) 显示成 Kid1…）：\n"
        + "\n".join(offenders)
    )