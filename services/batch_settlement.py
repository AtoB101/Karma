"""Deterministic batch-settlement coordinator for the SettlementBatch contract.

Bridges the off-chain primitives that must all hold before the operator calls
``SettlementBatch.batchSettle`` on-chain:

  1. every state's EIP-191 signature recovers to its declared signer
     (``services.settlement_channel``),
  2. every state's proof payload is retrievable by hash
     (``services.proof_availability``),
  3. binding ids are unique and the batch is ordered deterministically,
  4. the batch anchor is one hash over the canonical state encodings.

The result carries the exact ``batchSettle((uint256,bytes32)[])`` calldata, so
a thin submitter can broadcast it without re-deriving any of the above.
"""
from __future__ import annotations

from typing import Any

from eth_abi import encode
from eth_utils import keccak
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from services import proof_availability, settlement_channel

_BATCH_FUNCTION_SIGNATURE = "batchSettle((uint256,bytes32)[])"
_BATCH_SELECTOR = keccak(text=_BATCH_FUNCTION_SIGNATURE)[:4]


def _normalize_binding_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(422, "binding_id must be an integer")
    if value <= 0:
        raise HTTPException(422, "binding_id must be positive")
    return value


def _normalize_hash32(value: Any) -> str:
    h = (value or "").strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if len(h) != 64:
        raise HTTPException(422, "proof_hash must be 32-byte hex (0x + 64 hex chars)")
    try:
        bytes.fromhex(h)
    except ValueError as exc:
        raise HTTPException(422, "proof_hash is not valid hex") from exc
    return "0x" + h


def validate_batch_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify signatures, enforce unique positive binding ids, sort by id.

    Returns normalized items in deterministic (ascending binding_id) order.
    Raises 422 on shape errors, 403 on a signature mismatch, 409 on duplicates.
    """
    if not isinstance(items, list) or not items:
        raise HTTPException(422, "batch must contain at least one item")

    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(422, "each batch item must be an object")

        binding_id = _normalize_binding_id(item.get("binding_id"))
        if binding_id in seen:
            raise HTTPException(409, f"duplicate binding_id {binding_id}")
        seen.add(binding_id)

        state = item.get("state")
        if not isinstance(state, dict):
            raise HTTPException(422, f"binding {binding_id}: state must be an object")
        signature = item.get("signature") or ""
        signer_address = item.get("signer_address") or ""
        proof_hash = _normalize_hash32(item.get("proof_hash"))

        if not settlement_channel.verify_state(
            channel_id=state.get("channel_id"),
            seq=int(state.get("seq", 0)),
            balances=state.get("balances") or {},
            meta_hash=state.get("meta_hash"),
            signature=signature,
            signer_address=signer_address,
        ):
            raise HTTPException(403, f"binding {binding_id}: state signature mismatch")

        normalized.append(
            {
                "binding_id": binding_id,
                "proof_hash": proof_hash,
                "channel_id": state.get("channel_id"),
                "state": state,
                "signature": signature,
                "signer_address": signer_address.strip().lower(),
            }
        )

    normalized.sort(key=lambda i: i["binding_id"])
    return normalized


def encode_batch_settle_calldata(items: list[dict[str, Any]]) -> str:
    """ABI-encode ``batchSettle((uint256,bytes32)[])`` for the given items.

    Items must already be normalized (see ``validate_batch_items``).
    """
    tuples = [
        (int(item["binding_id"]), bytes.fromhex(item["proof_hash"][2:]))
        for item in items
    ]
    encoded = encode(["(uint256,bytes32)[]"], [tuples])
    return "0x" + (_BATCH_SELECTOR + encoded).hex()


def build_batch_settlement(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate and assemble a settlement batch (signatures + ordering + calldata).

    Data availability is intentionally *not* checked here; call
    ``assert_batch_proofs_available`` first (or pass the result through a
    submitter that does) so a bare hash can never reach the chain.
    """
    normalized = validate_batch_items(items)
    anchor_hash = settlement_channel.state_batch_hash(
        [item["state"] for item in normalized]
    )
    return {
        "count": len(normalized),
        "anchor_hash": anchor_hash,
        "calldata": encode_batch_settle_calldata(normalized),
        "items": [
            {
                "binding_id": item["binding_id"],
                "proof_hash": item["proof_hash"],
                "channel_id": item["channel_id"],
            }
            for item in normalized
        ],
    }


async def assert_batch_proofs_available(
    db: AsyncSession, items: list[dict[str, Any]]
) -> None:
    """Raise 409 unless every item's proof payload is retrievable by hash."""
    for item in items:
        await proof_availability.assert_proof_available(db, item["proof_hash"])
