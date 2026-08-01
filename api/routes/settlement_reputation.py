"""P8 Settlement reputation — encrypted public attestations + agent auto-verify."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import get_current_agent_id
from db.session import get_db
from services.settlement_reputation import (
    SettlementReputationError,
    agent_auto_verify_decision,
    assert_settle_gates,
    decrypt_attestation,
    get_attestation_for_task,
    public_agent_reputation,
    public_attestation_view,
    seal_settlement_attestation,
    verify_outcome_commitment,
)

router = APIRouter()


class SealRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    buyer_agent_id: str = Field(min_length=1, max_length=128)
    seller_agent_id: str = Field(min_length=1, max_length=128)
    amount: float = Field(ge=0)
    currency: str = Field(default="USDC", max_length=16)
    outcome: str = Field(default="SETTLED", max_length=32)
    scope_hash: str | None = None
    proof_hash: str | None = None
    capture_id: str | None = None
    delivery_verification_id: str | None = None
    agent_auto_verified: bool = False


class VerifyCommitmentRequest(BaseModel):
    attestation_id: str = Field(min_length=1, max_length=128)
    expected_commitment: str | None = None
    outcome_body: dict[str, Any] | None = None


class DecryptRequest(BaseModel):
    role: Literal["parties", "regulator", "protocol"] = "parties"


class AutoVerifyRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    delivery_verified: bool = False


class GateCheckRequest(BaseModel):
    task_id: str
    scene_id: str
    delivery_verified: bool | None = None
    confirmation_satisfied: bool = True
    success_receipt: bool = True
    agent_auto: bool = False


@router.post("/attestations/seal")
async def seal_attestation(
    body: SealRequest,
    _actor: str = Depends(get_current_agent_id),
) -> dict[str, Any]:
    try:
        return seal_settlement_attestation(
            task_id=body.task_id,
            scene_id=body.scene_id,
            buyer_agent_id=body.buyer_agent_id,
            seller_agent_id=body.seller_agent_id,
            amount=body.amount,
            currency=body.currency,
            outcome=body.outcome,
            scope_hash=body.scope_hash,
            proof_hash=body.proof_hash,
            capture_id=body.capture_id,
            delivery_verification_id=body.delivery_verification_id,
            agent_auto_verified=body.agent_auto_verified,
        )
    except SettlementReputationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/attestations/{attestation_id}/public")
async def get_public_attestation(attestation_id: str) -> dict[str, Any]:
    try:
        return public_attestation_view(attestation_id)
    except SettlementReputationError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/tasks/{task_id}/attestation")
async def get_task_attestation(task_id: str) -> dict[str, Any]:
    out = get_attestation_for_task(task_id)
    if not out:
        raise HTTPException(404, "no attestation for task")
    return out


@router.post("/attestations/verify-commitment")
async def verify_commitment(body: VerifyCommitmentRequest) -> dict[str, Any]:
    try:
        return verify_outcome_commitment(
            attestation_id=body.attestation_id,
            expected_commitment=body.expected_commitment,
            outcome_body=body.outcome_body,
        )
    except SettlementReputationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/attestations/{attestation_id}/decrypt")
async def decrypt_attestation_route(
    attestation_id: str,
    body: DecryptRequest,
    _actor: str = Depends(get_current_agent_id),
) -> dict[str, Any]:
    """Decrypt audit pack — always requires authenticated actor (parties/regulator)."""
    try:
        return decrypt_attestation(attestation_id, role=body.role)
    except SettlementReputationError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/agent-auto-verify")
async def agent_auto_verify(body: AutoVerifyRequest) -> dict[str, Any]:
    return agent_auto_verify_decision(
        scene_id=body.scene_id,
        task_id=body.task_id,
        delivery_verified=body.delivery_verified,
    )


@router.post("/gates/check")
async def check_settle_gates(body: GateCheckRequest) -> dict[str, Any]:
    return assert_settle_gates(
        task_id=body.task_id,
        scene_id=body.scene_id,
        delivery_verified=body.delivery_verified,
        confirmation_satisfied=body.confirmation_satisfied,
        success_receipt=body.success_receipt,
        agent_auto=body.agent_auto,
    )


@router.get("/agents/{agent_id}/public-reputation")
async def get_public_reputation(
    agent_id: str, include_agent_id: bool = False
) -> dict[str, Any]:
    return public_agent_reputation(agent_id, include_agent_id=include_agent_id)
