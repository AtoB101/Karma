import os

import pytest
from karma_mcp_server.http_auth import (
    REMOTE_SCOPE,
    StaticTokenVerifier,
    build_auth_settings,
    configured_token,
)


async def test_verifier_accepts_matching_token():
    v = StaticTokenVerifier("s3cret-token")
    token = await v.verify_token("s3cret-token")
    assert token is not None
    assert token.scopes == [REMOTE_SCOPE]


async def test_verifier_rejects_wrong_and_empty():
    v = StaticTokenVerifier("s3cret-token")
    assert await v.verify_token("wrong") is None
    assert await v.verify_token("") is None
    assert await v.verify_token("s3cret-token ") is not None  # 两侧空白容忍


def test_verifier_requires_non_empty_expected():
    with pytest.raises(ValueError):
        StaticTokenVerifier("")


def test_configured_token_reads_env():
    assert configured_token({"KARMA_MCP_HTTP_TOKEN": " t "}) == "t"
    assert configured_token({}) == ""


def test_auth_settings_require_urls():
    settings = build_auth_settings(default_host="127.0.0.1", default_port=8765)
    assert str(settings.issuer_url).startswith("http://127.0.0.1:8765")
    assert settings.required_scopes == [REMOTE_SCOPE]


def test_forbidden_env_blocks_startup_configuration():
    from karma_mcp_server.credentials import check_forbidden_env

    assert check_forbidden_env({"KARMA_PRIVATE_KEY": "x"}) == ["KARMA_PRIVATE_KEY"]
    assert os.environ.get("KARMA_PRIVATE_KEY") is None
