"""Batch-settlement endpoints — validate states, check DA, emit calldata.

These endpoints are *stateless with respect to chain submission*: they prove
that a batch is well-formed (signatures + data availability + ordering) and
produce the exact calldata, but broadcasting the transaction is left to the
operator key holder. That keeps the hot path verifiable without putting the
operator key in the web process.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services import batch_settlement

router = APIRouter(prefix="/v1/settlement-batch", tags=["SettlementBatch"])


class StateBody(BaseModel):
    channel_id: str = Field(min_length=1, max_length=128)
    seq: int = Field(ge=0)
    balances: dict[str, str]
    meta_hash: str = Field(min_length=1, max_length=128)


class BatchItem(BaseModel):
    binding_id: int = Field(gt=0)
    proof_hash: str
    state: StateBody
    signature: str
    signer_address: str


class BatchBuildBody(BaseModel):
    items: list[BatchItem] = Field(min_length=1)


@router.post("/build")
async def build_batch(
    body: BatchBuildBody, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items = [
        {
            "binding_id": item.binding_id,
            "proof_hash": item.proof_hash,
            "state": {
                "channel_id": item.state.channel_id,
                "seq": item.state.seq,
                "balances": item.state.balances,
                "meta_hash": item.state.meta_hash,
            },
            "signature": item.signature,
            "signer_address": item.signer_address,
        }
        for item in body.items
    ]
    normalized = batch_settlement.validate_batch_items(items)
    await batch_settlement.assert_batch_proofs_available(db, normalized)
    return batch_settlement.build_batch_settlement(items)
