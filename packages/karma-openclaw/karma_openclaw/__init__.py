"""Karma ↔ OpenClaw MCP bridge package.

Keep package import light: handoff/helpers must work without pulling FastMCP
(mcp v1). Server entrypoints are exported lazily.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_app", "main"]


def __getattr__(name: str) -> Any:
    if name in ("build_app", "main"):
        from karma_openclaw.server import build_app, main

        return build_app if name == "build_app" else main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
