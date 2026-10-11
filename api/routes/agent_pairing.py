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
from services import mailer
from services.identity_actor import resolve_actor_identity_id
from services.runtime_key_service import (
    PublicKeyError,
    activate_key_binding,
    agent_binding_fingerprint,
    load_active_context,
    verify_signed_request,
)
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
    #: agent 用自己私钥签的「我持有这把公钥」证明（Ed25519，base64）。
    #: 交了 public_key 就必须带 —— 公钥是「持有证明」，不再是「申报」。
    signature: str | None = Field(default=None, max_length=256)
    nonce: str | None = Field(default=None, max_length=128)
    #: 规范化前的 ISO-8601 UTC；服务端收敛成 YYYY-MM-DDTHH:MM:SSZ 再验签。
    timestamp: str | None = Field(default=None, max_length=64)
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

    @field_validator(
        "public_key",
        "signature",
        "nonce",
        "timestamp",
        "endpoint_url",
        "self_description",
        "requested_vertical",
        mode="before",
    )
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


class PairResendEmailBody(BaseModel):
    user_code: str = Field(min_length=4, max_length=16)
    #: 重发必须再确认一次收件邮箱 —— 不接受「服务器上次记的那个」这种隐式目标。
    email: str = Field(min_length=3, max_length=254)


class PairHandoffBody(BaseModel):
    user_code: str = Field(min_length=4, max_length=16)


class PairApproveBody(BaseModel):
    #: 主人的确认邮箱：填了就启用「邮箱回执」这第三把锁（agent 聊天窗口显示 match_code，
    #: 主人在邮件里点与它相同的那一个码，凭据才放行）。不填 = 这一版不加这道锁。
    notify_email: str | None = Field(default=None, max_length=254)
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
        signature=body.signature,
        signature_nonce=body.nonce,
        signature_timestamp=body.timestamp,
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

    notify_email = (body.notify_email or "").strip()
    if notify_email:
        # 动 agent 之前先把这道锁的出口验一遍：宁可现在就 503/400，
        # 也不要「批准已生效、锁却没加上」的半截状态。
        if not mailer.configured():
            raise HTTPException(
                503,
                "email confirmation was requested but outbound mail is not configured "
                "(KARMA_MAIL_HOST / KARMA_MAIL_FROM / KARMA_MAIL_RELAY_URL)",
            )
        if "@" not in notify_email or len(notify_email) > 254:
            raise HTTPException(400, "notify_email is not a usable address")

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
    email_confirm: dict[str, Any] = {"required": False, "state": "off"}
    if notify_email:
        issued = pairing.attach_email_confirm(user_code=body.user_code, email=notify_email)
        try:
            delivered = _send_email_confirm_mail(email=notify_email, issued=issued)
        except mailer.MailerUnavailable as exc:
            # attach 已经写盘 → claim 会被邮箱闸门挡住（fail-closed）；如实告诉主人去重发。
            raise HTTPException(
                502,
                "pairing approved, but the confirmation email could not be sent "
                f"({exc}); resend it from the console",
            ) from exc
        email_confirm = {
            "required": True,
            "state": "pending",
            "email_masked": issued.get("email_masked"),
            "expires_at": issued.get("expires_at"),
            "delivered": delivered,
            # 这串要念给 agent（它显示在聊天窗口里）；它单独换不到任何东西。
            "match_code": issued.get("match_code"),
        }
    return {
        "schema_version": "karma-agent-pairing-approve-v1",
        "pairing": record,
        "agent": agent,
        "p1_ready": result.get("p1_ready"),
        "p1_status": result.get("p1_status"),
        "boundary_hash": result.get("boundary_hash"),
        "email_confirm": email_confirm,
        "note_zh": (
            "已批准并交付：agent 身份已建好，API Key 已放进这次配对的交付里，"
            "它下一次轮询就会自己领走（只发一次）。控制台不再显示这串密钥。"
            "你不用再给它任何码；想再加一道手递手的确认，可以额外点「签发交接码」。"
            + (
                " 这次启用了「邮箱回执」：把上面 email_confirm.match_code 报给 agent，"
                "让它在聊天窗口显示出来，然后在你自己的邮箱里点与它相同的那一个码 ——"
                "点对了凭据才会放行。"
                if email_confirm.get("required")
                else ""
            )
        ),
    }


