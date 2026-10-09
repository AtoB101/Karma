from karma_mcp_server.credential_store import (
    upsert_credential,
    write_env_file,
    write_pairing_state,
)


def test_upsert_creates_and_replaces(tmp_path, monkeypatch):
    path = tmp_path / "agent.env"
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(path))
    upsert_credential("KARMA_AGENT_PRIVATE_KEY", "seed-1")
    upsert_credential("KARMA_RUNTIME_KEY", "KRM_RT_kid_secret")
    upsert_credential("KARMA_AGENT_PRIVATE_KEY", "seed-2")
    text = path.read_text(encoding="utf-8")
    assert text.count("KARMA_AGENT_PRIVATE_KEY=") == 1
    assert "KARMA_AGENT_PRIVATE_KEY=seed-2" in text
    assert "KARMA_RUNTIME_KEY=KRM_RT_kid_secret" in text


def test_write_env_file_replaces_whole_file(tmp_path, monkeypatch):
    path = tmp_path / "agent.env"
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(path))
    upsert_credential("OLD", "1")
    write_env_file("KARMA_RUNTIME_KEY=new\n")
    assert path.read_text(encoding="utf-8") == "KARMA_RUNTIME_KEY=new\n"


def test_write_pairing_state_sanitises_name(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_MCP_STATE_DIR", str(tmp_path / "pairings"))
    p = write_pairing_state("AB/../CD", "{}")
    assert p.parent == tmp_path / "pairings"
    assert ".." not in p.name
