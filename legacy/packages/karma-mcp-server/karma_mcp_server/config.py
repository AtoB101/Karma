"""MCP Server 配置。

**只读** ``KARMA_RUNTIME_KEY`` 等凭据；Tier-2/Tier-3（动钱）默认**关闭**（fail-closed）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from karma_mcp_server.credentials import credential

DEFAULT_RUNTIME_URL = "http://localhost:8000"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class McpConfig:
    runtime_base_url: str = DEFAULT_RUNTIME_URL
    read_timeout_seconds: float = 30.0
    write_timeout_seconds: float = 120.0
    #: Tier-2（交易/交付）与 Tier-3（结算/争议）默认关闭。
    enable_tier2: bool = False
    enable_tier3: bool = False
    #: 远程 Streamable HTTP 默认关闭 —— 远程鉴权方案未定前不得开放。
    enable_http: bool = False

    def allowed_tiers(self) -> frozenset[int]:
        tiers = {0, 1}
        if self.enable_tier2:
            tiers.add(2)
        if self.enable_tier3:
            tiers.add(3)
        return frozenset(tiers)


def load_config(
    env: dict[str, str] | None = None, *, file_values: dict[str, str] | None = None
) -> McpConfig:
    source = os.environ if env is None else env
    base = (
        credential("KARMA_RUNTIME_URL", env=source, file_values=file_values) or DEFAULT_RUNTIME_URL
    )
    return McpConfig(
        runtime_base_url=base.rstrip("/"),
        enable_tier2=_truthy(source.get("KARMA_MCP_ENABLE_TIER2")),
        enable_tier3=_truthy(source.get("KARMA_MCP_ENABLE_TIER3")),
        enable_http=_truthy(source.get("KARMA_MCP_ENABLE_HTTP")),
    )
