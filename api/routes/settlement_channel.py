"""Settlement-channel helper endpoints (stateless crypto primitives).

The channel is peer-to-peer: parties sign states off-chain and submit the
latest batch hash on-chain. These endpoints let clients reconstruct the exact
message to sign, verify a signature, and compute the deterministic batch
anchor without reimplementing the canonical encoding.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import settlement_channel

router = APIRouter(prefix="/v1/settlement-channel", tags=["SettlementChannel"])


class StateBody(BaseModel):
    channel_id: str = Field(min_length=1, max_length=128)
    seq: int = Field(ge=0)
    balances: dict[str, str]
    meta_hash: str = Field(min_length=1, max_length=128)


class VerifyBody(StateBody):
    signature: str
    signer_address: str


class BatchBody(BaseModel):
    states: list[StateBody]


@router.post("/sign-message")
async def sign_message(body: StateBody) -> dict[str, Any]:
    return {
        "message": settlement_channel.canonical_state_message(
            channel_id=body.channel_id,
            seq=body.seq,
            balances=body.balances,
            meta_hash=body.meta_hash,
        )
    }


@router.post("/verify")
async def verify(body: VerifyBody) -> dict[str, Any]:
    try:
        signer = settlement_channel.recover_signer(
            channel_id=body.channel_id,
            seq=body.seq,
            balances=body.balances,
            meta_hash=body.meta_hash,
            signature=body.signature,
        )
    except HTTPException:
        raise
    return {
        "valid": signer.lower() == body.signer_address.strip().lower(),
        "signer": signer,
    }


@router.post("/batch-hash")
async def batch_hash(body: BatchBody) -> dict[str, Any]:
    states = [
        {
            "channel_id": s.channel_id,
            "seq": s.seq,
            "balances": s.balances,
            "meta_hash": s.meta_hash,
        }
        for s in body.states
    ]
    return {"batch_hash": settlement_channel.state_batch_hash(states)}
