"""KSA-X402 attack regression tests."""

from __future__ import annotations

import pytest

from sdk.x402.client import assert_budget, assert_resource_matches_url
from sdk.x402.url_safety import UnsafeX402UrlError, validate_x402_target_url


def test_ksa_x402_001_budget_cap():
    with pytest.raises(ValueError, match="exceeds max_budget"):
        assert_budget(100.0, 10.0)


def test_ksa_x402_002_resource_mismatch():
    with pytest.raises(ValueError, match="does not match"):
        assert_resource_matches_url("https://evil.com/other", "https://api.example.com/resource")


def test_ksa_x402_003_path_traversal():
    with pytest.raises(UnsafeX402UrlError, match="path traversal"):
        validate_x402_target_url("https://api.example.com/a/../secret", allow_private_hosts=True)


def test_ksa_x402_004_private_ip_blocked():
    with pytest.raises(UnsafeX402UrlError):
        validate_x402_target_url("http://10.0.0.5/x", allow_private_hosts=False)


def _stub_dns(monkeypatch, *addresses):
    import ipaddress

    import sdk.x402.url_safety as url_safety

    monkeypatch.setattr(
        url_safety,
        "resolve_host_ips",
        lambda host: [ipaddress.ip_address(a) for a in addresses],
    )


def test_ksa_x402_005_hostname_pointing_at_metadata_is_blocked(monkeypatch):
    # 裸域名以前直接放行：evil.test -> 169.254.169.254 就能读到云元数据。
    _stub_dns(monkeypatch, "169.254.169.254")
    with pytest.raises(UnsafeX402UrlError, match="resolves to a private/reserved"):
        validate_x402_target_url("http://metadata.evil.test/latest/meta-data/", allow_private_hosts=False)


def test_ksa_x402_006_unresolvable_hostname_is_blocked(monkeypatch):
    _stub_dns(monkeypatch)
    with pytest.raises(UnsafeX402UrlError, match="did not resolve"):
        validate_x402_target_url("http://nxdomain.evil.test/x", allow_private_hosts=False)


def test_ksa_x402_007_public_hostname_still_allowed(monkeypatch):
    _stub_dns(monkeypatch, "93.184.216.34")
    assert validate_x402_target_url("https://api.example.com/paid", allow_private_hosts=False) == (
        "https://api.example.com/paid"
    )


def test_x402_key_prefers_the_dedicated_key(monkeypatch):
    from config.settings import settings
    from sdk.x402.executors import resolve_x402_private_key

    monkeypatch.setattr(settings, "x402_private_key", "0x" + "11" * 32)
    monkeypatch.setattr(settings, "karma_signing_dev_private_key", "0x" + "22" * 32)
    monkeypatch.setattr(settings, "testnet_private_key", "0x" + "33" * 32)
    assert resolve_x402_private_key() == "0x" + "11" * 32


def test_x402_key_never_falls_back_to_the_settlement_operator(monkeypatch):
    from config.settings import settings
    from sdk.x402.executors import resolve_x402_private_key

    monkeypatch.setattr(settings, "x402_private_key", "")
    monkeypatch.setattr(settings, "karma_signing_dev_private_key", "")
    monkeypatch.setattr(settings, "testnet_private_key", "")
    monkeypatch.setattr(settings, "settlement_operator_private_key", "0x" + "44" * 32)
    with pytest.raises(ValueError, match="X402_PRIVATE_KEY"):
        resolve_x402_private_key()
