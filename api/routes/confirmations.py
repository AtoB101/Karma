"""Owner confirmation sessions — only ask humans where reality requires it."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    """Create a Yes/No prompt for the owner; AUTO steps return skipped."""
    try:
        return create_confirmation_session(
            scene_id=body.scene_id,
            role=body.role,
            step=body.step,
            owner_agent_id=body.owner_agent_id,
            context=body.context,
            interaction_ref=body.interaction_ref,
            policy_auto_allowed=body.policy_auto_allowed,
        )
    except ConfirmationPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/sessions/{session_id}")
async def get_owner_confirmation_session(session_id: str) -> dict[str, Any]:
    try:
        return get_confirmation_session(session_id)
    except ConfirmationPolicyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/sessions/{session_id}/decide")
async def decide_owner_confirmation_session(session_id: str, body: DecideRequest) -> dict[str, Any]:
    """Owner answers: confirm=true → agent may proceed; false → stop."""
    try:
        return decide_confirmation_session(
            session_id,
            confirm=body.confirm,
            note=body.note,
            actor_agent_id=body.actor_agent_id,
        )
    except ConfirmationPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc


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
        )
    except ConfirmationPolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
