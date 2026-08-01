"""Owner confirmation sessions — only ask humans where reality requires it."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services.accept_fulfillment import (
    expire_pending_seller_accepts,
    process_expired_seller_session,
    record_seller_non_confirm,
)
from services.agent_trust import record_seller_non_confirm_reputation
from services.human_confirmation_policy import (
    ConfirmationPolicyError,
    assert_step_allowed,
    create_confirmation_session,
    decide_confirmation_session,
    get_confirmation_session,
    plan_confirmations,
)

router = APIRouter()


class PlanRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=128)
    role: Literal["buyer", "seller"]
    steps: list[str] | None = None
    policy_auto_allowed: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class CreateSessionRequest(BaseModel):
    scene_id: str = Field(min_length=1, max_length=128)
    role: Literal["buyer", "seller"]
    step: str = Field(min_length=1, max_length=64)
    owner_agent_id: str = Field(min_length=1, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)
    interaction_ref: str | None = Field(default=None, max_length=256)
    policy_auto_allowed: bool = False


class DecideRequest(BaseModel):
    confirm: bool
    actor_agent_id: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=1000)


class AssertRequest(BaseModel):
    scene_id: str
    role: Literal["buyer", "seller"]
    step: str
    confirmation_session_id: str | None = None
    policy_auto_allowed: bool = False
    expected_owner_agent_id: str | None = Field(default=None, max_length=128)
    amount: float | None = Field(default=None, gt=0)
    consume: bool = True
    expected_interaction_ref: str | None = Field(default=None, max_length=256)


@router.post("/plan")
async def plan_owner_confirmations(body: PlanRequest) -> dict[str, Any]:
    """Split must-confirm vs auto-ok steps for a scene/role."""
    try:
        return plan_confirmations(
            scene_id=body.scene_id,
            role=body.role,
            steps=body.steps,
            policy_auto_allowed=body.policy_auto_allowed,
            context=body.context,
        )
    except ConfirmationPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/sessions")
async def create_owner_confirmation_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create a Yes/No prompt for the owner; AUTO steps return skipped.

    Client ``policy_auto_allowed`` is ignored — only Core/fulfill may enable
    POLICY_AUTO after verifying a saved automation-policy (anti-bypass).
    """
    try:
        _ = body.policy_auto_allowed  # intentionally ignored
        return create_confirmation_session(
            scene_id=body.scene_id,
            role=body.role,
            step=body.step,
            owner_agent_id=body.owner_agent_id,
            context=body.context,
            interaction_ref=body.interaction_ref,
            policy_auto_allowed=False,
        )
    except ConfirmationPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/sessions/{session_id}")
async def get_owner_confirmation_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        pub = get_confirmation_session(session_id)
    except ConfirmationPolicyError as exc:
        raise HTTPException(404, str(exc)) from exc
    # P6: lazy timeout → cancel + non-confirm ledger
    if (
        pub.get("role") == "seller"
        and pub.get("step") == "accept_order"
        and pub.get("status") == "EXPIRED"
    ):
        cancelled = process_expired_seller_session(session_id)
        if cancelled:
            delta = float(
                ((cancelled.get("recorded") or {}).get("reputation_delta")) or -2.0
            )
            try:
                await record_seller_non_confirm_reputation(
                    db,
                    seller_agent_id=str(pub.get("owner_agent_id") or ""),
                    delta=delta,
                )
            except Exception:  # noqa: BLE001
                pass
            return {**pub, **cancelled, "status": "CANCELLED"}
    return pub


@router.post("/sessions/{session_id}/decide")
async def decide_owner_confirmation_session(
    session_id: str,
    body: DecideRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Owner answers: confirm=true → agent may proceed; false → stop."""
    try:
        # If already past TTL, convert to P6 timeout cancel instead of bare error
        try:
            pub = get_confirmation_session(session_id)
            if (
                pub.get("role") == "seller"
                and pub.get("step") == "accept_order"
                and pub.get("status") == "EXPIRED"
            ):
                cancelled = process_expired_seller_session(session_id)
                if cancelled:
                    delta = float(
                        ((cancelled.get("recorded") or {}).get("reputation_delta")) or -2.0
                    )
                    try:
                        await record_seller_non_confirm_reputation(
                            db,
                            seller_agent_id=str(pub.get("owner_agent_id") or ""),
                            delta=delta,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    return cancelled
        except ConfirmationPolicyError:
            pass

        out = decide_confirmation_session(
            session_id,
            confirm=body.confirm,
            note=body.note,
            actor_agent_id=body.actor_agent_id,
        )
    except ConfirmationPolicyError as exc:
        if "EXPIRED" in str(exc):
            cancelled = process_expired_seller_session(session_id)
            if cancelled:
                return cancelled
        raise HTTPException(400, str(exc)) from exc

    # P6: seller reject → non_confirm ledger + slight reputation hit
    if (
        not body.confirm
        and out.get("role") == "seller"
        and out.get("step") == "accept_order"
    ):
        recorded = record_seller_non_confirm(
            seller_id=str(out.get("owner_agent_id") or body.actor_agent_id),
            scene_id=str(out.get("scene_id") or ""),
            interaction_ref=out.get("interaction_ref"),
            reason="reject",
            session_id=session_id,
            amount=out.get("max_amount"),
        )
        try:
            await record_seller_non_confirm_reputation(
                db,
                seller_agent_id=str(out.get("owner_agent_id") or body.actor_agent_id),
                delta=float(recorded.get("reputation_delta") or -3.0),
            )
        except Exception:  # noqa: BLE001
            pass
        out["non_confirm"] = recorded
        out["status_after"] = "cancelled_seller_reject"
    return out


@router.post("/expire-pending-seller-accepts")
async def expire_pending_seller_accepts_route(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """P6 sweep: expire seller accept TTL → cancel intent side-effect + ledger."""
    swept = expire_pending_seller_accepts(limit=200)
    for item in swept.get("cancelled") or []:
        seller = str(item.get("seller_id") or "")
        delta = float(
            ((item.get("recorded") or {}).get("reputation_delta")) or -2.0
        )
        if not seller:
            continue
        try:
            await record_seller_non_confirm_reputation(
                db, seller_agent_id=seller, delta=delta
            )
        except Exception:  # noqa: BLE001
            pass
    return swept


@router.post("/assert")
async def assert_confirmation_gate(body: AssertRequest) -> dict[str, Any]:
    """Orchestration helper: is this step allowed to proceed now?

    Client ``policy_auto_allowed`` is ignored — only Core/fulfill may enable POLICY_AUTO
    after verifying a saved automation-policy.
    """
    try:
        return assert_step_allowed(
            scene_id=body.scene_id,
            role=body.role,
            step=body.step,
            confirmation_session_id=body.confirmation_session_id,
            policy_auto_allowed=False,
            expected_owner_agent_id=body.expected_owner_agent_id,
            amount=body.amount,
            consume=body.consume,
            expected_interaction_ref=body.expected_interaction_ref,
        )
    except ConfirmationPolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
