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
