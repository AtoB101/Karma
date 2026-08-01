"""Assistant orchestration — intent to delivery in one call."""
from __future__ import annotations

from typing import Any

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
    # Real-world: pause until owner Yes on required buyer/seller steps
    require_owner_confirmation: bool = True
    confirmation_session_id: str | None = Field(default=None, max_length=128)
    seller_confirmation_session_id: str | None = Field(default=None, max_length=128)
    # Deprecated client hint — server ignores; POLICY_AUTO comes from saved automation-policy
    policy_auto_allowed: bool = False
    # Optional; must match intent-inferred scene or request is rejected
    scene_id: str | None = Field(default=None, max_length=128)
    confirmation_context: dict[str, Any] = Field(default_factory=dict)
    # Important Fields: default required for commerce/B2B scenes
    require_important_fields_match: bool | None = None
    important_fields_capture_id: str | None = Field(default=None, max_length=128)
    important_fields: dict[str, Any] = Field(default_factory=dict)
    # Demo/dev only: protocol auto capture+dual-submit+MATCH (blocked outside demo envs)
    auto_lock_important_fields: bool = False


@router.post("/fulfill-intent")
async def fulfill_intent_route(
    body: FulfillIntentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Full assistant spine:

    discover → owner Yes/No (when required) → A2A negotiate → voucher →
    settlement lock/start → optional auto evidence + settle.

    Without a CONFIRMED confirmation session, returns
    ``status=awaiting_owner_confirmation`` or ``awaiting_seller_confirmation``
    with ``owner_prompt_zh``. Use ``require_owner_confirmation=false`` only for demos
    (forbidden for high-risk scenes).
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
        require_owner_confirmation=body.require_owner_confirmation,
        confirmation_session_id=body.confirmation_session_id,
        seller_confirmation_session_id=body.seller_confirmation_session_id,
        policy_auto_allowed=body.policy_auto_allowed,
        scene_id=body.scene_id,
        confirmation_context=body.confirmation_context,
        require_important_fields_match=body.require_important_fields_match,
        important_fields_capture_id=body.important_fields_capture_id,
        important_fields=body.important_fields or None,
        auto_lock_important_fields=body.auto_lock_important_fields,
    )
    await db.commit()
    return result
