"""x402 HTTP client — 402 parse, budget check, pay, retry."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import httpx

from sdk.x402.executors import X402PaymentExecutor
from core.schemas import ExternalPaymentRecord
from sdk.x402.models import PaymentRequiredDocument
from sdk.x402.url_safety import UnsafeX402UrlError, validate_x402_target_url

_PAYMENT_REQUIRED_HEADERS = ("payment-required", "x-payment-required")
_PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"


@dataclass
class X402FetchResult:
    status_code: int
    body: bytes
    headers: dict[str, str]
    external_payment: ExternalPaymentRecord | None
    payment_attempts: int


def parse_payment_required_response(
    *,
    status_code: int,
    headers: dict[str, str],
    body: bytes,
) -> PaymentRequiredDocument:
    if status_code != 402:
        raise ValueError(f"expected HTTP 402, got {status_code}")
    hdrs = {k.lower(): v for k, v in headers.items()}
    raw: str | None = None
    for name in _PAYMENT_REQUIRED_HEADERS:
        if name in hdrs:
            raw = hdrs[name]
            break
    if raw:
        try:
            decoded = base64.b64decode(raw, validate=False)
            data = json.loads(decoded.decode("utf-8"))
        except Exception:
            data = json.loads(raw)
        return PaymentRequiredDocument.model_validate(data)
    if body:
        return PaymentRequiredDocument.model_validate(json.loads(body.decode("utf-8")))
    raise ValueError("402 response missing PAYMENT-REQUIRED header and body")


def assert_budget(accept_amount_usdc: float, max_budget_usdc: float) -> None:
    if accept_amount_usdc > max_budget_usdc + 1e-9:
        raise ValueError(f"x402 amount {accept_amount_usdc} exceeds max_budget {max_budget_usdc}")


def assert_resource_matches_url(accept_resource: str, request_url: str) -> None:
    if not accept_resource:
        return
    if accept_resource.rstrip("/") != request_url.rstrip("/"):
        raise ValueError("402 resource does not match requested URL")


class X402Client:
    def __init__(
        self,
        executor: X402PaymentExecutor,
        *,
        timeout_s: float = 60.0,
        allow_private_hosts: bool = False,
    ) -> None:
        self._executor = executor
        self._timeout = timeout_s
        self._allow_private = allow_private_hosts

    async def pay_and_fetch(
        self,
        url: str,
        *,
        max_budget_usdc: float,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        prefer_network: str | None = None,
    ) -> X402FetchResult:
        safe_url = validate_x402_target_url(url, allow_private_hosts=self._allow_private)
        hdrs = dict(headers or {})
        attempts = 0
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            first = await client.request(method, safe_url, headers=hdrs)
            if first.status_code != 402:
                return X402FetchResult(
                    status_code=first.status_code,
                    body=first.content,
                    headers=dict(first.headers),
                    external_payment=None,
                    payment_attempts=0,
                )
            doc = parse_payment_required_response(
                status_code=first.status_code,
                headers=dict(first.headers),
                body=first.content,
            )
            accept = doc.pick_accept(prefer_network=prefer_network)
            amount = accept.amount_usdc_float()
            assert_budget(amount, max_budget_usdc)
            assert_resource_matches_url(accept.resource or safe_url, safe_url)
            attempts = 1
            proof = await self._executor.pay(accept=accept, resource_url=safe_url)
            retry_hdrs = {**hdrs, _PAYMENT_SIGNATURE_HEADER: proof.payment_signature_b64}
            second = await client.request(method, safe_url, headers=retry_hdrs)
            ext = ExternalPaymentRecord(
                protocol="x402",
                tx_hash=proof.tx_hash,
                amount_usdc=proof.amount_usdc or amount,
                resource_url=safe_url,
                payment_proof=proof.payment_signature_b64,
                network=proof.network,
                asset=proof.asset,
            )
            return X402FetchResult(
                status_code=second.status_code,
                body=second.content,
                headers=dict(second.headers),
                external_payment=ext,
                payment_attempts=attempts,
            )
