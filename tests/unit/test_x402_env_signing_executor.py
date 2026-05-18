"""Env signing x402 executor."""

from __future__ import annotations

import pytest
from eth_account import Account

from sdk.x402.chain_executor import EnvSigningX402PaymentExecutor
from sdk.x402.models import PaymentRequiredAccept


@pytest.mark.asyncio
async def test_env_signing_produces_non_mock_tx_hash():
    acct = Account.create()
    accept = PaymentRequiredAccept(
        scheme="exact",
        network="base-sepolia",
        maxAmountRequired="1.5",
        asset="USDC",
        payTo="0x" + "a" * 40,
        resource="https://api.example.com/r",
    )
    ex = EnvSigningX402PaymentExecutor(private_key=acct.key.hex())
    proof = await ex.pay(accept=accept, resource_url="https://api.example.com/r")
    assert proof.payment_signature_b64
    assert proof.tx_hash.startswith("0x")
    assert not proof.tx_hash.startswith("0xmock")
