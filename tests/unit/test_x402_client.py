"""x402 client unit tests."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sdk.x402.client import (
    X402Client,
    assert_budget,
    parse_payment_required_response,
)
from sdk.x402.executors import MockX402PaymentExecutor
from sdk.x402.models import PaymentRequiredDocument
from sdk.x402.url_safety import UnsafeX402UrlError, validate_x402_target_url


def test_parse_payment_required_from_header():
    doc = PaymentRequiredDocument(
        x402Version=1,
        accepts=[
            {
                "scheme": "exact",
                "network": "base-sepolia",
                "maxAmountRequired": "1000000",
                "asset": "USDC",
                "payTo": "0x" + "a" * 40,
                "resource": "https://api.example.com/paid",
            }
        ],
    )
    raw = base64.urlsafe_b64encode(
        json.dumps(doc.model_dump(by_alias=True)).encode()
    ).decode()
    parsed = parse_payment_required_response(
        status_code=402,
        headers={"PAYMENT-REQUIRED": raw},
        body=b"",
    )
    assert parsed.accepts[0].amount_usdc_float() == 1.0


def test_assert_budget_rejects_over_max():
    with pytest.raises(ValueError, match="exceeds max_budget"):
        assert_budget(5.0, 1.0)


def test_url_blocks_private_by_default():
    with pytest.raises(UnsafeX402UrlError):
        validate_x402_target_url("http://127.0.0.1/resource", allow_private_hosts=False)


@pytest.mark.asyncio
async def test_pay_and_fetch_mock_flow():
    doc = PaymentRequiredDocument(
        x402Version=1,
        accepts=[
            {
                "scheme": "exact",
                "network": "base-sepolia",
                "maxAmountRequired": "1.0",
                "asset": "USDC",
                "payTo": "0x" + "b" * 40,
                "resource": "https://api.example.com/resource",
            }
        ],
    )
    hdr = base64.urlsafe_b64encode(
        json.dumps(doc.model_dump(by_alias=True)).encode()
    ).decode()

    resp_402 = MagicMock(status_code=402, content=b"", headers={"PAYMENT-REQUIRED": hdr})
    resp_200 = MagicMock(status_code=200, content=b'{"ok":true}', headers={})

    mock_client = MagicMock()
    mock_client.request = AsyncMock(side_effect=[resp_402, resp_200])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("sdk.x402.client.httpx.AsyncClient", return_value=mock_client):
        client = X402Client(MockX402PaymentExecutor())
        result = await client.pay_and_fetch("https://api.example.com/resource", max_budget_usdc=5.0)

    assert result.status_code == 200
    assert result.external_payment is not None
    assert result.external_payment.tx_hash
    assert result.payment_attempts == 1
