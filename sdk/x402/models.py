"""x402 data models (HTTP transport + Karma audit bridge)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.schemas import ExternalPaymentRecord  # noqa: F401 — re-export


class PaymentRequiredAccept(BaseModel):
    """One accepted payment option from a 402 response."""

    scheme: str = "exact"
    network: str = ""
    max_amount_required: str = Field(default="0", alias="maxAmountRequired")
    asset: str = "USDC"
    pay_to: str = Field(default="", alias="payTo")
    resource: str = ""
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds")

    model_config = {"populate_by_name": True}

    def amount_usdc_float(self) -> float:
        raw = (self.max_amount_required or "0").strip()
        try:
            # x402 amounts may be atomic units (6 decimals) or decimal strings
            val = float(raw)
            if val >= 1_000_000:
                return val / 1_000_000.0
            return val
        except ValueError:
            return 0.0


class PaymentRequiredDocument(BaseModel):
    """Decoded PAYMENT-REQUIRED / JSON 402 body."""

    x402_version: int = Field(default=1, alias="x402Version")
    accepts: list[PaymentRequiredAccept] = Field(default_factory=list)
    error: str | None = None

    model_config = {"populate_by_name": True}

    def pick_accept(self, *, prefer_network: str | None = None) -> PaymentRequiredAccept:
        if not self.accepts:
            raise ValueError("no payment options in 402 response")
        if prefer_network:
            for a in self.accepts:
                if a.network == prefer_network:
                    return a
        return self.accepts[0]


class PaymentProof(BaseModel):
    """Proof attached on retried request (PAYMENT-SIGNATURE header)."""

    protocol: str = "x402"
    network: str = ""
    tx_hash: str | None = None
    payment_signature_b64: str = ""
    amount_usdc: float = 0.0
    pay_to: str = ""
    asset: str = "USDC"


# ExternalPaymentRecord lives in core.schemas (API + DB persistence).
