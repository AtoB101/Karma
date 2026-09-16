"""
Karma — Master identity verification routes (证件 + 扫脸 → 身份卡).

- ``GET  /v1/identity/{identity_id}/verification``         本人看完整状态，他人只看状态位
- ``POST /v1/identity/{identity_id}/verification/submit``  本人提交「密文包 + 摘要 + 脱敏字段」
- ``POST /v1/identity/{identity_id}/verification/verify``  verifier 类档案核验

第三方实名 / 活体服务（可选，IDENTITY_PROVIDER 配置切换，见 services/identity_provider）：

- ``GET  /v1/identity/{identity_id}/verification/provider``            接了没有 / 这次核验到哪一步
- ``POST /v1/identity/{identity_id}/verification/provider/session``    开一次核验，拿到浏览器要打开的入口
- ``POST /v1/identity/{identity_id}/verification/provider/sync``       主动回查一次结论
- ``POST /v1/identity/{identity_id}/verification/provider/mock-push``  仅本地（mock 服务商）自测用
- ``POST /v1/identity/{identity_id}/verification/provider-callback``   **服务商服务器**回调，公开路由，只认签名

服务端只存密文与摘要：明文字段在服务层就被拒（见 services/identity_verification）。
回调报文同样只做白名单提取（结论 / 原因码 / 会话号），原文只留 SHA-256 指纹。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models.orm import IdentityRoleProfile, IdentityVerificationModel
from db.session import get_db
from services.identity_actor import resolve_actor_identity_id
from services.identity_provider import (
    ProviderError,
    provider_status,
    resolve_provider,
)
from services.identity_provider.registry import configured_name
from services.identity_provider.service import (
    apply_callback,
    build_mock_push,
    provider_view,
    start_session,
    sync_active_session,
)
from services.identity_activation import activation_of
from services.identity_verification import (
    IdentityVerificationError,
    assert_can_decide,
    assert_can_submit,
    build_submission,
    empty_view,
    mark_verified,
    owner_view,
    public_view,
)
from services.path_param_safety import validate_public_url_segment

router = APIRouter()


class SubmitVerificationBody(BaseModel):
    # 故意允许未知字段：任何夹带的明文 / 原图字段都要在服务层被指名拒掉，
    # 而不是被 pydantic 静默丢掉（丢掉会让"我传了明文"变成看不见的事实）。
    model_config = {"extra": "allow"}

    level: str | None = Field(default=None, max_length=16)
    # 摘要 / 密文的具体形状由服务层校验，错误信息才说得清楚（400 而不是 422）。
    doc_digest: str = Field(min_length=1, max_length=128)
    face_digest: str = Field(min_length=1, max_length=128)
    package_digest: str = Field(min_length=1, max_length=128)
    package_cipher: str = Field(min_length=1, max_length=8_000_000)
    encryption: dict[str, Any] = Field(default_factory=dict)
    extracted: dict[str, Any] = Field(default_factory=dict)


class ProviderSessionBody(BaseModel):
    """开一次服务商核验。return_url 只允许回我们自己认可的站点（挡住开放重定向）。"""

    return_url: str | None = Field(default=None, max_length=500)


class MockPushBody(BaseModel):
    """本地模拟服务商用：把一条**真签名**的回调推给自己（走完全相同的验签路径）。"""

    outcome: str = Field(..., pattern="^(verified|rejected|pending)$")
    reason_code: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=128)


class VerifyDecisionBody(BaseModel):
    decision: str = Field(..., pattern="^(verified|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)


def _translate(exc: IdentityVerificationError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _require_owner(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to manage identity verification")
    if actor != identity_id:
        raise HTTPException(403, "only the identity owner can manage its verification")
    return actor


async def _require_verifier(db: AsyncSession, request: Request, identity_id: str) -> str:
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to verify identity")
    if actor == identity_id:
        raise HTTPException(403, "an identity cannot verify itself")
    row = (
        await db.execute(
            select(IdentityRoleProfile).where(
                IdentityRoleProfile.owner_identity_id == actor,
                IdentityRoleProfile.class_ == "verifier",
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(403, "only a verifier-class profile can verify identity")
    return actor


@router.get("/{identity_id}/verification")
async def get_identity_verification(
    identity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    row = await db.get(IdentityVerificationModel, identity_id)
    actor = await resolve_actor_identity_id(db, request)
    if row is None:
        if actor == identity_id:
            return empty_view(identity_id)
        return {"identity_id": identity_id, "status": "none", "level": "basic", "verified_at": None}
    if actor == identity_id:
        return owner_view(row)
    return public_view(row)


@router.get("/{identity_id}/activation")
async def get_identity_activation(
    identity_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """主身份是否已激活 = 本人实名认证（证件 + 刷脸）是否通过。

    操作台、撮合、Runtime 都读这一个口径，不各自再算一遍。
    """
    validate_public_url_segment("identity_id", identity_id)
    return await activation_of(db, identity_id)


@router.post("/{identity_id}/verification/submit")
async def submit_identity_verification(
    identity_id: str,
    body: SubmitVerificationBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)

    try:
        payload = build_submission(
            level=body.level,
            doc_digest=body.doc_digest,
            face_digest=body.face_digest,
            package_digest=body.package_digest,
            package_cipher=body.package_cipher,
            encryption=body.encryption,
            extracted=body.extracted,
            raw_payload=body.model_dump(),
        )
    except IdentityVerificationError as exc:
        raise _translate(exc) from exc

    row = await db.get(IdentityVerificationModel, identity_id)
    current = row.status if row else "none"
    try:
        assert_can_submit(current)
    except IdentityVerificationError as exc:
        raise _translate(exc) from exc

    if row is None:
        row = IdentityVerificationModel(identity_id=identity_id)
        db.add(row)

    row.status = "pending"
    row.level = payload["level"]
    row.doc_digest = payload["doc_digest"]
    row.face_digest = payload["face_digest"]
    row.package_digest = payload["package_digest"]
    row.package_cipher = payload["package_cipher"]
    row.encryption = payload["encryption"]
    row.extracted = payload["extracted"]
    row.reviewer_identity_id = None
    row.review_note = None
    row.verified_at = None
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


@router.post("/{identity_id}/verification/verify")
async def verify_identity_verification(
    identity_id: str,
    body: VerifyDecisionBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    validate_public_url_segment("identity_id", identity_id)
    reviewer = await _require_verifier(db, request, identity_id)

    row = await db.get(IdentityVerificationModel, identity_id)
    if row is None:
        raise HTTPException(404, "identity verification not found")

    try:
        assert_can_decide(row.status, body.decision)
    except IdentityVerificationError as exc:
        raise _translate(exc) from exc

    if body.decision == "verified":
        mark_verified(row, reviewer_identity_id=reviewer, note=body.reason)
    else:
        row.status = "rejected"
        row.reviewer_identity_id = reviewer
        row.review_note = (body.reason or "")[:2000] or None
        row.verified_at = None
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return owner_view(row)


# ---------------------------------------------------------------------------
# 第三方实名 / 活体服务：开会话 → 回查 / 回调 → 置位
#
# 公开的那条（provider_router）是**服务商服务器**打过来的，带不了 Karma 令牌，
# 所以它挂在 app.py 里不带鉴权依赖的那一组路由上，靠服务商签名自证。
# ---------------------------------------------------------------------------

provider_router = APIRouter()

_ALLOWED_RETURN_ORIGINS_FALLBACK = ("http://127.0.0.1", "http://localhost")


def _allowed_return_origins() -> set[str]:
    """return_url 只允许回到「我们自己的站点」：公开地址 + CORS 白名单。"""
    settings = get_settings()
    origins: set[str] = set()
    for raw in (
        (getattr(settings, "identity_provider_public_base_url", "") or ""),
        (getattr(settings, "cors_allow_origins", "") or ""),
    ):
        for item in str(raw).split(","):
            item = item.strip().rstrip("/")
            if item:
                origins.add(item if "://" in item else "https://" + item)
    return origins


def _safe_return_url(value: str | None) -> str | None:
    """服务商核验完会把用户送回这里 —— 不能让它变成一个开放重定向。"""
    text = (value or "").strip()
    if not text:
        return None
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        raise HTTPException(400, "return_url must be an absolute URL")
    origin = f"{parts.scheme}://{parts.netloc}"
    allowed = _allowed_return_origins()
    if "://" in text and origin in allowed:
        return text
    if (getattr(get_settings(), "app_env", "") or "").strip().lower() in (
        "development",
        "dev",
        "local",
        "test",
    ) and origin.startswith(_ALLOWED_RETURN_ORIGINS_FALLBACK):
        return text
    raise HTTPException(400, "return_url must point at one of our own origins")


def _translate_provider_error(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _assert_mock_push_allowed() -> None:
    """模拟通道只在本地可用；生产环境一律 404（不暴露这个入口存在）。"""
    settings = get_settings()
    env = (settings.app_env or "").strip().lower()
    if configured_name(settings) != "mock" or env not in ("development", "dev", "local", "test"):
        raise HTTPException(404, "Not Found")


@router.get("/{identity_id}/verification/provider")
async def get_identity_provider_state(
    identity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """操作台问：接了服务商没有？我这次核验走到哪一步了？"""
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)
    row = await db.get(IdentityVerificationModel, identity_id)
    return {
        "identity_id": identity_id,
        "provider": provider_status(),
        "state": provider_view(row) if row is not None else None,
    }


@router.post("/{identity_id}/verification/provider/session")
async def create_identity_provider_session(
    identity_id: str,
    body: ProviderSessionBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """开一次核验。返回的是**给浏览器**的东西：会话号 + 服务商入口地址。"""
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)
    try:
        created = await start_session(
            db, identity_id=identity_id, return_url=_safe_return_url(body.return_url)
        )
    except ProviderError as exc:
        raise _translate_provider_error(exc) from exc
    return {"identity_id": identity_id, "provider": provider_status(), "session": created}


@router.post("/{identity_id}/verification/provider/sync")
async def sync_identity_provider_session(
    identity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """主动回查一次（pull 型服务商：用户做完核验、前端轮询这个接口拿结论）。"""
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)
    try:
        result = await sync_active_session(db, identity_id=identity_id)
    except ProviderError as exc:
        raise _translate_provider_error(exc) from exc
    row = await db.get(IdentityVerificationModel, identity_id)
    return {**result, "verification": owner_view(row) if row is not None else None}


@router.post("/{identity_id}/verification/provider/mock-push")
async def mock_push_identity_provider(
    identity_id: str,
    body: MockPushBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """本地自测：签一条回调推给**公开的**回调入口，整条链路（含验签）真的跑一遍。"""
    _assert_mock_push_allowed()
    validate_public_url_segment("identity_id", identity_id)
    await _require_owner(db, request, identity_id)

    row = await db.get(IdentityVerificationModel, identity_id)
    state = provider_view(row) if row is not None else None
    session_id = (body.session_id or "").strip() or str(
        ((state or {}).get("active") or {}).get("session_id") or ""
    )
    if not session_id:
        raise HTTPException(409, "no identity verification session is waiting for this identity")
    try:
        raw_body, signature = build_mock_push(
            identity_id=identity_id,
            session_id=session_id,
            outcome=body.outcome,
            reason_code=body.reason_code,
        )
        result = await apply_callback(
            db,
            identity_id=identity_id,
            provider_name="mock",
            headers={"x-karma-provider-signature": signature},
            raw_body=raw_body,
        )
    except ProviderError as exc:
        raise _translate_provider_error(exc) from exc
    return result


@provider_router.post("/{identity_id}/verification/provider-callback/{provider_name}")
@provider_router.post("/{identity_id}/verification/provider-callback")
async def identity_provider_callback(
    identity_id: str,
    request: Request,
    provider_name: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """服务商服务器的回调入口。

    * 没有 Karma 令牌可用，鉴权就是**它自己的签名**（push 型）。
    * pull 型（阿里云 / 腾讯云）这里只当「去查一下」的信号：结论由服务器带密钥回查，
      所以伪造一条回调没有任何收益。
    * 不管哪种，消息里的会话号必须对得上我们开出去的那一次，否则 409。
    """
    validate_public_url_segment("identity_id", identity_id)
    name = (provider_name or configured_name()).strip().lower()
    if name == "none":
        raise HTTPException(409, "no real-name/liveness provider is configured")
    raw_body = await request.body()
    try:
        return await apply_callback(
            db,
            identity_id=identity_id,
            provider_name=name,
            headers=request.headers,
            raw_body=raw_body,
        )
    except ProviderError as exc:
        raise _translate_provider_error(exc) from exc

