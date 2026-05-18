"""Sepolia ERC-20 transfer executor for x402 (optional testnet)."""

from __future__ import annotations

import asyncio

from eth_account import Account
from web3 import Web3

from sdk.x402.models import PaymentProof, PaymentRequiredAccept
from sdk.x402.payment_signing import (
    build_payment_payload,
    sign_payment_payload,
    usdc_amount_to_atomic,
)

_ERC20_TRANSFER_ABI = [
    {
        "name": "transfer",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
    }
]


def _load_settings():
    from config.settings import settings

    return settings


def _send_usdc_transfer_sync(
    *,
    private_key: str,
    pay_to: str,
    amount_atomic: int,
) -> str:
    settings = _load_settings()
    rpc = (settings.testnet_rpc_url or "").strip()
    token = (settings.erc20_token_address or "").strip()
    if not rpc or not token:
        raise ValueError("X402_PAYMENT_BACKEND=sepolia requires TESTNET_RPC_URL and ERC20_TOKEN_ADDRESS")
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        raise ValueError("could not connect to TESTNET_RPC_URL")
    acct = Account.from_key(private_key)
    token_c = w3.eth.contract(address=Web3.to_checksum_address(token), abi=_ERC20_TRANSFER_ABI)
    tx = token_c.functions.transfer(
        Web3.to_checksum_address(pay_to),
        amount_atomic,
    ).build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            "value": 0,
        }
    )
    est = w3.eth.estimate_gas(tx)
    tx["gas"] = int(est * 1.25)
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, 300)
    if receipt.status != 1:
        raise ValueError(f"USDC transfer reverted: {Web3.to_hex(h)}")
    return Web3.to_hex(h)


class EnvSigningX402PaymentExecutor:
    """Sign PAYMENT-SIGNATURE with dev key; tx_hash is EIP-191 digest (off-chain proof)."""

    def __init__(self, *, private_key: str) -> None:
        if not private_key.strip():
            raise ValueError("env x402 executor requires a private key")
        self._key = private_key.strip()
        self._address = Account.from_key(self._key).address

    async def pay(self, *, accept: PaymentRequiredAccept, resource_url: str) -> PaymentProof:
        payload = build_payment_payload(
            accept=accept,
            resource_url=resource_url,
            payer_address=self._address,
        )
        b64, digest = sign_payment_payload(private_key=self._key, payload=payload)
        return PaymentProof(
            protocol="x402",
            network=accept.network,
            tx_hash=digest,
            payment_signature_b64=b64,
            amount_usdc=accept.amount_usdc_float(),
            pay_to=accept.pay_to,
            asset=accept.asset,
        )


class SepoliaErc20X402PaymentExecutor:
    """USDC transfer on Sepolia + signed PAYMENT-SIGNATURE header."""

    def __init__(self, *, private_key: str) -> None:
        if not private_key.strip():
            raise ValueError("sepolia x402 executor requires a private key")
        self._key = private_key.strip()
        self._address = Account.from_key(self._key).address

    async def pay(self, *, accept: PaymentRequiredAccept, resource_url: str) -> PaymentProof:
        if not accept.pay_to:
            raise ValueError("x402 accept missing payTo address")
        amount_atomic = usdc_amount_to_atomic(accept.amount_usdc_float())
        tx_hash = await asyncio.to_thread(
            _send_usdc_transfer_sync,
            private_key=self._key,
            pay_to=accept.pay_to,
            amount_atomic=amount_atomic,
        )
        payload = build_payment_payload(
            accept=accept,
            resource_url=resource_url,
            payer_address=self._address,
        )
        payload["txHash"] = tx_hash
        b64, _ = sign_payment_payload(private_key=self._key, payload=payload)
        return PaymentProof(
            protocol="x402",
            network=accept.network,
            tx_hash=tx_hash,
            payment_signature_b64=b64,
            amount_usdc=accept.amount_usdc_float(),
            pay_to=accept.pay_to,
            asset=accept.asset,
        )
