from karma_mcp_server.pairing import (
    credentials_env_text,
    load_pairing,
    resolve_pairing_code,
    save_pairing,
)


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_MCP_STATE_DIR", str(tmp_path / "pairings"))
    path = save_pairing({"user_code": "ABCD1234", "pairing_code": "PC-SECRET"})
    assert path.exists()
    got = load_pairing("abcd1234")
    assert got is not None
    assert got["pairing_code"] == "PC-SECRET"


def test_load_pairing_empty_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_MCP_STATE_DIR", str(tmp_path / "pairings"))
    assert load_pairing() is None


def test_resolve_prefers_explicit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_MCP_STATE_DIR", str(tmp_path / "pairings"))
    save_pairing({"user_code": "U1", "pairing_code": "SAVED"})
    code, record = resolve_pairing_code("EXPLICIT")
    assert code == "EXPLICIT"
    assert record is None
    code2, record2 = resolve_pairing_code("", "U1")
    assert code2 == "SAVED"
    assert record2 is not None


def test_credentials_env_text_only_includes_present_values():
    text = credentials_env_text(
        "agent-9",
        "http://karma.test",
        {"KARMA_RUNTIME_KEY": "KRM_RT_kid_secret"},
    )
    assert "KARMA_AGENT_ID=agent-9" in text
    assert "KARMA_RUNTIME_URL=http://karma.test" in text
    assert "KARMA_RUNTIME_KEY=KRM_RT_kid_secret" in text
    assert "KARMA_API_KEY" not in text
    assert text.endswith("\n")
