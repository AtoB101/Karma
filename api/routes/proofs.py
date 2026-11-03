"""Proof data-availability endpoints — store / retrieve the bytes behind a hash."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services import proof_availability

router = APIRouter(prefix="/v1/proofs", tags=["ProofAvailability"])


class StoreProofBody(BaseModel):
    payload: str = Field(min_length=1, description="The proof payload whose sha256 is the proof_hash")
    proof_hash: str | None = Field(default=None, description="Optional expected sha256 (0x + 64 hex)")
    meta: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=201)
async def store_proof(body: StoreProofBody, db: AsyncSession = Depends(get_db)):
    record = await proof_availability.store_proof(
        db,
        payload=body.payload,
        meta=body.meta,
        proof_hash=body.proof_hash,
    )
    await db.commit()
    return {"proof_hash": record.proof_hash, "stored": True}


@router.get("/{proof_hash}")
async def retrieve_proof(proof_hash: str, db: AsyncSession = Depends(get_db)):
    return await proof_availability.retrieve_proof(db, proof_hash)


@router.get("/{proof_hash}/available")
async def available(proof_hash: str, db: AsyncSession = Depends(get_db)):
    return {
        "proof_hash": proof_availability._normalize_hash(proof_hash),
        "available": await proof_availability.proof_available(db, proof_hash),
    }
