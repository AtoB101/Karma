"""操作台里每一个取数请求都必须带认证头。

为什么专门立一条测试：``karmaFetch`` 只负责发 fetch，**不会**替你加
``Authorization`` / ``X-Karma-Identity-Id``。少写一个 ``headers: api().headers()``，
本地看着一切正常，线上就是 401/403 —— 而且页面上只表现为「一直是空的」，
没有任何报错提示。这个坑已经踩过两次（复核台、开发者实名），所以用一条静态检查
把它钉住：新增的取数请求忘带认证头，测试直接红。
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "apps" / "console" / "scripts"

#: 客户端本体的定义文件，里面的 ``karmaFetch(path, init)`` 不是调用。
DEFINITION_FILE = "karma-public-api.js"

_CALL = re.compile(r"karmaFetch\(")


def _call_bodies(source: str):
    """把每一次 ``karmaFetch(...)`` 的完整实参文本切出来（按括号配平）。"""
    for match in _CALL.finditer(source):
        index, depth = match.end(), 1
        while index < len(source) and depth:
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
            index += 1
        yield match.start(), source[match.start():index]


def test_every_console_fetch_passes_auth_headers():
    offenders: list[str] = []
    for path in sorted(SCRIPTS.glob("*.js")):
        if path.name == DEFINITION_FILE:
            continue
        source = path.read_text(encoding="utf-8")
        for position, call in _call_bodies(source):
            # 认证头可以由 api().headers() 直接给出，也可以走 headers 变量 —— 名字里带 headers 都算。
            if "headers" in call:
                continue
            line = source[:position].count("\n") + 1
            offenders.append(f"  {path.name}:{line}  {' '.join(call.split())[:90]}")
    assert not offenders, "这些取数请求没带认证头（线上会 401/403）：\n" + "\n".join(offenders)
