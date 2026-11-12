"""GET /v1/info 暴露 WalletConnect projectId（公开值，非密钥）。

前端 cyber 控制台的比特派扫码连接用这个值初始化 WalletConnect provider；
自托管/本地没有配时返回空串，前端会退回 window.KARMA_WC_PROJECT_ID。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_info_exposes_walletconnect_project_id(client: AsyncClient, monkeypatch):
    monkeypatch.setattr("config.settings.settings.wc_project_id", "test-project-id")
    resp = await client.get("/v1/info")
    assert resp.status_code == 200, resp.text
    assert resp.json()["walletconnect"]["project_id"] == "test-project-id"


@pytest.mark.asyncio
async def test_info_walletconnect_project_id_defaults_to_empty(client: AsyncClient, monkeypatch):
    monkeypatch.setattr("config.settings.settings.wc_project_id", "")
    resp = await client.get("/v1/info")
    assert resp.status_code == 200, resp.text
    assert resp.json()["walletconnect"]["project_id"] == ""
