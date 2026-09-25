"""Agent self-service pairing — request, approve, claim.

The agent opens a pairing request and shows its owner a short ``user_code``; the
owner approves it in the console against their authenticated identity; the agent
picks the minted credentials up by polling with its ``pairing_code``.

Two properties matter and are easy to lose in a refactor:

1. The direction is **owner approves agent**, never *agent asks the owner for a
   key*. A "paste your key here" flow is a phishing template with our name on
   it, so the console is the only place a credential is ever minted.
2. ``/request`` and ``/claim`` are unauthenticated by design (the agent has no
   credential yet — that is the problem being solved), so they are the only
   routes here without an owner session. Everything that decides anything is
   owner-authenticated, and the pair is mounted separately in ``api/app.py``
   rather than inheriting the protected router's auth dependency.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import agent_pairing_rate_limit, real_client_ip
from api.routes.agents import connect_owner_agent
from db.session import get_db
from services import agent_pairing as pairing
from services.identity_actor import resolve_actor_identity_id
from services.runtime_key_service import load_active_context, verify_signed_request
from services.text_safety import (
    validate_json_strings_safe,
    validate_safe_storage_text,
    validate_safe_storage_text_optional,
)

#: Agent-facing: no session exists yet, this is how one gets requested.
public_router = APIRouter()
#: Owner-facing: same identity resolution the rest of the console uses.
owner_router = APIRouter()


class PairRequestBody(BaseModel):
    """What the agent knows about itself at the moment it asks to connect."""

    agent_name: str = Field(min_length=1, max_length=256)
    platform: str = Field(default="custom", max_length=64)
    public_key: str | None = Field(default=None, max_length=512)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    self_description: str | None = Field(default=None, max_length=2000)
    requested_side: Literal["buyer", "seller"] | None = None
    requested_vertical: str | None = Field(default=None, max_length=64)
    #: Industry hard metrics the agent declares about its own business. The P1
    #: gate still validates them against the industry contract, so this is a
    #: convenience for the owner, not a trust decision made on the agent's word.
    answers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="agent_name")

    @field_validator("platform")
    @classmethod
    def _safe_platform(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="platform")

    @field_validator("public_key", "endpoint_url", "self_description", "requested_vertical", mode="before")
    @classmethod
    def _safe_optional(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="pair_request")

    @field_validator("answers")
    @classmethod
    def _bound_answers(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, ensure_ascii=False)) > 4000:
            raise ValueError("answers is too large")
        validate_json_strings_safe(v, field="answers")
        return v


class PairClaimBody(BaseModel):
    pairing_code: str = Field(min_length=8, max_length=256)
    #: 主人在操作台看到、亲手交给 agent 的那串码 —— 第二把锁（3 分钟）。
    handoff_code: str | None = Field(default=None, max_length=32)


class PairHandoffBody(BaseModel):
    user_code: str = Field(min_length=4, max_length=16)


class PairApproveBody(BaseModel):
    user_code: str = Field(min_length=4, max_length=16)
    side: Literal["buyer", "seller"]
    vertical: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=256)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    scope_profile_id: str | None = Field(default=None, max_length=128)
    answers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display_name", "endpoint_url", "vertical", "scope_profile_id", mode="before")
    @classmethod
    def _safe_optional(cls, v: object) -> str | None:
        return validate_safe_storage_text_optional(None if v is None else str(v), field="pair_approve")


class PairDenyBody(BaseModel):
    user_code: str = Field(min_length=4, max_length=16)
    reason: str = Field(default="", max_length=200)


class PairAttachRuntimeKeyBody(BaseModel):
    user_code: str = Field(min_length=4, max_length=16)
    runtime_key: str = Field(min_length=8, max_length=256)


async def _require_owner(db: AsyncSession, request: Request) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required: connect a wallet first")
    return actor


@public_router.post("/request", status_code=201)
async def create_pairing_request(
    body: PairRequestBody,
    request: Request,
    _rl: None = Depends(agent_pairing_rate_limit),
):
    """Open a pairing request. ``pairing_code`` is returned exactly once."""
    # ``request.client.host`` is our own nginx behind the proxy, which would turn
    # the per-address cap into a global one; ``real_client_ip`` is the same
    # trusted-proxy-aware address the limiter uses.
    client_bucket = pairing.client_bucket(real_client_ip(request))
    return pairing.create_request(
        agent_name=body.agent_name,
        platform=body.platform,
        public_key=body.public_key,
        endpoint_url=body.endpoint_url,
        self_description=body.self_description,
        requested_side=body.requested_side,
        requested_vertical=body.requested_vertical,
        requested_answers=body.answers,
        request_ip=client_bucket,
    )


@public_router.post("/claim")
async def claim_pairing(
    body: PairClaimBody,
    _rl: None = Depends(agent_pairing_rate_limit),
):
    """Poll for approval. Credentials are delivered once, then never again."""
    return pairing.claim(pairing_code=body.pairing_code, handoff_code=body.handoff_code)


@owner_router.get("/lookup")
async def lookup_pairing(
    user_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """What the approval screen shows: who is asking, and for what."""
    await _require_owner(db, request)
    return pairing.lookup_by_user_code(user_code)


@owner_router.get("/mine")
async def my_pairings(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    owner = await _require_owner(db, request)
    rows = pairing.list_for_owner(owner)
    return {"owner_identity_id": owner, "pairings": rows, "total": len(rows)}


@owner_router.post("/approve")
async def approve_pairing(
    body: PairApproveBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create the agent for an approved request and park its key for pickup.

    The bootstrap API key is minted here and goes **into the pairing delivery**,
    never into this response — the console approves the request, the agent
    collects the secret. The owner's consent is the authenticated session, the
    same bar ``/v1/agents/owner-connect`` uses.
    """
    owner = await _require_owner(db, request)
    view = pairing.lookup_by_user_code(body.user_code)
    if view.get("status") != "pending":
        raise HTTPException(409, f"pairing is already {view.get('status')}")

    result = await connect_owner_agent(
        db,
        owner_identity_id=owner,
        side=body.side,
        vertical=body.vertical or view.get("requested_vertical"),
        display_name=body.display_name or view.get("agent_name"),
        self_description=view.get("self_description"),
        endpoint_url=body.endpoint_url or view.get("endpoint_url"),
        scope_profile_id=body.scope_profile_id,
        # The owner's choices win; the agent's self-declared metrics fill the rest.
        answers={**dict(view.get("requested_answers") or {}), **dict(body.answers or {})},
    )
    agent = result["agent"]
    agent_id = getattr(agent, "agent_id", None) or (agent or {}).get("agent_id")
    credentials = dict(result.get("credentials") or {})

    record = pairing.approve(
        user_code=body.user_code,
        owner_identity_id=owner,
        agent_id=str(agent_id),
        api_key=credentials.get("api_key"),
        agent_public_key=credentials.get("agent_public_key"),
    )
    return {
        "schema_version": "karma-agent-pairing-approve-v1",
        "pairing": record,
        "agent": agent,
        "p1_ready": result.get("p1_ready"),
        "p1_status": result.get("p1_status"),
        "boundary_hash": result.get("boundary_hash"),
        "note_zh": (
            "已批准：agent 身份已建好，API Key 已放进这次配对的交付里，"
            "等它自己来领取（只发一次）。控制台不再显示这串密钥。"
            "接下来点「签发交接码」，把那串码交给你的 agent —— 它自己的 pairing_code "
            "加上这串码，两个都对，凭据才会发出去。"
        ),
    }


