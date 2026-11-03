"""Content-addressed proof availability (data availability for on-chain hashes).

The chain stores only a ``proof_hash``; this module makes the actual bytes
retrievable and verifiable, so "a bare hash" is never treated as proof. An
arbitrator (or the dispute gate) can fetch the payload and recompute the hash.
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import ProofRecordModel


def compute_proof_hash(payload: str) -> str:
    """0x-prefixed sha256 of the payload's UTF-8 bytes."""
    return "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_hash(proof_hash: str) -> str:
    h = (proof_hash or "").strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if len(h) != 64:
        raise HTTPException(400, "proof_hash must be 32-byte hex (0x + 64 hex chars)")
    return "0x" + h


async def store_proof(
    db: AsyncSession,
    *,
    payload: str,
    meta: dict[str, Any] | None = None,
    proof_hash: str | None = None,
) -> ProofRecordModel:
    """Persist a proof payload, optionally verifying it hashes to ``proof_hash``.

    Returns the record idempotently: storing the same payload twice is a no-op.
    """
    if not isinstance(payload, str) or not payload:
        raise HTTPException(400, "payload must be a non-empty string")
    actual = compute_proof_hash(payload)
    if proof_hash is not None:
        expected = _normalize_hash(proof_hash)
        if actual != expected:
            raise HTTPException(
                409,
                f"payload hash mismatch: expected {expected}, got {actual}",
            )
    existing = await db.get(ProofRecordModel, actual)
    if existing is not None:
        return existing
    record = ProofRecordModel(proof_hash=actual, payload=payload, meta=meta or {})
    db.add(record)
    await db.flush()
    return record


async def retrieve_proof(db: AsyncSession, proof_hash: str) -> dict[str, Any]:
    """Return the stored payload for a proof hash, or 404 when unavailable."""
    h = _normalize_hash(proof_hash)
    record = await db.get(ProofRecordModel, h)
    if record is None:
        raise HTTPException(404, "proof payload not available")
    return {
        "proof_hash": record.proof_hash,
        "payload": record.payload,
        "meta": record.meta,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


async def proof_available(db: AsyncSession, proof_hash: str) -> bool:
    """True when a proof hash has a retrievable payload."""
    try:
        h = _normalize_hash(proof_hash)
    except HTTPException:
        return False
    return await db.get(ProofRecordModel, h) is not None


async def assert_proof_available(db: AsyncSession, proof_hash: str) -> None:
    """Raise 409 unless the proof hash is backed by retrievable payload data."""
    if not await proof_available(db, proof_hash):
        raise HTTPException(
            409,
            "proof hash has no retrievable payload — publish the proof data first",
        )
