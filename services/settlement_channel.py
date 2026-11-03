"""Signed, sequenced off-chain settlement states (payment-channel primitive).

Within an already-locked allowance the two parties keep exchanging signed
states with a strictly increasing sequence number, instead of every move
hitting the chain. When an amount or time threshold is crossed, the *latest*
states are aggregated into one deterministic batch hash and submitted in a
single on-chain anchor. Replay protection is the monotonic sequence number:
a stale (lower-or-equal) state is rejected, and either party can always exit
with the counterparty's last-signed state as evidence.
"""
from __future__ import annotations

import hashlib
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException

DOMAIN = "Karma Settlement Channel v1"


def _normalize_sig(signature: str) -> bytes:
    s = (signature or "").strip()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 130:
        raise HTTPException(400, "signature must be 65-byte hex (0x + 130 hex chars)")
    try:
        return bytes.fromhex(s)
    except ValueError as exc:
        raise HTTPException(400, "signature is not valid hex") from exc


def canonical_state_message(
    *,
    channel_id: str,
    seq: int,
    balances: dict[str, str],
    meta_hash: str,
) -> str:
    """Deterministic EIP-191 text both sides rebuild and sign.

    ``balances`` maps party address -> decimal amount string. Sorting the
    parties makes the message independent of dict insertion order, so both
    sides reconstruct byte-for-byte identical text.
    """
    balance_lines = "".join(
        f"\n{party}:{amount}" for party, amount in sorted(balances.items())
    )
    return (
        f"{DOMAIN}\n"
        f"channel_id:{channel_id}\n"
        f"seq:{int(seq)}\n"
        f"meta_hash:{meta_hash}"
        f"{balance_lines}"
    )


def sign_state(
    *,
    channel_id: str,
    seq: int,
    balances: dict[str, str],
    meta_hash: str,
    private_key: str,
) -> str:
    """Return a 0x-prefixed EIP-191 signature over the canonical state."""
    message = canonical_state_message(
        channel_id=channel_id, seq=seq, balances=balances, meta_hash=meta_hash
    )
    signed = Account.sign_message(encode_defunct(text=message), private_key=private_key)
    return "0x" + signed.signature.hex()


def recover_signer(
    *,
    channel_id: str,
    seq: int,
    balances: dict[str, str],
    meta_hash: str,
    signature: str,
) -> str:
    """Recover the address that signed a state (0x-prefixed)."""
    message = canonical_state_message(
        channel_id=channel_id, seq=seq, balances=balances, meta_hash=meta_hash
    )
    try:
        return Account.recover_message(
            encode_defunct(text=message), signature=_normalize_sig(signature)
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "signature verification failed") from exc


def verify_state(
    *,
    channel_id: str,
    seq: int,
    balances: dict[str, str],
    meta_hash: str,
    signature: str,
    signer_address: str,
) -> bool:
    """True when the signature recovers to ``signer_address`` (case-insensitive)."""
    return recover_signer(
        channel_id=channel_id,
        seq=seq,
        balances=balances,
        meta_hash=meta_hash,
        signature=signature,
    ).lower() == (signer_address or "").strip().lower()


def state_batch_hash(states: list[dict[str, Any]]) -> str:
    """Deterministic hash over a batch of canonical state encodings.

    This is the single value that goes on-chain as the batch anchor: any state
    mutation (seq, balances, meta_hash) changes the digest, so a stale batch
    cannot be replayed against the chain anchor.
    """
    payload = "|".join(
        canonical_state_message(
            channel_id=str(s["channel_id"]),
            seq=int(s["seq"]),
            balances=s["balances"],
            meta_hash=str(s["meta_hash"]),
        )
        for s in states
    )
    return "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def batch_due(
    *,
    total_value: float,
    value_threshold: float,
    seq: int,
    seq_threshold: int,
) -> bool:
    """True when the channel has crossed its amount or state-count threshold."""
    return total_value >= value_threshold or seq >= seq_threshold


class ChannelLedger:
    """Monotonic-sequence replay guard for a single channel.

    Tracks the highest accepted ``seq`` and the latest state plus per-party
    signatures, so one party can produce exit evidence without the other being
    online.
    """

    def __init__(self, parties: set[str]):
        self.parties = {p.lower() for p in parties}
        self.latest_seq: int = -1
        self.latest: dict[str, Any] | None = None
        self.signatures: dict[str, str] = {}

    def apply(
        self,
        *,
        state: dict[str, Any],
        signature: str,
        signer_address: str,
    ) -> dict[str, Any]:
        signer = (signer_address or "").strip().lower()
        if signer not in self.parties:
            raise HTTPException(403, "signer is not a channel party")
        if not verify_state(
            channel_id=state["channel_id"],
            seq=int(state["seq"]),
            balances=state["balances"],
            meta_hash=state["meta_hash"],
            signature=signature,
            signer_address=signer,
        ):
            raise HTTPException(403, "state signature does not match signer")
        seq = int(state["seq"])
        if seq <= self.latest_seq:
            raise HTTPException(409, "stale state: seq must be strictly increasing")
        self.latest_seq = seq
        self.latest = dict(state)
        self.signatures[signer] = signature
        return self.latest

    def exit_evidence(self) -> dict[str, Any]:
        """Latest accepted state + its signatures, for one-sided on-chain exit."""
        if self.latest is None:
            raise HTTPException(409, "no accepted state to exit with")
        return {
            "state": self.latest,
            "latest_seq": self.latest_seq,
            "signatures": dict(self.signatures),
        }
