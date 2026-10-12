"""MCP 握手身份：``serverInfo`` 必须报**本包**名字与版本。

mcp SDK 1.x 的 ``FastMCP`` 不把版本号转给底层 ``MCPServer``，后者回落成
``importlib.metadata.version("mcp")`` —— 客户端握手时看到的是 SDK 的版本号
（例如 1.29.1），不是 Karma 包的版本，排障时会把人带偏。这里用内存流跑一次真实
``initialize``，把客户端实际看到的东西钉死；顺带守住 pyproject 与 ``__version__`` 不漂移。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


async def _handshake(mcp: FastMCP) -> Any:
    """跑一次真实握手（内存流，不起进程），返回客户端收到的 InitializeResult。"""
    server = mcp._mcp_server
    seen: dict[str, Any] = {}
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read, server_write, server.create_initialization_options()
                )
            )
            async with ClientSession(client_read, client_write) as session:
                seen["init"] = await session.initialize()
            tg.cancel_scope.cancel()
    return seen["init"]


def _pyproject_version() -> str:
    meta = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return meta["project"]["version"]


from karma_openclaw import __version__ as PKG_VERSION
from karma_openclaw.server import build_app

DIST_NAME = "karma-openclaw"


def test_dunder_version_matches_pyproject():
    assert _pyproject_version() == PKG_VERSION


async def test_handshake_reports_package_identity():
    init = await _handshake(build_app())
    assert init.serverInfo.name == DIST_NAME
    assert init.serverInfo.version == PKG_VERSION
