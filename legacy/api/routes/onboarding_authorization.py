"""Interactive onboarding authorization — step-by-step owner consent driven by an agent.

当主人对 agent 说「接入 Karma」时：
  1. agent 调 POST /v1/onboarding-authorization/start 开一个流程；
  2. 每一步返回一个可渲染 prompt（title_zh/body_zh/control/actions/payload）；
  3. 交互页面按 prompt_type 渲染控件，主人操作后回传；
  4. agent 调 POST .../respond 推进，直到 status=complete。

安全边界：本路由只收集「逐步同意 + 交接」，不重做 SIWE / 铸钥匙 / 配对
的密码学校验；那些仍在 auth / runtime_gateway / agent_pairing 里各自校验。
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import get_current_agent_id
from services.onboarding_authorization import (
    abort_onboarding,
    current_prompt,
    get_onboarding_flow,
    respond_onboarding,
    start_onboarding,
)

router = APIRouter()


class StartRequest(BaseModel):
    identity_id: str = Field(min_length=1, max_length=128)
    profile_id: Literal["user", "merchant", "enterprise"]


class RespondRequest(BaseModel):
    action: Literal["sign", "confirm", "reject", "cancel", "continue"]
    value: dict[str, Any] = Field(default_factory=dict)


def _owned_flow(flow_id: str, actor: str):
    flow = get_onboarding_flow(flow_id)
    if not flow:
        raise HTTPException(404, f"unknown onboarding flow: {flow_id}")
    if flow.started_by and flow.started_by != actor:
        raise HTTPException(403, "flow belongs to another agent")
    return flow


@router.post("/start")
async def start(body: StartRequest, actor: str = Depends(get_current_agent_id)) -> dict[str, Any]:
    """Agent opens an onboarding authorization flow for an owner identity."""
    try:
        return start_onboarding(
            identity_id=body.identity_id, profile_id=body.profile_id, started_by=actor
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{flow_id}")
async def get(flow_id: str, actor: str = Depends(get_current_agent_id)) -> dict[str, Any]:
    """Renderable current step for the given flow."""
    _owned_flow(flow_id, actor)
    try:
        return current_prompt(flow_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{flow_id}/respond")
async def respond(
    flow_id: str,
    body: RespondRequest,
    actor: str = Depends(get_current_agent_id),
) -> dict[str, Any]:
    """Feed the owner's action back into the flow and advance."""
    _owned_flow(flow_id, actor)
    try:
        return respond_onboarding(flow_id=flow_id, action=body.action, value=body.value)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{flow_id}/abort")
async def abort(flow_id: str, actor: str = Depends(get_current_agent_id)) -> dict[str, Any]:
    """Owner declines mid-flow; mark the flow aborted."""
    _owned_flow(flow_id, actor)
    try:
        return abort_onboarding(flow_id=flow_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
