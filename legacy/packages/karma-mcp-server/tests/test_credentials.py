from karma_mcp_server.credentials import check_forbidden_env, credential, read_agent_env
from karma_mcp_server.redact import fingerprint, redact_wallet


def test_env_wins_over_file():
    got = credential(
        "KARMA_RUNTIME_KEY",
        env={"KARMA_RUNTIME_KEY": "from-env"},
        file_values={"KARMA_RUNTIME_KEY": "from-file"},
    )
    assert got == "from-env"


def test_file_fallback():
    got = credential("KARMA_RUNTIME_KEY", env={}, file_values={"KARMA_RUNTIME_KEY": "from-file"})
    assert got == "from-file"


def test_missing_is_empty_string():
    assert credential("NOPE", env={}, file_values={}) == ""


def test_read_agent_env_parses(tmp_path, monkeypatch):
    p = tmp_path / "agent.env"
    p.write_text("KARMA_RUNTIME_KEY=abc\n# comment\nKARMA_AGENT_ID=x1\n", encoding="utf-8")
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(p))
    values = read_agent_env()
    assert values["KARMA_RUNTIME_KEY"] == "abc"
    assert values["KARMA_AGENT_ID"] == "x1"


def test_read_agent_env_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_AGENT_ENV_PATH", str(tmp_path / "nope.env"))
    assert read_agent_env() == {}


def test_forbidden_env_detects_private_keys():
    found = check_forbidden_env({"KARMA_PRIVATE_KEY": "0xdeadbeef", "KARMA_RUNTIME_KEY": "ok"})
    assert found == ["KARMA_PRIVATE_KEY"]


def test_forbidden_env_clean():
    assert check_forbidden_env({"KARMA_RUNTIME_KEY": "ok"}) == []


def test_fingerprint_never_reveals_secret():
    fp = fingerprint("KRM_RT_secret_value")
    assert "secret" not in fp
    assert len(fp) == 12


def test_redact_wallet():
    assert redact_wallet("0x1234567890abcdef1234567890abcdef12345678") == "0x1234...5678"
    assert redact_wallet("") == ""
