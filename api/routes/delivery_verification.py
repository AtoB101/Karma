"""P7 Delivery verification — triple-party physical POD, ticket stubs, digital light."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.delivery_verification import (
    DeliveryVerificationError,
    apply_silent_buyer_default,
    buyer_confirm,
    create_verification_session,
    expire_silent_buyers,
    get_verification,
    issue_capture_challenge,
    logistics_deliver,
    logistics_intake,
    mark_execution_receipt,
    seller_ship,
    submit_proof,
    try_verify,
)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    scene_id: str = Field(min_length=1, max_length=128)
    seller_agent_id: str = Field(min_length=1, max_length=128)
    buyer_agent_id: str = Field(min_length=1, max_length=128)
    logistics_agent_id: str | None = Field(default=None, max_length=128)
    capture_id: str | None = Field(default=None, max_length=128)
    amount: float | None = Field(default=None, ge=0)


class SellerShipRequest(BaseModel):
    actor_agent_id: str = Field(min_length=1, max_length=128)
    ship_proof_hash: str | None = Field(default=None, max_length=128)
    meta: dict[str, Any] = Field(default_factory=dict)


class LogisticsIntakeRequest(BaseModel):
    actor_agent_id: str = Field(min_length=1, max_length=128)
    item_matches: bool
    note: str | None = Field(default=None, max_length=2000)
    intake_proof_hash: str | None = Field(default=None, max_length=128)


class CaptureChallengeRequest(BaseModel):
    party_role: Literal["seller", "logistics", "buyer"]
    geo_hash: str | None = Field(default=None, max_length=128)


class ProofRequest(BaseModel):
    proof_type: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(min_length=16, max_length=256)
    actor_agent_id: str = Field(min_length=1, max_length=128)
    party_role: Literal["seller", "logistics", "buyer", "protocol"] = "seller"
    media_uri: str | None = Field(default=None, max_length=2000)
    nonce: str | None = None
    captured_at: str | None = None
    geo_hash: str | None = None
    tag_hmac: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class LogisticsDeliverRequest(BaseModel):
    actor_agent_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(min_length=16, max_length=256)
    delivery_proof_type: str = "delivery_photo_tagged"
    nonce: str | None = None
    captured_at: str | None = None
    geo_hash: str | None = None
    tag_hmac: str | None = None
    media_uri: str | None = None


class BuyerConfirmRequest(BaseModel):
    actor_agent_id: str = Field(min_length=1, max_length=128)
    confirm: bool = True
    note: str | None = Field(default=None, max_length=2000)


class ReceiptMarkRequest(BaseModel):
    ok: bool = True


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    try:
        return create_verification_session(
            task_id=body.task_id,
            scene_id=body.scene_id,
            seller_agent_id=body.seller_agent_id,
            buyer_agent_id=body.buyer_agent_id,
            logistics_agent_id=body.logistics_agent_id,
            capture_id=body.capture_id,
            amount=body.amount,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/expire-silent-buyers")
async def post_expire_silent_buyers() -> dict[str, Any]:
    return expire_silent_buyers(limit=200)


@router.get("/{verification_id}")
async def get_session(verification_id: str) -> dict[str, Any]:
    try:
        return get_verification(verification_id)
    except DeliveryVerificationError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{verification_id}/seller-ship")
async def post_seller_ship(verification_id: str, body: SellerShipRequest) -> dict[str, Any]:
    try:
        return seller_ship(
            verification_id,
            actor_agent_id=body.actor_agent_id,
            ship_proof_hash=body.ship_proof_hash,
            meta=body.meta,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/logistics-intake")
async def post_logistics_intake(
    verification_id: str, body: LogisticsIntakeRequest
) -> dict[str, Any]:
    try:
        return logistics_intake(
            verification_id,
            actor_agent_id=body.actor_agent_id,
            item_matches=body.item_matches,
            note=body.note,
            intake_proof_hash=body.intake_proof_hash,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/capture-challenge")
async def post_capture_challenge(
    verification_id: str, body: CaptureChallengeRequest
) -> dict[str, Any]:
    try:
        return issue_capture_challenge(
            verification_id,
            party_role=body.party_role,
            geo_hash=body.geo_hash,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/proofs")
async def post_proof(verification_id: str, body: ProofRequest) -> dict[str, Any]:
    try:
        return submit_proof(
            verification_id,
            proof_type=body.proof_type,
            content_hash=body.content_hash,
            actor_agent_id=body.actor_agent_id,
            party_role=body.party_role,
            media_uri=body.media_uri,
            nonce=body.nonce,
            captured_at=body.captured_at,
            geo_hash=body.geo_hash,
            tag_hmac=body.tag_hmac,
            meta=body.meta,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/logistics-deliver")
async def post_logistics_deliver(
    verification_id: str, body: LogisticsDeliverRequest
) -> dict[str, Any]:
    try:
        return logistics_deliver(
            verification_id,
            actor_agent_id=body.actor_agent_id,
            delivery_proof_type=body.delivery_proof_type,
            content_hash=body.content_hash,
            nonce=body.nonce,
            captured_at=body.captured_at,
            geo_hash=body.geo_hash,
            tag_hmac=body.tag_hmac,
            media_uri=body.media_uri,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/buyer-confirm")
async def post_buyer_confirm(
    verification_id: str, body: BuyerConfirmRequest
) -> dict[str, Any]:
    try:
        return buyer_confirm(
            verification_id,
            actor_agent_id=body.actor_agent_id,
            confirm=body.confirm,
            note=body.note,
        )
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/mark-receipt")
async def post_mark_receipt(
    verification_id: str, body: ReceiptMarkRequest
) -> dict[str, Any]:
    try:
        mark_execution_receipt(verification_id, ok=body.ok)
        return try_verify(verification_id)
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/verify")
async def post_verify(verification_id: str) -> dict[str, Any]:
    try:
        return try_verify(verification_id)
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{verification_id}/apply-silent-default")
async def post_apply_silent(verification_id: str) -> dict[str, Any]:
    try:
        out = apply_silent_buyer_default(verification_id)
        if out is None:
            return get_verification(verification_id)
        return out
    except DeliveryVerificationError as exc:
        raise HTTPException(400, str(exc)) from exc
