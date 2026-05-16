"""MCP exposes server automation-readiness check."""

import asyncio

from urllib.parse import quote


def test_build_app_registers_readiness_tool():
    from karma_openclaw.server import build_app

    mcp = build_app()
    tools = asyncio.run(mcp.list_tools())
    assert any(t.name == "karma_check_automation_readiness" for t in tools)


import pytest


@pytest.mark.asyncio
async def test_readiness_query_path_shape(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_api_get(path: str):
        captured["path"] = path
        return {"ready_for_task_automation": True}

    monkeypatch.setattr("karma_openclaw.p0_tools.api_get", fake_api_get)

    task_id = "task-x"
    role = "buyer"
    kid = "buyer-x"
    q = f"?task_id={quote(task_id.strip(), safe='')}&role={quote(role.strip() or 'buyer', safe='')}"
    q += f"&karma_identity_id={quote(kid.strip(), safe='')}"
    await fake_api_get(f"/v1/openclaw/automation-readiness{q}")

    assert "automation-readiness" in captured["path"]
    assert "task-x" in captured["path"]
    assert "buyer-x" in captured["path"]
