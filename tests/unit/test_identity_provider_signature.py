"""回调签名校验：这是第三方核验唯一的一道门，必须逐条钉死。

为什么单独测它：服务商的回调没有 Karma 令牌，**只有签名**。签名校验一旦松掉，
等于任何人都能 POST 一条「核验通过」把任意身份点亮。
"""
from __future__ import annotations

import time

import pytest

from services.identity_provider.base import ProviderSignatureError
from services.identity_provider.signature import (
    assert_fresh,
    hmac_sha256_hex,
    parse_timestamped_signature,
    sha256_hex,
    sign_timestamped_hmac,
    verify_timestamped_hmac,
)

SECRET = "callback-secret-for-tests"
BODY = b'{"outcome":"verified","session_id":"abc"}'


def _verify(*, header, body=BODY, secret=SECRET, tolerance=300, now=None):
    return verify_timestamped_hmac(
        secret=secret,
        raw_body=body,
        header=header,
        tolerance_seconds=tolerance,
        now=now,
    )


def test_sign_then_verify_round_trip():
    header = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=1_700_000_000)
    assert header.startswith("t=1700000000,v1=")
    _verify(header=header, now=1_700_000_010)


def test_signature_is_deterministic_and_body_bound():
    a = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=1_700_000_000)
    b = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=1_700_000_000)
    assert a == b
    other = sign_timestamped_hmac(secret=SECRET, raw_body=BODY + b" ", timestamp=1_700_000_000)
    assert a != other


def test_tampered_body_is_rejected():
    header = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=1_700_000_000)
    with pytest.raises(ProviderSignatureError):
        _verify(header=header, body=b'{"outcome":"verified","session_id":"xxx"}', now=1_700_000_010)


def test_wrong_secret_is_rejected():
    header = sign_timestamped_hmac(secret="not-our-secret", raw_body=BODY, timestamp=1_700_000_000)
    with pytest.raises(ProviderSignatureError):
        _verify(header=header, now=1_700_000_010)


def test_old_callback_is_rejected_as_replay():
    header = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=1_700_000_000)
    with pytest.raises(ProviderSignatureError) as exc:
        _verify(header=header, now=1_700_000_000 + 3600)
    assert exc.value.status == 401


def test_future_callback_is_rejected_too():
    header = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=1_700_000_000)
    with pytest.raises(ProviderSignatureError):
        _verify(header=header, now=1_700_000_000 - 3600)


def test_tolerance_window_boundary():
    assert_fresh(1_700_000_000, tolerance_seconds=300, now=1_700_000_300)
    with pytest.raises(ProviderSignatureError):
        assert_fresh(1_700_000_000, tolerance_seconds=300, now=1_700_000_301)


def test_missing_header_is_rejected():
    with pytest.raises(ProviderSignatureError):
        parse_timestamped_signature(None)
    with pytest.raises(ProviderSignatureError):
        parse_timestamped_signature("")


def test_malformed_header_is_rejected():
    for header in ("v1=deadbeef", "t=1700000000", "t=notanumber,v1=deadbeef", "nonsense"):
        with pytest.raises(ProviderSignatureError):
            parse_timestamped_signature(header)


def test_empty_secret_never_passes():
    """没配密钥时绝不能「放行」—— 那是把签名校验整个关掉。"""
    header = sign_timestamped_hmac(secret="", raw_body=BODY, timestamp=1_700_000_000)
    with pytest.raises(ProviderSignatureError):
        _verify(header=header, secret="", now=1_700_000_010)


def test_multiple_signature_values_accepts_v1():
    header = "t=1700000000,v0=old,v1=" + hmac_sha256_hex(SECRET, b"1700000000." + BODY)
    _verify(header=header, now=1_700_000_010)


def test_sha256_hex_is_stable():
    assert sha256_hex(b"abc") == sha256_hex("abc")
    assert len(sha256_hex(b"abc")) == 64


def test_signature_header_is_case_insensitive_on_secret_hex():
    """服务商有时把 hex 写成大写 —— 大小写不该决定成败。"""
    header = sign_timestamped_hmac(secret=SECRET, raw_body=BODY, timestamp=int(time.time()))
    upper = header.split("v1=")[0] + "v1=" + header.split("v1=")[1].upper()
    _verify(header=upper)
