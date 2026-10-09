"""远程（Streamable HTTP）访问的鉴权。

采用 MCP SDK 自带的标准化路径：``FastMCP(token_verifier=...)`` +
``AuthSettings(issuer_url=..., resource_server_url=...)``。未通过校验的请求由 SDK
返回 401 + ``WWW-Authenticate``，不会到达任何工具。

当前实现：**静态 bearer token**（``KARMA_MCP_HTTP_TOKEN``，常量时间比较）。
完整 OAuth 2.1 授权服务器接入留待后续 —— 在此之前远程传输必须默认关闭。
"""

from __future__ import annotations

import hmac
import os

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

TOKEN_ENV = "KARMA_MCP_HTTP_TOKEN"
ISSUER_ENV = "KARMA_MCP_ISSUER_URL"
RESOURCE_ENV = "KARMA_MCP_RESOURCE_URL"

#: 远程访问可用的最小 scope 集（当前只区分「能连」）。
REMOTE_SCOPE = "karma.mcp"


def configured_token(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return (source.get(TOKEN_ENV) or "").strip()


class StaticTokenVerifier(TokenVerifier):
    """常量时间比较的静态 bearer token 校验器。"""

    def __init__(self, expected_token: str, *, subject: str = "karma-mcp-remote") -> None:
        if not expected_token:
            raise ValueError("remote auth requires a non-empty token")
        self._expected = expected_token
        self._subject = subject

    async def verify_token(self, token: str) -> AccessToken | None:
        candidate = (token or "").strip()
        if not candidate:
            return None
        if not hmac.compare_digest(candidate, self._expected):
            return None
        return AccessToken(
            token=candidate,
            client_id="karma-mcp-client",
            scopes=[REMOTE_SCOPE],
            subject=self._subject,
        )


def build_auth_settings(
    *, default_host: str = "127.0.0.1", default_port: int = 8765
) -> AuthSettings:
    issuer = os.environ.get(ISSUER_ENV, "").strip() or f"http://{default_host}:{default_port}"
    resource = os.environ.get(RESOURCE_ENV, "").strip() or issuer
    return AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource,
        required_scopes=[REMOTE_SCOPE],
    )
