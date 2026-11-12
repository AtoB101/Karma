"""入口：stdio（默认）或 Streamable HTTP（默认关闭，需显式开启 + 鉴权令牌）。

安全第一：
* 启动前拒绝「私钥被注入本进程」这种配置（红线 R1）。
* 远程 HTTP 没有配置鉴权令牌时**拒绝启动**，不会裸奔。
"""

from __future__ import annotations

import argparse
import sys

from karma_mcp_server.config import load_config
from karma_mcp_server.credentials import check_forbidden_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="karma-mcp-server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="stdio（本地 Agent，默认）或 streamable-http（远程，需 KARMA_MCP_ENABLE_HTTP=1）",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    forbidden = check_forbidden_env()
    if forbidden:
        print(
            "refusing to start: this MCP process must not hold private key material. "
            "remove these env vars: " + ", ".join(forbidden),
            file=sys.stderr,
        )
        return 2

    config = load_config()

    token_verifier = None
    auth_settings = None
    if args.transport == "streamable-http":
        if not config.enable_http:
            print(
                "refusing to start: remote HTTP transport is disabled "
                "(set KARMA_MCP_ENABLE_HTTP=1 once remote auth is configured).",
                file=sys.stderr,
            )
            return 3
        from karma_mcp_server.http_auth import (
            StaticTokenVerifier,
            build_auth_settings,
            configured_token,
        )

        token = configured_token()
        if not token:
            print(
                "refusing to start: remote HTTP requires KARMA_MCP_HTTP_TOKEN "
                "(no anonymous remote access).",
                file=sys.stderr,
            )
            return 4
        token_verifier = StaticTokenVerifier(token)
        auth_settings = build_auth_settings(default_host=args.host, default_port=args.port)

    from karma_mcp_server.server import build_server

    mcp = build_server(config, token_verifier=token_verifier, auth_settings=auth_settings)

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
        return 0

    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
