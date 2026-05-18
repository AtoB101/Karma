"""Payment executors for x402 offers."""

from __future__ import annotations

import base64
import json
import secrets
from typing import Protocol

from sdk.x402.models import PaymentProof, PaymentRequiredAccept


class X402PaymentExecutor(Protocol):
    async def pay(self, *, accept: PaymentRequiredAccept, resource_url: str) -> PaymentProof:
        """Produce payment proof for retried HTTP request."""


class MockX402PaymentExecutor:
    """CI/local — deterministic mock tx + PAYMENT-SIGNATURE payload."""

    def __init__(self, *, tx_prefix: str = "0xmock_x402_") -> None:
        self._tx_prefix = tx_prefix

    async def pay(self, *, accept: PaymentRequiredAccept, resource_url: str) -> PaymentProof:
        tx = self._tx_prefix + secrets.token_hex(16)
        payload = {
            "x402Version": 1,
            "scheme": accept.scheme,
            "network": accept.network,
            "txHash": tx,
            "resource": resource_url or accept.resource,
        }
        b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        return PaymentProof(
            protocol="x402",
            network=accept.network,
            tx_hash=tx,
            payment_signature_b64=b64,
            amount_usdc=accept.amount_usdc_float(),
            pay_to=accept.pay_to,
            asset=accept.asset,
        )
