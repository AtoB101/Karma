"""双 key 平滑轮换回归用例（JWT / runtime key / 响应 HMAC / 设置校验）。"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

import api.middleware.auth as auth
import services.runtime_key_service as rks
import services.runtime_response_sign as rrs
from config.settings import Settings


def _settings(*, current="new-secret-key", previous="", until=""):
    return Settings(
        app_env="test",
        app_secret_key=current,
        app_secret_key_previous=previous,
        app_secret_key_previous_until=until,
    )


def _old_jwt(secret: str, subject: str = "agent-1") -> str:
    now = datetime.utcnow()
    return jwt.encode(
        {"sub": subject, "exp": now + timedelta(minutes=5), "iat": now},
        secret,
        algorithm=auth.ALGORITHM,
    )


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def test_jwt_previous_key_accepted_during_window(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(previous="old-secret-key", until="2099-01-01T00:00:00Z"))
    assert auth.decode_access_token(_old_jwt("old-secret-key"))["sub"] == "agent-1"


def test_jwt_current_key_still_accepted_during_window(monkeypatch):
    monkeypatch.setattr(
        auth,
        "settings",
        _settings(current="new-secret-key", previous="old-secret-key", until="2099-01-01T00:00:00Z"),
    )
    assert auth.decode_access_token(_old_jwt("new-secret-key"))["sub"] == "agent-1"


def test_jwt_previous_key_rejected_after_window(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(previous="old-secret-key", until="2000-01-01T00:00:00Z"))
    with pytest.raises(HTTPException) as exc:
        auth.decode_access_token(_old_jwt("old-secret-key"))
    assert exc.value.status_code == 401


def test_jwt_previous_key_rejected_when_cleared(monkeypatch):
    # 急刹车：清掉 PREVIOUS，即使 until 还在未来也不认旧 token。
    monkeypatch.setattr(auth, "settings", _settings(previous="", until="2099-01-01T00:00:00Z"))
    with pytest.raises(HTTPException):
        auth.decode_access_token(_old_jwt("old-secret-key"))


# ---------------------------------------------------------------------------
# runtime key 的 secret_hash
# ---------------------------------------------------------------------------


def _hash_with(key: str, *, key_id: str, secret: str) -> str:
    material = (key + ":karma_runtime_key_v1").encode()
    return hmac.new(material, f"{key_id}:{secret}".encode(), hashlib.sha256).hexdigest()


def test_runtime_secret_previous_material_accepted_during_window(monkeypatch):
    monkeypatch.setattr(rks, "settings", _settings(previous="old-secret-key", until="2099-01-01T00:00:00Z"))
    old_hash = _hash_with("old-secret-key", key_id="k1", secret="s1")
    assert rks.runtime_secret_match(key_id="k1", secret="s1", secret_hash=old_hash) == "previous"
    assert rks.verify_runtime_secret(key_id="k1", secret="s1", secret_hash=old_hash) is True


def test_runtime_secret_previous_material_rejected_after_window(monkeypatch):
    monkeypatch.setattr(rks, "settings", _settings(previous="old-secret-key", until="2000-01-01T00:00:00Z"))
    old_hash = _hash_with("old-secret-key", key_id="k1", secret="s1")
    assert rks.runtime_secret_match(key_id="k1", secret="s1", secret_hash=old_hash) is None


def test_runtime_secret_current_material_matches_current(monkeypatch):
    monkeypatch.setattr(
        rks,
        "settings",
        _settings(current="new-secret-key", previous="old-secret-key", until="2099-01-01T00:00:00Z"),
    )
    cur_hash = _hash_with("new-secret-key", key_id="k1", secret="s1")
    assert rks.runtime_secret_match(key_id="k1", secret="s1", secret_hash=cur_hash) == "current"


# ---------------------------------------------------------------------------
# 网关响应 HMAC
# ---------------------------------------------------------------------------


def _hmac_hex(key: str, body: bytes) -> str:
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def test_response_dual_headers_during_window(monkeypatch):
    monkeypatch.setattr(
        rrs,
        "settings",
        _settings(current="new-secret-key", previous="old-secret-key", until="2099-01-01T00:00:00Z"),
    )
    body = b'{"a":1}'
    headers = rrs.runtime_hmac_headers(body)
    assert headers["X-Karma-Response-Signature"] == f"sha256={_hmac_hex('old-secret-key', body)}"
    assert headers["X-Karma-Response-Signature-V2"] == f"sha256={_hmac_hex('new-secret-key', body)}"


def test_response_single_header_without_rotation(monkeypatch):
    monkeypatch.setattr(rrs, "settings", _settings(current="new-secret-key"))
    body = b'{"a":1}'
    headers = rrs.runtime_hmac_headers(body)
    assert headers["X-Karma-Response-Signature"] == f"sha256={_hmac_hex('new-secret-key', body)}"
    assert "X-Karma-Response-Signature-V2" not in headers


# ---------------------------------------------------------------------------
# 设置校验
# ---------------------------------------------------------------------------


def test_secret_rotation_active_only_with_future_deadline():
    active = _settings(previous="old-secret-key", until="2099-01-01T00:00:00Z")
    assert active.secret_rotation_active() is True

    expired = _settings(previous="old-secret-key", until="2000-01-01T00:00:00Z")
    assert expired.secret_rotation_active() is False

    cleared = _settings(previous="", until="2099-01-01T00:00:00Z")
    assert cleared.secret_rotation_active() is False

    unparseable = _settings(previous="old-secret-key", until="not-a-date")
    assert unparseable.secret_rotation_active() is False


def test_production_rejects_previous_equal_current():
    with pytest.raises(ValueError, match="differ"):
        Settings(
            app_env="production",
            app_secret_key="secret-A",
            app_secret_key_previous="secret-A",
            app_secret_key_previous_until="2099-01-01T00:00:00Z",
        )


def test_production_rejects_previous_without_deadline():
    with pytest.raises(ValueError, match="APP_SECRET_KEY_PREVIOUS_UNTIL"):
        Settings(
            app_env="production",
            app_secret_key="secret-A",
            app_secret_key_previous="secret-B",
            app_secret_key_previous_until="",
        )
