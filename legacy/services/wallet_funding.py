"""Wallet funding gate for identity registration.

Product rule: a wallet must hold funds before Karma mints an identity for it.
Unfunded wallets are *not* rejected outright — onboarding must not dead-end —
they are throttled on a dimension the caller cannot forge (see
``api.middleware.rate_limit.enforce_zero_funding_registration_limit``).

The probe is a read-only RPC call (``eth_getBalance`` + ``balanceOf``). It never
touches a private key, a mnemonic or a signature.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from fastapi import Request

from config.settings import settings

logger = structlog.get_logger(__name__)

_ERC20_BALANCE_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]


def is_dev_like_env() -> bool:
    return (settings.app_env or "").lower() in ("development", "dev", "local", "test")


def _web3():
    from web3 import Web3

    return Web3(
        Web3.HTTPProvider(
            settings.testnet_rpc_url,
            request_kwargs={
                "timeout": int(settings.registration_funding_rpc_timeout_seconds),
            },
        )
    )


@dataclass(frozen=True)
class FundingProbe:
    """Outcome of the balance probe.

    ``checked=False`` means "we could not decide" (dev env, missing RPC URL, or an
    RPC error). Callers treat that as *unfunded* so an RPC outage throttles sybil
    signups instead of either failing open or taking registration down.
    """

    checked: bool
    funded: bool
    native_wei: int
    token_units: int
    reason: str


def probe_wallet_funding(address: str) -> FundingProbe:
    """Read-only balance probe. Never raises."""
    if is_dev_like_env():
        return FundingProbe(False, True, 0, 0, "dev_env_skipped")
    if not (settings.testnet_rpc_url or "").strip():
        return FundingProbe(False, False, 0, 0, "rpc_not_configured")
    try:
        w3 = _web3()
        account = w3.to_checksum_address(address)
        native_wei = int(w3.eth.get_balance(account))
        token_units = 0
        token_address = (settings.erc20_token_address or "").strip()
        if token_address:
            erc20 = w3.eth.contract(
                address=w3.to_checksum_address(token_address),
                abi=_ERC20_BALANCE_ABI,
            )
            token_units = int(erc20.functions.balanceOf(account).call())
        min_native = max(1, int(settings.registration_min_native_wei))
        min_token = max(1, int(settings.registration_min_token_units))
        funded = native_wei >= min_native or token_units >= min_token
        return FundingProbe(True, funded, native_wei, token_units, "ok")
    except Exception as exc:  # noqa: BLE001 — probe must never break registration
        logger.warning("wallet_funding_probe_failed", error=str(exc))
        return FundingProbe(False, False, 0, 0, f"probe_error:{type(exc).__name__}")


async def enforce_registration_funding_gate(request: Request, address: str) -> FundingProbe:
    """Gate a *new* identity creation for ``address``.

    Raises 429 when the wallet holds no funds and its unfunded-registration
    budget is exhausted. A funded wallet never consumes that budget.
    """
    if not settings.registration_require_funding:
        return FundingProbe(False, True, 0, 0, "gate_disabled")

    # The probe is blocking socket I/O against a JSON-RPC endpoint; keep it off
    # the event loop, which is a single thread for the whole process.
    probe = await asyncio.to_thread(probe_wallet_funding, address)
    if not probe.funded:
        from api.middleware.rate_limit import enforce_zero_funding_registration_limit

        await enforce_zero_funding_registration_limit(request)
        logger.info(
            "zero_funding_registration_allowed",
            wallet=address,
            reason=probe.reason,
        )
    return probe
