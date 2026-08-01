"""Assistant orchestration — intent to delivery in one call."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services.intent_fulfillment import fulfill_intent
from services.ledger_party_access import require_ledger_identity
from services.path_param_safety import validate_public_url_segment

router = APIRouter()


class FulfillIntentRequest(BaseModel):
    requirement_text: str = Field(min_length=1, max_length=32000)
    buyer_identity_id: str
    amount: float | None = Field(default=None, gt=0)
    seller_identity_id: str | None = None
    auto_fund_capacity: bool = True
    negotiate_a2a: bool = True
    auto_complete: bool = False
    buyer_signature: str = "0xintent_fulfillment"


@router.post("/fulfill-intent")
async def fulfill_intent_route(
    body: FulfillIntentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Full assistant spine:

    discover merchant → A2A negotiate (if endpoint) → real voucher →
    settlement lock/start → optional auto evidence + settle.

    Use ``auto_complete=true`` for demos / trusted automation to finish
    delivery+receipt+buyer-accept in one shot.
    """
    validate_public_url_segment("buyer_identity_id", body.buyer_identity_id)
    if body.seller_identity_id:
        validate_public_url_segment("seller_identity_id", body.seller_identity_id)
    require_ledger_identity(request, body.buyer_identity_id)

    result = await fulfill_intent(
        db,
        requirement_text=body.requirement_text,
        buyer_identity_id=body.buyer_identity_id,
        amount=body.amount,
        seller_identity_id=body.seller_identity_id,
        auto_fund_capacity=body.auto_fund_capacity,
        negotiate_a2a=body.negotiate_a2a,
        auto_complete=body.auto_complete,
        buyer_signature=body.buyer_signature,
    )
    await db.commit()
    return result
