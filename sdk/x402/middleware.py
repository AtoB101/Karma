"""Starlette/FastAPI middleware — respond with HTTP 402 + PAYMENT-REQUIRED."""

from __future__ import annotations

import base64
import json
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sdk.x402.models import PaymentRequiredAccept, PaymentRequiredDocument

Handler = Callable[[Request], Awaitable[Response]]


def build_payment_required_header(
    *,
    resource_url: str,
    pay_to: str,
    amount_atomic: str,
    network: str = "base-sepolia",
    asset: str = "USDC",
) -> str:
    doc = PaymentRequiredDocument(
        x402_version=1,
        accepts=[
            PaymentRequiredAccept(
                scheme="exact",
                network=network,
                maxAmountRequired=amount_atomic,
                asset=asset,
                payTo=pay_to,
                resource=resource_url,
            )
        ],
    )
    raw = json.dumps(doc.model_dump(by_alias=True), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


class X402PaymentMiddleware(BaseHTTPMiddleware):
    """
    When request lacks valid PAYMENT-SIGNATURE, return 402 with PAYMENT-REQUIRED.

    Set ``request.state.x402_paid = True`` in an upstream dependency after verifying payment.
    """

    def __init__(
        self,
        app,
        *,
        resource_url: str,
        pay_to: str,
        amount_atomic: str = "1000000",
        network: str = "base-sepolia",
    ) -> None:
        super().__init__(app)
        self._resource_url = resource_url
        self._pay_to = pay_to
        self._amount_atomic = amount_atomic
        self._network = network

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        if getattr(request.state, "x402_paid", False):
            return await call_next(request)
        sig = request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("payment-signature")
        if sig and len(sig) >= 8:
            request.state.x402_paid = True
            return await call_next(request)
        header_val = build_payment_required_header(
            resource_url=self._resource_url,
            pay_to=self._pay_to,
            amount_atomic=self._amount_atomic,
            network=self._network,
        )
        return JSONResponse(
            status_code=402,
            content={"error": "payment_required", "protocol": "x402"},
            headers={"PAYMENT-REQUIRED": header_val},
        )