def _send_email_confirm_mail(*, email: str, issued: dict[str, Any]) -> bool:
    """把 3 个候选码发到主人邮箱。发不出去就抛 —— 绝不当成「已确认」。"""
    codes = list(issued.get("codes") or [])
    links = list(issued.get("links") or [])
    ttl_minutes = max(1, int(issued.get("ttl_seconds") or 0) // 60)
    agent_name = "你的 Agent"

    text_lines = [
        "Karma 配对确认",
        "",
        f"有人在 {agent_name} 的聊天窗口里发起接入 Karma，现在需要你确认。",
        "",
        "请核对：下面 3 个码里，只有一个和 agent 在聊天窗口里显示的那串完全相同。",
        "点与它对应的那一行链接即可完成确认（链接只能点对一次，点错会记一次失败）。",
        "",
    ]
    for item, link in zip(codes, links):
        text_lines.append(f"  码 {item}：{link.get('url')}")
    text_lines += [
        "",
        f"有效期 {ttl_minutes} 分钟。过期或想重发，请在操作台重新发一次确认邮件。",
        "如果你没有发起过这次接入，忽略这封邮件即可 —— 没有人能仅凭它取走任何凭据。",
        "",
        "—— Karma",
    ]

    rows = "".join(
        f'<li style="margin:10px 0"><b style="font-size:20px;letter-spacing:3px">{item}</b>'
        f' &nbsp;<a href="{link.get("url")}">点这个码完成确认</a></li>'
        for item, link in zip(codes, links)
    )
    html = (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:560px">'
        "<h2>Karma 配对确认</h2>"
        "<p>有人在 agent 的聊天窗口里发起接入 Karma，现在需要你确认。</p>"
        "<p>下面 3 个码里，只有一个和 agent 在聊天窗口里显示的那串完全相同。"
        "点与它对应的那一行链接即可。</p>"
        f'<ul style="list-style:none;padding:0">{rows}</ul>'
        f"<p>有效期约 {ttl_minutes} 分钟。过期请在操作台重发。</p>"
        "<p>如果你没有发起过这次接入，忽略这封邮件即可。</p>"
        "</div>"
    )
    mailer.send_mail(
        to=email,
        subject="Karma 配对确认 —— 请在下面点与 agent 显示相同的那一个码",
        text="\n".join(text_lines),
        html=html,
    )
    return True


@public_router.get("/email-confirm")
async def confirm_pairing_email(
    user_code: str,
    token: str,
    _rl: None = Depends(agent_pairing_rate_limit),
):
    """邮件里那 3 条链接打到的就是这个口。token 只在邮件里 —— 邮箱才是那把钥匙。

    返回一页纯 HTML：不反射任何输入、不出现任何码、不带任何外链。
    """
    verdict = pairing.verify_email_confirm(user_code=user_code, token=token)
    page = {
        "confirmed": (
            "确认成功",
            "配对已确认。回到与 agent 的对话，让它继续领取凭据。",
        ),
        "wrong": (
            "这个码不对",
            "请回到邮件，点与 agent 聊天窗口里显示的那个码相同的那一行。",
        ),
        "expired": (
            "确认已过期",
            "请在操作台重新发一次确认邮件，然后点新邮件里的码。",
        ),
        "too_many": (
            "尝试次数用尽",
            "这次配对已就地作废。请让 agent 重新发起接入，再从零走一遍。",
        ),
        "unknown": (
            "链接无效",
            "这封邮件的链接已经不存在了。请在操作台重新发一次确认邮件。",
        ),
    }
    title, body = page.get(verdict, page["unknown"])
    from fastapi.responses import HTMLResponse

    html = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Karma {title}</title></head>"
        '<body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
        'max-width:520px;margin:12vh auto;padding:0 20px;line-height:1.6">'
        f"<h2>{title}</h2><p>{body}</p></body></html>"
    )
    return HTMLResponse(html, status_code=200 if verdict == "confirmed" else 409)


@owner_router.post("/email-confirm/resend")
async def resend_pairing_email(
    body: PairResendEmailBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """重发确认邮件：重出 3 个码、旧码当场作废，并把新的 match_code 交给主人。"""
    owner = await _require_owner(db, request)
    view = pairing.lookup_by_user_code(body.user_code)
    if (view.get("owner_identity_id") or "") != owner:
        raise HTTPException(403, "this pairing belongs to another identity")
    if view.get("status") != "approved":
        raise HTTPException(409, f"pairing is already {view.get('status')}")
    if not mailer.configured():
        raise HTTPException(503, "outbound mail is not configured")
    issued = pairing.attach_email_confirm(user_code=body.user_code, email=body.email)
    _send_email_confirm_mail(email=body.email, issued=issued)
    return {
        "schema_version": "karma-agent-pairing-email-confirm-v1",
        "user_code": issued.get("user_code"),
        "email_masked": issued.get("email_masked"),
        "expires_at": issued.get("expires_at"),
        "match_code": issued.get("match_code"),
        "note_zh": "新邮件已发出，旧邮件里的码即刻作废。把 match_code 交给 agent 显示。",
    }


@owner_router.post("/handoff")
async def issue_pairing_handoff(
    body: PairHandoffBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """签发交接码 —— 可选加固，不是必经步骤。

    默认批准即交付：agent 用 pairing_code 直接就能领。只有主人想再加一道手递手的
    确认时才签发 —— 3 分钟有效、只在这条响应里出现一次（服务端只留 SHA-256），
    重签会当场作废旧码。一旦签发，agent 领取时就必须带上它。
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

    # 配对即激活：agent 申请接入时就交了自己的公钥，操作台在批准前把这个公钥的
    # 指纹显示给主人核对，所以「批准 + 划额度」本身就是那次确认 —— 不再需要
    # 「agent 申请绑定 → 出 8 位码 → 主人再输一次码」。
    #
    # 绑定之后照旧逐请求验签：钥匙字符串泄漏了也花不出去，签名要 agent 本机的私钥。
    declared_key = pairing.public_key_for_user_code(body.user_code)
    fingerprint = ""
    if declared_key:
        try:
            await activate_key_binding(
                db=db,
                key_id=ctx.key_id,
                agent_id=str(record.get("agent_id") or ""),
                agent_public_key=declared_key,
            )
            fingerprint = agent_binding_fingerprint(declared_key)
        except PublicKeyError:
            # agent 报上来的公钥不成形（不是 32 字节裸公钥）：这次不激活，钥匙照旧
            # 挂进交付，让它走「申请绑定 + 8 位匹配码」那条老路。主人这一下批准不该
            # 被一串脏数据打断，agent 也会从 claim 的回执里看到 activated=false。
            fingerprint = ""
    result = pairing.attach_runtime_key(
        user_code=body.user_code,
        owner_identity_id=owner,
        runtime_key=body.runtime_key,
        runtime_key_id=ctx.key_id,
        activated_fingerprint=fingerprint,
    )
    await db.commit()
    return result
