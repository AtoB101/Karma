"""Self-serve first-key client: challenge -> claim -> (later) grant-gated upgrade.

This is the agent-side half of ``services/agent_first_key``. A brand-new agent has
no credential yet, so ``acquire`` is unauthenticated; after the owner approves a
spending grant, ``upgrade`` exchanges the restricted key for a full-scope key.

Persisted credentials live in the same ``~/.karma/agent.env`` the rest of
``karma-openclaw`` uses (``KARMA_DEVICE_ID``, ``KARMA_API_KEY``, ``KARMA_AGENT_ID``).
"""
from __future__ import annotations

import json
import os
import secrets
from typing import Any

import httpx

from karma_openclaw.agent_env import upsert_credential
from karma_openclaw.http_client import api_key, runtime_base_url

DEVICE_ID_KEY = "KARMA_DEVICE_ID"


def device_id() -> str:
    """Stable per-host device id; generated once and stored in agent.env."""
    env = _read_agent_env_file()
    existing = env.get(DEVICE_ID_KEY, "").strip()
    if existing:
        return existing
    value = f"device-{secrets.token_hex(12)}"
    upsert_credential(DEVICE_ID_KEY, value)
    return value


def acquire(base_url: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
    """Run challenge -> claim and persist the returned restricted key."""
    base = (base_url or runtime_base_url()).rstrip("/")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        r = client.post(
            "/v1/agents/first-key/challenge",
            json={"device_id": device_id(), "agent_name": agent_name},
        )
        _raise_for(r, "first-key/challenge")
        challenge = r.json()

        r = client.post(
            "/v1/agents/first-key/claim",
            json={
                "challenge_id": challenge["challenge_id"],
                "challenge": challenge["challenge"],
                "device_id": device_id(),
            },
        )
        _raise_for(r, "first-key/claim")
        issued = r.json()

    upsert_credential("KARMA_API_KEY", issued["api_key"])
    upsert_credential("KARMA_AGENT_ID", issued["agent_id"])
    return issued


def upgrade(base_url: str | None = None) -> dict[str, Any]:
    """Exchange the current (restricted) key for a full-scope key.

    Fails with 403 unless the owner has already approved an active spending grant.
    """
    base = (base_url or runtime_base_url()).rstrip("/")
    key = api_key()
    if not key:
        raise RuntimeError("KARMA_API_KEY is not set — acquire a first key first")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        r = client.post(
            "/v1/agents/first-key/upgrade",
            headers={"X-Karma-Api-Key": key},
        )
        _raise_for(r, "first-key/upgrade")
        upgraded = r.json()

    upsert_credential("KARMA_API_KEY", upgraded["api_key"])
    upsert_credential("KARMA_AGENT_ID", upgraded["agent_id"])
    return upgraded


def _read_agent_env_file() -> dict[str, str]:
    path = os.path.expanduser("~/.karma/agent.env")
    try:
        text = path and __import__("pathlib").Path(path).read_text(encoding="utf-8") or ""
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    return values


def _raise_for(resp: httpx.Response, label: str) -> None:
    if resp.status_code < 300:
        return
    try:
        detail = resp.json().get("detail") or resp.text
    except Exception:  # noqa: BLE001
        detail = resp.text
    raise RuntimeError(f"{label} failed ({resp.status_code}): {detail}")
