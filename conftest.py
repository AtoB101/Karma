"""Karma — 仓库级 pytest 钩子。

只做一件事：让 CI 能再跑一遍**逆序**的用例，守「用例之间不许有顺序依赖」。

用法：``KARMA_TEST_ORDER=reverse python -m pytest ...``
（见 ``.github/workflows/python-tests.yml`` 的第二个 acceptance 步骤）。
不设这个环境变量时，这个文件什么都不做。

为什么要有这一遍：会话级的用例内存库（``tests/conftest.py``）是全进程共享的 ——
只要有一条用例把行 commit 出去、另一条用例又正好读它，正序可能是绿的、逆序就是红的。
这种依赖在开发机上永远看不见（大家跑的是单个文件或子集）。清表 fixture 已经把
「跨用例残留」堵住，这一遍负责证明它真的堵住了：换一个顺序也必须全绿。
"""
from __future__ import annotations

import os


def pytest_collection_modifyitems(session, config, items):
    if os.environ.get("KARMA_TEST_ORDER", "").strip().lower() == "reverse":
        items.reverse()
