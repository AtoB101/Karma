"""发行版版本号的单一来源：``pyproject.toml``。

包内 ``__version__`` 与 ``pyproject.toml`` 的 ``version`` 是两处写法，改了版本只改一处
就会漂 —— 而漂掉的那处正是 `MCP packages` 作业会拿去和 wheel 元数据比对的地方。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from karma_connect import __version__ as PKG_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_dunder_version_matches_pyproject():
    meta = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["name"] == "karma-connect"
    assert meta["project"]["version"] == PKG_VERSION
