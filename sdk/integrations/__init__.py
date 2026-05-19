"""
Karma SDK — One-Click Integrations
====================================
Discover, authenticate, and wrap external agent runtimes (OpenClaw, OpenManus)
in a single call.  Designed to make ``import karma.sdk`` the only dependency
needed before an agent runtime can start producing verified Karma receipts.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Environment variable keys ──────────────────────────────────────
ENV_KARMA_RUNTIME_URL  = "KARMA_RUNTIME_URL"
ENV_KARMA_API_KEY      = "KARMA_API_KEY"
ENV_KARMA_AGENT_ID     = "KARMA_AGENT_ID"
ENV_OPENCLAW_GATEWAY   = "OPENCLAW_GATEWAY_URL"       # auto-discovery
ENV_OPENCLAW_MCP_BRIDGE = "OPENCLAW_MCP_BRIDGE_PORT"

# ── Defaults ──────────────────────────────────────────────────────
DEFAULT_LOCAL_RUNTIME  = "http://localhost:8000"
DEFAULT_OPENCLAW_GW    = "http://127.0.0.1:18789"


# ═══════════════════════════════════════════════════════════════════
# Discovery
# ═══════════════════════════════════════════════════════════════════

def discover_runtime_url() -> Optional[str]:
    """Return Karma runtime URL from env, or None."""
    return os.getenv(ENV_KARMA_RUNTIME_URL)


def discover_api_key() -> Optional[str]:
    """Return Karma API key from env, or None."""
    return os.getenv(ENV_KARMA_API_KEY)


def discover_agent_id() -> Optional[str]:
    """Return agent id from env, or parse from API key."""
    agent_id = os.getenv(ENV_KARMA_AGENT_ID)
    if agent_id:
        return agent_id
    key = discover_api_key()
    if key and key.startswith("karma_"):
        parts = key.split("_")
        if len(parts) >= 3:
            return parts[1]
    return None


def discover_openclaw_gateway() -> Optional[str]:
    """Return OpenClaw gateway URL from env or default."""
    return os.getenv(ENV_OPENCLAW_GATEWAY, DEFAULT_OPENCLAW_GW)


def discover_all() -> dict[str, Optional[str]]:
    """Discover all integration parameters from environment."""
    return {
        "runtime_url": discover_runtime_url(),
        "api_key": discover_api_key(),
        "agent_id": discover_agent_id(),
        "openclaw_gateway": discover_openclaw_gateway(),
    }


def validate_discovery(discovered: dict[str, Optional[str]]) -> list[str]:
    """Return list of missing required config keys."""
    missing = []
    if not discovered.get("runtime_url"):
        missing.append(ENV_KARMA_RUNTIME_URL)
    if not discovered.get("api_key"):
        missing.append(ENV_KARMA_API_KEY)
    return missing


# ═══════════════════════════════════════════════════════════════════
# Quick-connect helpers
# ═══════════════════════════════════════════════════════════════════

async def probe_runtime_health(runtime_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """
    Lightweight health-check probe against a Karma runtime.

    Returns ``{"ok": True, "info": {...}}`` or ``{"ok": False, "error": ...}``.
    """
    import httpx
    url = runtime_url.rstrip("/") + "/v1/info"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return {"ok": True, "info": resp.json()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def probe_openclaw_gateway(
    gateway_url: str = DEFAULT_OPENCLAW_GW,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """
    Probe an OpenClaw gateway to confirm it is reachable.

    Returns ``{"ok": True, "version": "..."}`` or ``{"ok": False, "error": ...}``.
    """
    import httpx
    url = gateway_url.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return {"ok": True, "status": resp.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def discover_and_connect(
    agent_id: Optional[str] = None,
    runtime_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> "KarmaOpenClawAgent":   # noqa: F821 — forward ref
    """
    One-click: discover environment config and return a ready-to-use
    ``KarmaOpenClawAgent``.

    Priority: explicit args > environment variables > defaults.

    Raises ``RuntimeError`` if required config is missing.
    """
    from sdk.openclaw_agent import KarmaOpenClawAgent

    url = runtime_url or discover_runtime_url()
    key = api_key or discover_api_key()
    aid = agent_id or discover_agent_id()

    missing = []
    if not url:
        missing.append(ENV_KARMA_RUNTIME_URL)
    if not key:
        missing.append(ENV_KARMA_API_KEY)
    if not aid:
        missing.append("agent_id or " + ENV_KARMA_AGENT_ID)

    if missing:
        raise RuntimeError(
            "Missing required config for one-click connect: "
            + ", ".join(missing)
            + "\nSet environment variables or pass args explicitly."
        )

    agent = KarmaOpenClawAgent(
        agent_id=aid,
        runtime_url=url,
        api_key=key,
    )

    # Quick health check
    health = await probe_runtime_health(url)
    if not health["ok"]:
        logger.warning("Karma runtime health check failed: %s", health.get("error"))
        # Don't block — agent can still be used; KARMA_API may start later.

    return agent


# ═══════════════════════════════════════════════════════════════════
# Connection manifest (for console / UI)
# ═══════════════════════════════════════════════════════════════════

def build_connect_manifest(
    runtime_url: str,
    api_key: str,
    agent_id: str,
    openclaw_gateway: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build a connection manifest dict that can be saved to disk or
    passed between processes.  Useful for the Console → Agent handoff.
    """
    manifest = {
        "karma_runtime_url": runtime_url,
        "karma_api_key": api_key,
        "agent_id": agent_id,
        "karma_version": "0.1.0",
        "created_at_utc": "",
    }
    from datetime import datetime, timezone
    manifest["created_at_utc"] = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    if openclaw_gateway:
        manifest["openclaw_gateway"] = openclaw_gateway
    return manifest


def save_connect_manifest(manifest: dict[str, Any], path: str = "./karma-connect.json") -> str:
    """Persist connection manifest to a JSON file. Returns the path."""
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return path


def load_connect_manifest(path: str = "./karma-connect.json") -> dict[str, Any]:
    """Load a previously saved connection manifest."""
    with open(path) as f:
        return json.load(f)