@owner_router.post("/handoff")
async def issue_pairing_handoff(
    body: PairHandoffBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """签发交接码（主人 -> agent 方向的第二把锁）。

    批准之后才能签发；3 分钟有效、只在这条响应里出现一次（服务端只留 SHA-256），
    重签会当场作废旧码。agent 光有 pairing_code 领不走凭据，必须有它。
    """
    owner = await _require_owner(db, request)
    return pairing.issue_handoff(user_code=body.user_code, owner_identity_id=owner)


@owner_router.post("/deny")
async def deny_pairing(
    body: PairDenyBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    owner = await _require_owner(db, request)
    return pairing.deny(user_code=body.user_code, owner_identity_id=owner, reason=body.reason)


@owner_router.post("/attach-runtime-key")
async def attach_runtime_key(
    body: PairAttachRuntimeKeyBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Add an already-minted runtime key to a pairing that has not been claimed.

    The console mints the runtime key the normal way (wallet signature over
    ``/runtime/create-key``) and hands it here, so the agent can collect identity
    and spending authority in one poll. The key is checked against the same
    identity that owns the pairing before it is parked.
    """
    owner = await _require_owner(db, request)
    ctx = await load_active_context(db=db, token=body.runtime_key)
    if ctx.agent_public_key:
        # 已绑定 agent 公钥的 key 也得逐请求验签：这条附加通道不能变成绕过签名的后门。
        verify_signed_request(
            ctx=ctx,
            method=request.method,
            path=request.url.path,
            body=await request.body(),
            signature_b64=request.headers.get("X-Karma-Agent-Signature"),
            timestamp_header=request.headers.get("X-Karma-Runtime-Timestamp"),
            nonce_header=request.headers.get("X-Karma-Runtime-Nonce"),
        )
    if ctx.karma_identity_id != owner:
        raise HTTPException(403, "runtime key belongs to another identity")

    record = pairing.lookup_by_user_code(body.user_code)
    if (record.get("owner_identity_id") or "") != owner:
        raise HTTPException(403, "this pairing belongs to another identity")
    bound = (ctx.agent_binding or "").strip()
    if record.get("agent_id") and bound and bound != str(record["agent_id"]):
        # A key minted for another agent is almost always a mix-up between two
        # pending pairings, so make the owner redo it instead of shipping it.
        raise HTTPException(
            409,
            "runtime key was minted for a different agent than this pairing",
        )

    return pairing.attach_runtime_key(
        user_code=body.user_code,
        owner_identity_id=owner,
        runtime_key=body.runtime_key,
        runtime_key_id=ctx.key_id,
    )
