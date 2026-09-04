"""KarmaBilateral direct integration routes (moved from the BFF).

These are the endpoints the karma-openclaw MCP tools call, so agents can drive
lock/bind/settle/finalize with plain X-Karma-Api-Key auth (no HMAC).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import require_auth_if_enabled
from services.chain.settlement_adapter import OnChainSettlementAdapter

router = APIRouter(prefix="/v1/bilateral", tags=["bilateral"])

_adapter: OnChainSettlementAdapter | None = None


def _chain() -> OnChainSettlementAdapter:
    global _adapter
    if _adapter is None:
        _adapter = OnChainSettlementAdapter()
    return _adapter


class LockRequest(BaseModel):
    token: str = Field(description="ERC-20 token address")
    amount: int = Field(description="Amount in base units (6 decimals for USDC)")
    role: str = Field(default="buyer", description="buyer | agent")


class BindRequest(BaseModel):
    buyer_bill_id: int
    agent_bill_id: int
    scope_hash: str = Field(description="0x-prefixed 32-byte hex")


class SettleRequest(BaseModel):
    binding_id: int
    proof_hash: str = Field(description="0x-prefixed 32-byte hex proof hash")


@router.post("/lock")
async def lock(body: LockRequest, _auth=Depends(require_auth_if_enabled)):
    try:
        bill_id = _chain().lock_direct(body.token, body.amount, body.role)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain lock failed: {e}") from e
    return {"bill_id": bill_id, "token": body.token, "amount": body.amount, "state": "MINTED"}


@router.post("/bind")
async def bind(body: BindRequest, _auth=Depends(require_auth_if_enabled)):
    try:
        binding_id = _chain().bind_direct(body.buyer_bill_id, body.agent_bill_id, body.scope_hash)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain bind failed: {e}") from e
    return {
        "binding_id": binding_id,
        "buyer_bill_id": body.buyer_bill_id,
        "agent_bill_id": body.agent_bill_id,
        "state": "ACTIVE",
    }


@router.post("/settle")
async def settle(body: SettleRequest, _auth=Depends(require_auth_if_enabled)):
    try:
        _chain().settle_direct(body.binding_id, body.proof_hash)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain settle failed: {e}") from e
    return _chain().binding_status(body.binding_id)


@router.get("/status/{binding_id}")
async def status(binding_id: int):
    try:
        return _chain().binding_status(binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain status failed: {e}") from e


@router.post("/finalize/{binding_id}")
async def finalize(binding_id: int, _auth=Depends(require_auth_if_enabled)):
    try:
        _chain().finalize_binding(binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain finalize failed: {e}") from e
    return _chain().binding_status(binding_id)
