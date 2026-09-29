# -*- coding: utf-8 -*-
"""配对接入之后，凭据必须**就地生效** —— 不能等宿主重启 MCP server。

这里守的就是这件事：以前只有 ``os.environ`` 一条读路径，claim 把凭据写进
``~/.karma/agent.env`` 之后，正在跑的那个进程还是看不到它，用户配完等于没配。
"""
import io
import os

import karma_openclaw.agent_binding as ab
import karma_openclaw.agent_env as ae
import karma_openclaw.http_client as hc

CREDENTIAL_KEYS = (
    "KARMA_API_KEY",
    "KARMA_RUNTIME_KEY",
    "KARMA_RUNTIME_URL",
    "KARMA_AGENT_ID",
    "KARMA_AGENT_PRIVATE_KEY",
)


def _clean(monkeypatch, tmp_path):
    for key in CREDENTIAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "karma" / "agent.env"
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(path))
    ae.invalidate_agent_env()
    return path


def test_without_a_file_the_runtime_url_falls_back_to_localhost(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    assert hc.runtime_base_url() == "http://localhost:8000"
    assert hc.api_key() is None
    assert hc.runtime_key() is None


def test_the_credential_file_is_picked_up_without_a_restart(monkeypatch, tmp_path):
    path = _clean(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "KARMA_AGENT_ID=agent-live-1\n"
        "KARMA_RUNTIME_URL=https://karma-network.ai\n"
        "KARMA_API_KEY=KRM_API_live_1\n"
        "KARMA_RUNTIME_KEY=KRM_RT_keyid_1\n",
        encoding="utf-8",
    )
    assert hc.runtime_base_url() == "https://karma-network.ai"
    assert hc.api_key() == "KRM_API_live_1"
    assert hc.runtime_key() == "KRM_RT_keyid_1"
    assert ab.agent_id_from_env() == "agent-live-1"


def test_rotating_the_file_is_seen_on_the_next_call(monkeypatch, tmp_path):
    path = _clean(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("KARMA_API_KEY=KRM_API_first\n", encoding="utf-8")
    assert hc.api_key() == "KRM_API_first"
    path.write_text("KARMA_API_KEY=KRM_API_second\n", encoding="utf-8")
    assert hc.api_key() == "KRM_API_second"


def test_an_explicit_env_var_beats_the_file(monkeypatch, tmp_path):
    """宿主显式注入的凭据优先级更高 —— 别被一个旧文件悄悄盖掉。"""
    path = _clean(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("KARMA_API_KEY=KRM_API_from_file\n", encoding="utf-8")
    monkeypatch.setenv("KARMA_API_KEY", "KRM_API_from_env")
    assert hc.api_key() == "KRM_API_from_env"


def test_refresh_credentials_clears_the_cache(monkeypatch, tmp_path):
    path = _clean(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("KARMA_API_KEY=KRM_API_one\n", encoding="utf-8")
    assert hc.api_key() == "KRM_API_one"
    path.write_text("KARMA_API_KEY=KRM_API_two\n", encoding="utf-8")
    hc.refresh_credentials()
    assert hc.api_key() == "KRM_API_two"


def test_pairing_claim_reuses_the_one_shared_path_resolver():
    """写盘和读盘必须是同一个解析结果，否则覆盖了路径就成了两个文件。"""
    import karma_openclaw.pairing_tools as pt

    assert pt.agent_env_path is ae.agent_env_path
