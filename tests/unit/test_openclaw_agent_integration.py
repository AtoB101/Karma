"""Tests for Karma ↔ OpenClaw agent SDK integration."""

from __future__ import annotations

import pytest

from sdk.openclaw_agent import KarmaOpenClawAgent
from sdk.integrations import (
    discover_and_connect,
    discover_all,
    validate_discovery,
    build_connect_manifest,
    save_connect_manifest,
    load_connect_manifest,
    probe_runtime_health,
    ENV_KARMA_RUNTIME_URL,
    ENV_KARMA_API_KEY,
    ENV_KARMA_AGENT_ID,
)


# ── Discovery ───────────────────────────────────────────────

def test_discover_all_returns_dict(monkeypatch):
    monkeypatch.setenv(ENV_KARMA_RUNTIME_URL, "http://localhost:8000")
    monkeypatch.setenv(ENV_KARMA_API_KEY, "karma_agent_secret123")
    monkeypatch.setenv(ENV_KARMA_AGENT_ID, "agent-001")
    result = discover_all()
    assert result["runtime_url"] == "http://localhost:8000"
    assert result["api_key"] == "karma_agent_secret123"
    assert result["agent_id"] == "agent-001"


def test_discover_all_empty_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_KARMA_RUNTIME_URL, raising=False)
    monkeypatch.delenv(ENV_KARMA_API_KEY, raising=False)
    monkeypatch.delenv(ENV_KARMA_AGENT_ID, raising=False)
    result = discover_all()
    assert result["runtime_url"] is None
    assert result["api_key"] is None


def test_validate_discovery_missing():
    missing = validate_discovery({"runtime_url": None, "api_key": None})
    assert ENV_KARMA_RUNTIME_URL in missing
    assert ENV_KARMA_API_KEY in missing


def test_validate_discovery_complete():
    missing = validate_discovery({
        "runtime_url": "http://x",
        "api_key": "karma_x_y",
    })
    assert missing == []


# ── Manifest ────────────────────────────────────────────────

def test_build_and_save_load_manifest(tmp_path):
    manifest = build_connect_manifest(
        runtime_url="http://localhost:8000",
        api_key="karma_agent_secret",
        agent_id="agent-42",
        openclaw_gateway="http://127.0.0.1:18789",
    )
    assert manifest["agent_id"] == "agent-42"
    assert manifest["karma_version"] == "0.1.0"
    assert "created_at_utc" in manifest

    path = tmp_path / "connect.json"
    saved = save_connect_manifest(manifest, str(path))
    assert saved == str(path)
    loaded = load_connect_manifest(str(path))
    assert loaded["agent_id"] == "agent-42"


# ── Agent construction ──────────────────────────────────────

def test_karma_openclaw_agent_init():
    agent = KarmaOpenClawAgent(
        agent_id="worker-001",
        runtime_url="http://localhost:8000",
        api_key="karma_worker-001_secret",
    )
    assert agent.agent_id == "worker-001"
    assert agent.runtime_url == "http://localhost:8000"
    assert agent.get_receipt_count("task-1") == 0


def test_karma_openclaw_agent_receipt_tracking():
    agent = KarmaOpenClawAgent(
        agent_id="worker-001",
        runtime_url="http://localhost:8000",
        api_key="karma_worker-001_secret",
    )
    assert agent.get_receipts("task-1") == []
    assert agent.get_receipt_count("task-1") == 0


def test_karma_openclaw_agent_reset():
    agent = KarmaOpenClawAgent(
        agent_id="worker-001",
        runtime_url="http://localhost:8000",
        api_key="karma_worker-001_secret",
    )
    agent._receipts["task-1"] = ["fake"]
    agent._step_counter["task-1"] = 5
    agent.reset("task-1")
    assert agent.get_receipt_count("task-1") == 0


