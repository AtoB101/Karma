"""Phase 2 — x402 MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from karma_openclaw.http_client import api_post


def register_phase2_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def karma_x402_fetch(
        task_id: str,
        agent_id: str,
        url: str,
        max_budget_usdc: float = 10.0,
    ) -> dict[str, Any]:
        """
        POST /v1/x402/pay-and-fetch — x402 paywall fetch with receipt ``external_payment`` audit.

        Requires server ``X402_ENABLED=true`` and task contract exists.
        """
        return await api_post(
            "/v1/x402/pay-and-fetch",
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "url": url,
                "max_budget_usdc": max_budget_usdc,
            },
        )
