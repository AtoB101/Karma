"""MCP (stdio) bridge from OpenClaw (or any MCP host) to Karma public HTTP API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP


def _runtime_url() -> str:
    u = os.environ.get("KARMA_RUNTIME_URL", "http://localhost:8000").strip().rstrip("/")
    return u


def _api_key() -> str | None:
    k = os.environ.get("KARMA_API_KEY", "").strip()
    return k or None


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        h["X-Karma-Api-Key"] = key
    return h


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(f"{_runtime_url()}{path}", headers=_headers())
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r.text


async def _post_json(path: str, body: Any) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{_runtime_url()}{path}",
            headers=_headers(),
            content=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        )
        r.raise_for_status()
        return r.json()


def build_app() -> FastMCP:
    mcp = FastMCP(
        "karma-openclaw",
        instructions=(
            "Karma Trust Protocol public API tools. Set KARMA_RUNTIME_URL and "
            "optionally KARMA_API_KEY (X-Karma-Api-Key). Paths match openapi/karma-v1.yaml."
        ),
    )

    @mcp.tool()
    async def karma_get_capacity(identity_id: str) -> dict[str, Any]:
        """GET /v1/capacity/{identity_id} — USDC capacity snapshot."""
        pid = quote(identity_id, safe="")
        return await _get(f"/v1/capacity/{pid}")

    @mcp.tool()
    async def karma_lock_usdc(identity_id: str, amount: float) -> dict[str, Any]:
        """POST /v1/capacity/{identity_id}/lock — reserve capacity (JSON {amount})."""
        pid = quote(identity_id, safe="")
        return await _post_json(f"/v1/capacity/{pid}/lock", {"amount": amount})

    @mcp.tool()
    async def karma_get_evidence_bundle(bundle_id: str) -> dict[str, Any]:
        """GET /v1/bundles/{bundle_id} — fetch evidence bundle by id (path URL-encoded)."""
        bid = quote(bundle_id, safe="")
        return await _get(f"/v1/bundles/{bid}")

    @mcp.tool()
    async def karma_get_evidence_bundle_by_task(task_id: str) -> dict[str, Any]:
        """GET /v1/bundles/task/{task_id} — fetch bundle for a task."""
        tid = quote(task_id, safe="")
        return await _get(f"/v1/bundles/task/{tid}")

    @mcp.tool()
    async def karma_submit_evidence_bundle(bundle_json: str) -> dict[str, Any]:
        """
        POST /v1/bundles — body is full EvidenceBundle JSON string
        (same fields as openapi EvidenceBundle schema).
        """
        body = json.loads(bundle_json)
        return await _post_json("/v1/bundles", body)

    return mcp


def main() -> None:
    """Entrypoint: ``python -m karma_openclaw`` or ``karma-openclaw-mcp``."""
    build_app().run(transport="stdio")