# ── discover_and_connect ────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_and_connect_missing_config(monkeypatch):
    monkeypatch.delenv(ENV_KARMA_RUNTIME_URL, raising=False)
    monkeypatch.delenv(ENV_KARMA_API_KEY, raising=False)
    monkeypatch.delenv(ENV_KARMA_AGENT_ID, raising=False)
    with pytest.raises(RuntimeError, match="Missing required config"):
        await discover_and_connect()


@pytest.mark.asyncio
async def test_discover_and_connect_with_explicit_args(monkeypatch):
    agent = await discover_and_connect(
        agent_id="agent-7",
        runtime_url="http://localhost:8000",
        api_key="karma_agent-7_secret",
    )
    assert agent.agent_id == "agent-7"
    assert agent.runtime_url == "http://localhost:8000"


@pytest.mark.asyncio
async def test_discover_and_connect_from_env(monkeypatch):
    monkeypatch.setenv(ENV_KARMA_RUNTIME_URL, "http://localhost:9999")
    monkeypatch.setenv(ENV_KARMA_API_KEY, "karma_env_agent_key")
    monkeypatch.setenv(ENV_KARMA_AGENT_ID, "env-agent")
    agent = await discover_and_connect()
    assert agent.agent_id == "env-agent"
    assert agent.runtime_url == "http://localhost:9999"


# ── run_tool_sync ───────────────────────────────────────────

def test_run_tool_sync_creates_receipt():
    agent = KarmaOpenClawAgent(
        agent_id="worker-42",
        runtime_url="http://localhost:8000",
        api_key="karma_worker-42_secret",
    )
    receipt = agent.run_tool_sync(
        task_id="task-1",
        tool_name="browser.navigate",
        result={"url": "https://example.com", "status": 200},
        input_data={"url": "https://example.com"},
        success=True,
    )
    assert receipt is not None
    assert receipt.task_id == "task-1"
    assert receipt.agent_id == "worker-42"
    assert receipt.step_index == 1
    assert "mcp.browser.navigate" == receipt.tool_name
    assert receipt.status.value == "success"
    assert agent.get_receipt_count("task-1") == 1


def test_run_tool_sync_failure_receipt():
    agent = KarmaOpenClawAgent(
        agent_id="worker-42",
        runtime_url="http://localhost:8000",
        api_key="karma_worker-42_secret",
    )
    receipt = agent.run_tool_sync(
        task_id="task-1",
        tool_name="api.call",
        result=None,
        input_data={"url": "https://down.example.com"},
        success=False,
        error_message="Connection refused",
    )
    assert receipt.status.value == "failure"
    assert receipt.error_message == "Connection refused"


# ── SDK __init__ exports ────────────────────────────────────

def test_sdk_exports_openclaw_agent():
    from sdk import KarmaOpenClawAgent
    assert KarmaOpenClawAgent is not None


def test_sdk_exports_integration_functions():
    from sdk import discover_and_connect, discover_all, validate_discovery
    assert callable(discover_and_connect)
    assert callable(discover_all)
    assert callable(validate_discovery)


def test_sdk_exports_manifest_helpers():
    from sdk import build_connect_manifest, save_connect_manifest, load_connect_manifest
    assert callable(build_connect_manifest)
    assert callable(save_connect_manifest)
    assert callable(load_connect_manifest)


def test_sdk_exports_env_keys():
    from sdk import ENV_KARMA_RUNTIME_URL, ENV_KARMA_API_KEY, ENV_KARMA_AGENT_ID
    assert ENV_KARMA_RUNTIME_URL == "KARMA_RUNTIME_URL"
    assert ENV_KARMA_API_KEY == "KARMA_API_KEY"
    assert ENV_KARMA_AGENT_ID == "KARMA_AGENT_ID"


# ── Re-export consistency ───────────────────────────────────

def test_sdk_all_exports_match():
    from sdk import __all__ as sdk_all
    import sdk
    for name in sdk_all:
        assert hasattr(sdk, name), f"__all__ lists {name!r} but sdk has no such attribute"
