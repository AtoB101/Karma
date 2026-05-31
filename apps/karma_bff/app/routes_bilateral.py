"""KarmaBilateral integration API — mirrors existing operation flow."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.karma_bff.app import auth, config
from apps.karma_bff.app.deps import read_hmac_json

router = APIRouter(prefix="/v1/bilateral", tags=["bilateral"])


class LockRequest(BaseModel):
    token: str = Field(description="ERC-20 token address")
    amount: int = Field(description="Amount in base units (6 decimals for USDC)")
    role: str = Field(default="buyer", description="buyer | agent")


class LockResponse(BaseModel):
    bill_id: int
    owner: str
    token: str
    amount: int
    state: str


class BindRequest(BaseModel):
    buyer_bill_id: int
    agent_bill_id: int
    scope_hash: str = Field(description="0x-prefixed 32-byte hex")


class BindResponse(BaseModel):
    binding_id: int
    buyer_bill_id: int
    agent_bill_id: int
    state: str


class SettleRequest(BaseModel):
    binding_id: int
    proof_hash: str = Field(description="0x-prefixed 32-byte hex proof hash")


class StatusResponse(BaseModel):
    binding_id: int
    state: str
    bill_states: list[dict]
    can_settle: bool
    can_dispute: bool
    can_finalize: bool
    usdc_locked: int
    settle_after: int | None


def _get_client():
    """Lazy-init KarmaBilateral SDK client."""
    if not config.karma_bilateral_address:
        raise HTTPException(503, "KarmaBilateral not configured")
    try:
        from karma_sdk import KarmaBilateral
    except ImportError:
        raise HTTPException(503, "karma-sdk not installed")

    return KarmaBilateral(
        rpc_url=config.testnet_rpc_url,
        private_key=config.testnet_private_key,
        contract_address=config.karma_bilateral_address,
    )


@router.post("/lock", response_model=LockResponse)
async def lock(body: LockRequest, _hmac: Annotated[str | None, Depends(read_hmac_json)] = None):
    """Lock USDC and mint a Bill Token. Same flow as old lockFunds."""
    k = _get_client()
    bill_id = k.lock(body.token, body.amount)
    bill = k.get_bill(bill_id)
    return LockResponse(
        bill_id=bill.bill_id,
        owner=bill.owner,
        token=bill.token,
        amount=bill.amount,
        state=bill.state,
    )


@router.post("/bind", response_model=BindResponse)
async def bind(body: BindRequest, _hmac: Annotated[str | None, Depends(read_hmac_json)] = None):
    """Bilaterally bind buyer + agent Bill Tokens."""
    k = _get_client()
    binding_id = k.bind(body.buyer_bill_id, body.agent_bill_id, body.scope_hash)
    binding = k.get_binding(binding_id)
    return BindResponse(
        binding_id=binding.binding_id,
        buyer_bill_id=binding.buyer_bill_id,
        agent_bill_id=binding.agent_bill_id,
        state=binding.state,
    )


@router.post("/settle", response_model=StatusResponse)
async def settle(body: SettleRequest, _hmac: Annotated[str | None, Depends(read_hmac_json)] = None):
    """Submit settlement proof. Returns updated status."""
    k = _get_client()
    k.settle(body.binding_id, body.proof_hash)
    return _build_status(k, body.binding_id)


@router.get("/status/{binding_id}", response_model=StatusResponse)
async def status(binding_id: int):
    """Query full binding + bill status."""
    k = _get_client()
    return _build_status(k, binding_id)


@router.post("/finalize/{binding_id}", response_model=StatusResponse)
async def finalize(binding_id: int, _hmac: Annotated[str | None, Depends(read_hmac_json)] = None):
    """Finalize settlement after dispute window closes."""
    k = _get_client()
    # Call finalizeSettle directly
    import time
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(config.testnet_rpc_url))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(config.karma_bilateral_address),
        abi=[{"name":"finalizeSettle","type":"function","inputs":[{"name":"bindingId","type":"uint256"}],"outputs":[]}]
    )
    account = w3.eth.account.from_key(config.testnet_private_key)
    tx = contract.functions.finalizeSettle(binding_id).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 500000,
    })
    signed = account.sign_transaction(tx)
    w3.eth.send_raw_transaction(signed.raw_transaction)
    return _build_status(k, binding_id)


def _build_status(k, binding_id: int) -> StatusResponse:
    b = k.get_binding(binding_id)
    bb = k.get_bill(b.buyer_bill_id)
    ab = k.get_bill(b.agent_bill_id)
    invariant = k.check_invariant(bb.token)

    bill_states = [
        {"bill_id": bb.bill_id, "owner": bb.owner, "amount": bb.amount, "state": bb.state},
        {"bill_id": ab.bill_id, "owner": ab.owner, "amount": ab.amount, "state": ab.state},
    ]

    return StatusResponse(
        binding_id=b.binding_id,
        state=b.state,
        bill_states=bill_states,
        can_settle=(b.state == "ACTIVE" and b.settle_after <= 0),
        can_dispute=(b.state == "FINALIZING"),
        can_finalize=(b.state == "FINALIZING"),
        usdc_locked=bb.amount + ab.amount,
        settle_after=b.settle_after if b.state == "ACTIVE" else None,
    )
