"""SIWE / EIP-4361 challenge + verify for Karma Identity (MVP)."""
from __future__ import annotations

import os
import re
import secrets
import time
from dataclasses import dataclass
from threading import Lock

from eth_account import Account
from eth_account.messages import encode_defunct


class SiweError(ValueError):
    pass


@dataclass
class SiweChallenge:
    nonce: str
    address: str
    domain: str
    uri: str
    chain_id: int
    issued_at: int
    expiration_time: int
    statement: str
    message: str


_LOCK = Lock()
_CHALLENGES: dict[str, SiweChallenge] = {}


def _domain() -> str:
    return (os.getenv("KARMA_SIWE_DOMAIN") or "karma.local").strip()


def _uri() -> str:
    return (os.getenv("KARMA_SIWE_URI") or "https://karma.local").strip()


def _chain_id() -> int:
    return int(os.getenv("KARMA_SIWE_CHAIN_ID") or os.getenv("KARMA_CHAIN_ID") or "11155111")


def _ttl() -> int:
    return int(os.getenv("KARMA_SIWE_TTL_SECONDS", "600"))


def _normalize_address(address: str) -> str:
    if not isinstance(address, str) or not re.fullmatch(r"0x[a-fA-F0-9]{40}", address.strip()):
        raise SiweError("invalid wallet address")
    return address.strip()


def create_challenge(address: str) -> SiweChallenge:
    addr = _normalize_address(address)
    now = int(time.time())
    nonce = secrets.token_hex(16)
    domain = _domain()
    uri = _uri()
    chain_id = _chain_id()
    exp = now + _ttl()
    statement = "Sign in to Karma Identity for Telegram MiniApp."
    # EIP-4361-ish message (compatible with personal_sign / encode_defunct)
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{addr}\n\n"
        f"{statement}\n\n"
        f"URI: {uri}\n"
        f"Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}\n"
        f"Expiration Time: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(exp))}"
    )
    ch = SiweChallenge(
        nonce=nonce,
        address=addr.lower(),
        domain=domain,
        uri=uri,
        chain_id=chain_id,
        issued_at=now,
        expiration_time=exp,
        statement=statement,
        message=message,
    )
    with _LOCK:
        _CHALLENGES[nonce] = ch
    return ch


def verify_challenge(*, nonce: str, signature: str, address: str | None = None) -> SiweChallenge:
    with _LOCK:
        ch = _CHALLENGES.get(nonce)
    if not ch:
        raise SiweError("challenge not found")
    if int(time.time()) > ch.expiration_time:
        with _LOCK:
            _CHALLENGES.pop(nonce, None)
        raise SiweError("challenge expired")
    if address and address.lower() != ch.address:
        raise SiweError("address mismatch")
    if not signature or not isinstance(signature, str):
        raise SiweError("signature required")

    try:
        recovered = Account.recover_message(encode_defunct(text=ch.message), signature=signature)
    except Exception as exc:  # noqa: BLE001
        raise SiweError(f"invalid signature: {exc}") from exc
    if recovered.lower() != ch.address:
        raise SiweError("signature does not match wallet")

    with _LOCK:
        _CHALLENGES.pop(nonce, None)
    return ch


def reset_for_tests() -> None:
    with _LOCK:
        _CHALLENGES.clear()
