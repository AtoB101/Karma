"""karma-connect host writers: shapes, idempotency, and preserving neighbours."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from karma_connect.hosts import default_hosts, install, parse_env, upsert_toml_table  # noqa: E402


def test_upsert_toml_table_appends_and_preserves():
    original = 'model = "x"\n\n[other]\nkey = 1\n'
    out = upsert_toml_table(original, "mcp_servers.karma", ['command = "karma-mcp"'])
    assert 'model = "x"' in out
    assert "[other]" in out
    assert "[mcp_servers.karma]" in out
    # the new table is appended, so it cannot swallow the earlier [other] block
    assert out.count("[mcp_servers.karma]") == 1
    assert out.rstrip().endswith('command = "karma-mcp"')


def test_upsert_toml_table_replaces_in_place():
    original = '[mcp_servers.karma]\ncommand = "old"\n\n[other]\nkey = 1\n'
    out = upsert_toml_table(original, "mcp_servers.karma", ['command = "new"'])
    assert out.count("[mcp_servers.karma]") == 1
    assert '"new"' in out and '"old"' not in out
    assert "[other]" in out


def test_parse_env():
    assert parse_env(["A=1", "B=x=y"]) == {"A": "1", "B": "x=y"}
    with pytest.raises(ValueError):
        parse_env(["NOPE"])


def _host(key, tmp_path, monkeypatch, workspace=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path / ".openclaw"))
    hosts = {h.key: h for h in default_hosts(workspace=workspace)}
    return hosts[key]


def test_codex_toml_install_is_idempotent(tmp_path, monkeypatch):
    host = _host("codex", tmp_path, monkeypatch)
    host.config_path.parent.mkdir(parents=True, exist_ok=True)
    host.config_path.write_text('model = "deepseek-chat"\n', encoding="utf-8")

    first = install(host, "karma", "karma-mcp", [], {"KARMA_RPC_URL": "https://rpc"})
    assert first["changed"] is True
    text = host.config_path.read_text(encoding="utf-8")
    assert 'model = "deepseek-chat"' in text
    assert "[mcp_servers.karma]" in text
    assert "command = \"karma-mcp\"" in text
    assert 'KARMA_RPC_URL = "https://rpc"' in text

    second = install(host, "karma", "karma-mcp", [], {"KARMA_RPC_URL": "https://rpc"})
    assert second["changed"] is False


def test_json_hosts_preserve_siblings(tmp_path, monkeypatch):
    for key in ("claude", "cursor"):
        host = _host(key, tmp_path, monkeypatch)
        host.config_path.parent.mkdir(parents=True, exist_ok=True)
        host.config_path.write_text(json.dumps({"mcpServers": {"other": {"command": "keep-me"}}}),
                                    encoding="utf-8")
        install(host, "karma", "karma-mcp", ["-x"], {"KARMA_CONTRACT": "0xabc"})
        data = json.loads(host.config_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["other"] == {"command": "keep-me"}
        assert data["mcpServers"]["karma"]["command"] == "karma-mcp"
        assert data["mcpServers"]["karma"]["args"] == ["-x"]


def test_muse_entry_shape(tmp_path, monkeypatch):
    host = _host("muse", tmp_path, monkeypatch)
    install(host, "karma", "karma-mcp", [], {"KARMA_RPC_URL": "https://rpc"})
    data = json.loads(host.config_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    entry = data["mcpServers"]["karma"]
    assert entry["type"] == "stdio"
    assert entry["mode"] == "optional"
    assert "transport" not in entry


def test_openclaw_nested_bucket(tmp_path, monkeypatch):
    host = _host("openclaw", tmp_path, monkeypatch)
    host.config_path.parent.mkdir(parents=True, exist_ok=True)
    host.config_path.write_text(json.dumps({"agents": {"entries": {}}}), encoding="utf-8")
    install(host, "karma", "karma-mcp", [], {})
    data = json.loads(host.config_path.read_text(encoding="utf-8"))
    assert data["agents"] == {"entries": {}}
    assert data["mcp"]["servers"]["karma"]["transport"] == "stdio"


def test_vscode_only_with_workspace(tmp_path, monkeypatch):
    keys = {h.key for h in default_hosts(workspace=None)}
    assert "vscode" not in keys
    host = _host("vscode", tmp_path, monkeypatch, workspace=tmp_path)
    install(host, "karma", "karma-mcp", [], {})
    data = json.loads((tmp_path / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    assert data["servers"]["karma"]["type"] == "stdio"


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    host = _host("muse", tmp_path, monkeypatch)
    result = install(host, "karma", "karma-mcp", [], {}, dry_run=True)
    assert result["dry_run"] is True
    assert not host.config_path.exists()


def test_module_mode_uses_this_python_and_adds_pythonpath(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from karma_connect.cli import _resolve
    from argparse import Namespace

    args = Namespace(name=None, command=None, module="karma_mcp.server", arg=[], env=[])
    name, command, extra, env, defaults = _resolve(args)
    assert name == "karma"
    assert command == sys.executable
    assert extra[:2] == ["-m", "karma_mcp.server"]
    assert env["PYTHONPATH"]
    # KARMA_RUNTIME_URL must be baked in: without it the MCP server talks to
    # http://localhost:8000 and pairing dies before it can hand out a user_code.
    assert env["KARMA_RUNTIME_URL"] == "https://karma-network.ai"
    assert any(d.startswith("KARMA_RUNTIME_URL=") for d in defaults)


def test_explicit_env_beats_the_baked_default():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from karma_connect.cli import _resolve
    from argparse import Namespace

    args = Namespace(name=None, command=None, module="karma_mcp.server", arg=[],
                     env=["KARMA_RUNTIME_URL=http://127.0.0.1:9000"])
    _n, _c, _e, env, defaults = _resolve(args)
    assert env["KARMA_RUNTIME_URL"] == "http://127.0.0.1:9000"
    assert defaults == []


def test_module_mode_rejects_unimportable_module():
    from karma_connect.cli import _module_command

    with pytest.raises(ValueError):
        _module_command("definitely_not_a_real_module_xyz", [], {})
