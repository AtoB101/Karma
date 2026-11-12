"""EIP-191 personal message verification for Runtime Key wallet-bound actions."""
from __future__ import annotations

from datetime import datetime

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException


def _normalize_sig(sig: str) -> bytes:
    s = (sig or "").strip()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 130:
        raise HTTPException(status_code=400, detail="wallet_signature must be 65-byte hex (0x + 130 hex chars)")
    try:
        return bytes.fromhex(s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="wallet_signature is not valid hex") from exc


def verify_personal_message(*, message: str, wallet_address: str, wallet_signature: str) -> None:
    """Recover signer and require it to match ``wallet_address`` (case-insensitive)."""
    wa = (wallet_address or "").strip()
    if not wa.startswith("0x") or len(wa) != 42:
        raise HTTPException(status_code=400, detail="wallet_address must be a 0x-prefixed 20-byte address")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message),
            signature=_normalize_sig(wallet_signature),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="wallet_signature verification failed") from exc
    if recovered.lower() != wa.lower():
        raise HTTPException(status_code=403, detail="wallet_signature does not match wallet_address")


def build_create_key_message(
    *,
    karma_identity_id: str,
    wallet_address: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
    expire_time: datetime,
    agent_name: str,
    agent_binding: str | None,
) -> str:
    lines = [
        "Karma Runtime Key Create",
        f"karma_identity_id:{karma_identity_id}",
        f"wallet_address:{wallet_address}",
        f"permissions:{','.join(sorted(permissions))}",
        f"single_limit:{single_limit}",
        f"daily_limit:{daily_limit}",
        f"expire_time:{expire_time.isoformat()}",
        f"agent_name:{agent_name}",
        f"agent_binding:{agent_binding or ''}",
    ]
    return "\n".join(lines)


def build_revoke_key_message(*, key_id: str, karma_identity_id: str, wallet_address: str) -> str:
    return "\n".join(
        [
            "Karma Runtime Key Revoke",
            f"key_id:{key_id}",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
        ]
    )


def build_list_keys_message(*, karma_identity_id: str, wallet_address: str, client_nonce: str) -> str:
    return "\n".join(
        [
            "Karma Runtime Key List",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
            f"client_nonce:{client_nonce}",
        ]
    )
