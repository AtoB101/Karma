"""
Karma — Identity Role Profile API (P1: one card, many identities)
===================================================================

统一入口：一张身份卡（owner_identity_id）可派生多个「角色身份档案」
（identity_role_profiles），每个档案绑定独立的 class + KYC 状态 + 可见性。

- class ∈ {individual, merchant, enterprise, verifier, arbitrator}
- kyc_status ∈ {none, pending, verified, rejected}
- visibility ∈ {public, private}；enterprise 默认 private（资金流保密），其余默认 public

鉴权 / 可见性（P3 补齐）：
- create/update 仅 owner；list/get 对非 owner 只返回 public 档案并脱敏
  （剥掉 owner_identity_id 与 kyc_payload）。

区别于已存在的：
- IdentityProfileModel（identity_profiles，DID/法律身份）
- SubIdentityModel（sub_identities，交易角色）

两者不冲突，本特性使用独立表 identity_role_profiles。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import ArbitrationPoolMemberStatus
from db.models.orm import ArbitrationPoolMemberModel, IdentityRoleProfile
from db.session import get_db
from services import governance_stake
from services.actor_guards import admin_actor_ids
from services.console_notice import (
    NOTICE_GOVERNANCE_ROLE_GRANTED,
    NOTICE_GOVERNANCE_ROLE_REVOKED,
    NOTICE_WALLET_REBOUND,
    add_notice_safe,
)
from services.security_monitoring import SecurityMonitoringEventType, record_security_event
from services.face_activation import FaceError, assert_same_person
from services.identity_actor import resolve_actor_identity_id
from services.identity_verification import (
    IdentityVerificationError,
    assert_no_plaintext_payload,
    build_bind_wallet_message,
)
from services.path_param_safety import validate_public_url_segment
from services.runtime_wallet import verify_personal_message

router = APIRouter()

CLASS_VALUES = ("individual", "merchant", "enterprise", "verifier", "arbitrator")
KYC_STATUS_VALUES = ("none", "pending", "verified", "rejected")
#: 档案状态：只有 active 有实际语义（能力位按它判），disabled = 本人停用这张卡。
STATUS_VALUES = ("active", "disabled")
VISIBILITY_VALUES = ("public", "private")

_CLASS_PATTERN = "^(individual|merchant|enterprise|verifier|arbitrator)$"
_KYC_PATTERN = "^(none|pending|verified|rejected)$"
_STATUS_PATTERN = "^(active|disabled)$"
_VISIBILITY_PATTERN = "^(public|private)$"


def _default_visibility(class_: str) -> str:
    """enterprise 默认私有，其余角色默认公开。"""
    return "private" if class_ == "enterprise" else "public"


#: 「复核结论」这个键只属于复核方（``identity_kyc`` 的 verify 路由）。本人提交的
#: KYC 载荷里带了它，等于自己写一份「已通过」；所以任何客户端写入路径都先摘掉。
_KYC_VERDICT_KEY = "verification"


def _without_client_verdict(payload: dict | None) -> dict:
    data = dict(payload or {})
    data.pop(_KYC_VERDICT_KEY, None)
    return data


def _sanitize_client_kyc_payload(payload: dict | None) -> dict:
    """本人建 / 改档案时随手上传的 KYC 载荷：摘掉复核结论，并过和提交同一条明文红线。

    提交路径（``identity_kyc.submit_kyc``）一直有 ``assert_no_plaintext_payload``，
    但建 / 改档案的 ``kyc_payload`` 以前是直接入库的 —— 证件原图 / 人脸明文可以
    绕过提交路径从这儿塞进来。这里补齐同一条红线。
    """
    data = _without_client_verdict(payload)
    try:
        assert_no_plaintext_payload(data)
    except IdentityVerificationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return data


def _reject_self_declared_kyc(kyc_status: str | None) -> None:
    """KYC 状态只能由认证流程写入，不能由档案本人在建/改档案时自报。

    历史缺陷（2026-10-08 复核）：``POST`` 与 ``PUT`` 都直接照收请求体里的
    ``kyc_status``，于是本人一次调用就能把档案写成 ``verified`` —— 操作台显示
    「已验证」、对外列表也这么答，而证件一份没交、复核一个人没看。企业 / 个体户
    的认证是消费者判断「能不能跟你做生意」的依据，这条自报必须堵死。
    """
    if (kyc_status or "none").strip() != "none":
        raise HTTPException(
            422,
            "kyc_status 不能由本人自报：档案一律从 none 开始，认证状态只能由认证流程写入"
            "（提交 KYC → 复核通过，或同人刷脸开通）",
        )


class RoleProfileCreate(BaseModel):
    owner_identity_id: str = Field(..., min_length=1, max_length=128)
    class_: str = Field(..., alias="class", pattern=_CLASS_PATTERN)
    kyc_status: str = Field(default="none", pattern=_KYC_PATTERN)
    visibility: str | None = Field(default=None, pattern=_VISIBILITY_PATTERN)
    display_name: str | None = Field(default=None, max_length=256)
    kyc_payload: dict = Field(default_factory=dict)
    status: str = Field(default="active", pattern=_STATUS_PATTERN)
    # 治理岗（verifier / arbitrator）的质押承诺额。GOVERNANCE_OPEN_JOIN 打开后
    # 靠它开通（必须低于/等于已锁仓 USDC）；白名单开的岗可以不带。
    stake_amount: float | None = Field(default=None, ge=0)

    model_config = {"populate_by_name": True, "extra": "forbid"}  # P2-10


class RoleProfileUpdate(BaseModel):
    class_: str | None = Field(default=None, alias="class", pattern=_CLASS_PATTERN)
    kyc_status: str | None = Field(default=None, pattern=_KYC_PATTERN)
    visibility: str | None = Field(default=None, pattern=_VISIBILITY_PATTERN)
    display_name: str | None = Field(default=None, max_length=256)
    kyc_payload: dict | None = None
    # 子身份默认的权限 / 边界：生成 SDK 的授权向导会预填这些值。
    spend_policy: dict | None = None
    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    # 改质押：和开通同一把尺子（低于下限 422、没有锁仓背书 409）
    stake_amount: float | None = Field(default=None, ge=0)

    model_config = {"populate_by_name": True, "extra": "forbid"}  # P2-10


def _serialize(row: IdentityRoleProfile, *, full: bool = False) -> dict:
    """`full=True` only for the owner — exposes owner_identity_id + kyc_payload."""
    data = {
        "profile_id": row.profile_id,
        "class": row.class_,
        "kyc_status": row.kyc_status,
        "visibility": row.visibility,
        "display_name": row.display_name,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if full:
        data["owner_identity_id"] = row.owner_identity_id
        data["kyc_payload"] = row.kyc_payload or {}
        data["bound_wallet_address"] = getattr(row, "bound_wallet_address", None)
        data["spend_policy"] = getattr(row, "spend_policy", None) or {}
        data["stake_amount"] = float(getattr(row, "stake_amount", 0.0) or 0.0)
    return data



def _may_grant_governance(actor: str | None) -> bool:
    """治理身份发放方：``GOVERNANCE_VERIFIER_IDS`` 白名单 ∪ 管理员白名单（G5）。

    与 ``governance_stake.whitelisted`` 同一口径（身份命名空间），另收平台管理员 ——
    运维没有道理还得先把自己加进发放方名单才能收岗。
    """
    if not actor:
        return False
    return governance_stake.whitelisted(actor) or actor in admin_actor_ids()


#: 这两个角色是**治理角色**：verifier 能复核别人的主体认证与开发者实名，
#: arbitrator 能裁争议。放任自建等于谁都能给自己开一个「审批权」——
#: 所以默认谁都不许（GOVERNANCE_VERIFIER_IDS 是运维白名单，见 config/settings.py）。
GOVERNANCE_CLASSES = ("verifier", "arbitrator")


async def _resolve_governance_stake(
    db: AsyncSession, actor: str, class_: str, stake_amount: float | None
) -> float:
    """治理岗开通 / 换岗前的闸门，返回该记下来的质押承诺额。

    - 非治理岗：与质押无关，记 0；
    - 白名单（GOVERNANCE_VERIFIER_IDS）：平台自己承担责任的岗，放行、记 0。
      不拿用户的押金去给平台的岗背书，也不因为押金变动牵连运维岗；
    - GOVERNANCE_OPEN_JOIN 打开：走质押通道 —— 低于平台下限 422，
      没有锁仓 USDC 背书 409（规矩与仲裁入池一致，见 services/governance_stake.py）；
    - 两条路都没开：维持原样 403。
    """
    if class_ not in GOVERNANCE_CLASSES:
        return 0.0
    if governance_stake.whitelisted(actor):
        return 0.0
    if not governance_stake.open_join():
        raise HTTPException(
            403,
            f"{class_} 是治理角色，不能自助开通：请由运维把身份加入 GOVERNANCE_VERIFIER_IDS，"
            "或让服务端打开 GOVERNANCE_OPEN_JOIN 后凭锁仓质押开通",
        )
    state = await governance_stake.assert_stake_acceptable(
        db, identity_id=actor, stake_amount=stake_amount
    )
    return float(state["stake_amount"])


@router.post("", status_code=201)
async def create_role_profile(
    body: RoleProfileCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建一个角色身份档案。

    - 默认**仅 owner**：认证身份必须等于 ``owner_identity_id``；
    - 例外（G5）：``verifier`` / ``arbitrator`` 这两个治理岗可以由**治理发放方**
      （``GOVERNANCE_VERIFIER_IDS`` 白名单 ∪ 管理员）替他人开 —— 平台指派、记 0 质押，
      并给被指派人留一条站内回执 + 一条安全事件。别的类别一律仍要本人。
    """
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to create a role profile")
    granting = actor != body.owner_identity_id
    if granting and not (body.class_ in GOVERNANCE_CLASSES and _may_grant_governance(actor)):
        raise HTTPException(403, "owner_identity_id must match the authenticated identity")
    _reject_self_declared_kyc(body.kyc_status)
    if granting:
        # 指派出来的治理岗不占被指派人的押金（与 assert_governor_active 的
        # 「appointed」一档对齐）：这一档跟的是名单，不是押金。
        stake_amount = 0.0
    else:
        stake_amount = await _resolve_governance_stake(db, actor, body.class_, body.stake_amount)

    visibility = body.visibility or _default_visibility(body.class_)
    row = IdentityRoleProfile(
        owner_identity_id=body.owner_identity_id,
        class_=body.class_,
        kyc_status="none",
        visibility=visibility,
        display_name=body.display_name,
        kyc_payload=_sanitize_client_kyc_payload(body.kyc_payload),
        status=body.status,
        stake_amount=stake_amount,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    if granting:
        record_security_event(
            SecurityMonitoringEventType.GOVERNANCE_ROLE_GRANTED,
            metadata={
                "profile_id": row.profile_id,
                "owner_identity_id": row.owner_identity_id,
                "class": row.class_,
                "granted_by": actor,
            },
        )
        await db.commit()
        await add_notice_safe(
            db,
            karma_identity_id=row.owner_identity_id,
            kind=NOTICE_GOVERNANCE_ROLE_GRANTED,
            payload={"profile_id": row.profile_id, "class": row.class_, "granted_by": actor},
        )
        await db.refresh(row)
    return _serialize(row, full=True)


@router.get("")
async def list_role_profiles(
    owner_identity_id: str | None = Query(default=None, max_length=128),
    class_: str | None = Query(default=None, alias="class", pattern=_CLASS_PATTERN),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """按 owner / class 过滤。非 owner（或匿名）只看到 public 档案，且脱敏。"""
    actor = await resolve_actor_identity_id(db, request)
    is_owner = bool(actor) and (owner_identity_id is None or actor == owner_identity_id)

    base_q = select(IdentityRoleProfile)
    count_q = select(func.count(IdentityRoleProfile.profile_id))
    if owner_identity_id:
        base_q = base_q.where(IdentityRoleProfile.owner_identity_id == owner_identity_id)
        count_q = count_q.where(IdentityRoleProfile.owner_identity_id == owner_identity_id)
    if class_:
        base_q = base_q.where(IdentityRoleProfile.class_ == class_)
        count_q = count_q.where(IdentityRoleProfile.class_ == class_)
    if not is_owner:
        base_q = base_q.where(IdentityRoleProfile.visibility == "public")
        count_q = count_q.where(IdentityRoleProfile.visibility == "public")

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            base_q.order_by(IdentityRoleProfile.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {"profiles": [_serialize(r, full=is_owner) for r in rows], "total": total}


@router.get("/{profile_id}")
async def get_role_profile(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """按 profile_id 读取。私有档案仅 owner 可见；非 owner 只拿脱敏视图。"""
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")

    actor = await resolve_actor_identity_id(db, request)
    is_owner = bool(actor) and actor == row.owner_identity_id
    if row.visibility == "private" and not is_owner:
        raise HTTPException(404, "role profile not found")
    data = _serialize(row, full=is_owner)
    if is_owner:
        from services.identity_reputation import attach_profile_reputation

        data = await attach_profile_reputation(db, data)
    return data


@router.put("/{profile_id}")
async def update_role_profile(
    profile_id: str,
    body: RoleProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """部分更新；仅 owner。"""
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")

    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != row.owner_identity_id:
        raise HTTPException(403, "only the profile owner can update it")

    data = body.model_dump(exclude_unset=True)
    if "class_" in data:
        if data["class_"] != row.class_:
            row.stake_amount = await _resolve_governance_stake(
                db, actor, data["class_"], body.stake_amount
            )
        row.class_ = data["class_"]
    if "stake_amount" in data and row.class_ in GOVERNANCE_CLASSES:
        row.stake_amount = await _resolve_governance_stake(
            db, actor, row.class_, data["stake_amount"]
        )
    if "kyc_status" in data:
        _reject_self_declared_kyc(data["kyc_status"])
    if "visibility" in data:
        row.visibility = data["visibility"]
    if "display_name" in data:
        row.display_name = data["display_name"]
    if "kyc_payload" in data:
        row.kyc_payload = _sanitize_client_kyc_payload(data["kyc_payload"])
    if "spend_policy" in data:
        row.spend_policy = data["spend_policy"] or {}
    if "status" in data:
        row.status = data["status"]
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.refresh(row)
    return _serialize(row, full=True)


class FaceConsistencyBody(BaseModel):
    """追加身份的「同人比对」结论：分数由本人设备算，服务端复核签名 / 参考模板 / 新鲜度 / 过线。

    故意允许未知字段：夹带人脸明文要由服务层指名拒掉，而不是被静默丢掉。
    """

    model_config = {"extra": "allow"}

    wallet_address: str = Field(..., min_length=10, max_length=128)
    wallet_signature: str = Field(..., min_length=130, max_length=200)
    reference_digest: str = Field(..., min_length=64, max_length=64)
    capture_digest: str = Field(..., min_length=64, max_length=64)
    score: float = Field(..., ge=0.0, le=1.0)
    liveness: dict = Field(default_factory=dict)
    encryption: dict = Field(default_factory=dict)
    template_cipher: str | None = Field(default=None, max_length=2_000_000)


@router.post("/{profile_id}/face-consistency")
async def confirm_role_profile_same_person(
    profile_id: str,
    body: FaceConsistencyBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """追加身份自动开通：填完标准字段再刷一次脸，本机比出分数，服务端复核后直接置为已核验。

    判据与边界见 services/face_activation.py。这里只做两件事：**复核**、然后**置位**。
    治理岗（verifier / arbitrator）不因为「是同一个人」就免掉质押那道闸 ——
    那条路走 create/update，规矩不变。
    """
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if row is None:
        raise HTTPException(404, "role profile not found")
    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != row.owner_identity_id:
        raise HTTPException(403, "only the profile owner can confirm the same-person check")

    try:
        verdict = await assert_same_person(
            db,
            owner_identity_id=row.owner_identity_id,
            profile_id=profile_id,
            class_=row.class_,
            wallet_address=body.wallet_address,
            wallet_signature=body.wallet_signature,
            reference_digest=body.reference_digest,
            capture_digest=body.capture_digest,
            score=body.score,
            liveness=body.liveness,
            encryption=body.encryption,
            template_cipher=body.template_cipher,
        )
    except FaceError as exc:
        raise HTTPException(exc.status, exc.message) from exc

    row.kyc_status = "verified"
    payload = dict(row.kyc_payload or {})
    payload["face_consistency"] = {
        "mode": "device_template",
        "score": verdict["score"],
        "threshold": verdict["threshold"],
        "reference_digest": verdict["reference_digest"],
        "capture_digest": verdict["capture_digest"],
        "angles": verdict["liveness"].get("angles"),
        "reviewer": verdict["reviewer"],
        "checked_at": verdict["checked_at"],
    }
    row.kyc_payload = payload
    row.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(row)
    return {**_serialize(row, full=True), "face_consistency": verdict}


class BindWalletBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # P2-10: 未知字段直接报错，不静默丢弃
    wallet_address: str = Field(..., min_length=42, max_length=128)
    wallet_signature: str = Field(..., min_length=130, max_length=200)
    # 换绑（这档案已经绑过另一个钱包）走「本人刷脸」闸门：下面这组字段是刷脸结论，
    # 与 /face-consistency 同一套判据（见 services/face_activation.assert_same_person）。
    # 签名的钱包必须是这个身份的**绑定钱包**（身份根），不是被换掉的那个操作钱包。
    face_wallet_address: str | None = Field(default=None, max_length=128)
    face_wallet_signature: str | None = Field(default=None, max_length=200)
    face_reference_digest: str | None = Field(default=None, max_length=64)
    face_capture_digest: str | None = Field(default=None, max_length=64)
    face_score: float | None = Field(default=None, ge=0.0, le=1.0)
    face_liveness: dict | None = None
    face_encryption: dict | None = None
    face_template_cipher: str | None = Field(default=None, max_length=2_000_000)


@router.post("/{profile_id}/bind-wallet")
async def bind_role_profile_wallet(
    profile_id: str,
    body: BindWalletBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """把子身份绑定到一个操作钱包。

    - 首次绑定：只需要该钱包的 personal_sign（证明「这个钱包确实愿意代表这张子身份」）。
    - **换绑**（这张子身份已经绑过另一个钱包）：光有 owner 会话 / 一把签名不够 ——
      换钱包 = 换代表权，必须**本人刷脸通过**（同一套同人比对判据），签名来自身份的绑定
      钱包；另加新钱包自己的签名。动作本身落安全事件 + 站内回执（G6）。

    这只是「谁可以代表这个子身份签名」，不是资金账户：子身份的收入与支出仍然
    统一走主身份钱包，见操作台身份页的资金归属说明。
    """
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")

    actor = await resolve_actor_identity_id(db, request)
    if not actor or actor != row.owner_identity_id:
        raise HTTPException(403, "only the profile owner can bind a wallet")

    wallet = body.wallet_address.strip()
    previous = str(row.bound_wallet_address or "").strip().lower()
    rebind = bool(previous) and previous != wallet.lower()

    # 新钱包必须自己签（证明「控制着这个地址」）—— 首次与换绑都要过这一关。
    message = build_bind_wallet_message(
        profile_id=profile_id,
        owner_identity_id=row.owner_identity_id,
        wallet_address=wallet,
    )
    verify_personal_message(
        message=message,
        wallet_address=wallet,
        wallet_signature=body.wallet_signature,
    )

    if rebind:
        # 换绑是「把代表权挪到另一个钱包」：必须本人刷脸，单靠 owner 会话不足以放行。
        if not body.face_wallet_address or not body.face_wallet_signature:
            raise HTTPException(
                409,
                "changing the bound wallet requires a fresh face check: submit the same-person "
                "evidence (face_wallet_address / face_wallet_signature / face_reference_digest / "
                "face_capture_digest / face_score / face_liveness)",
            )
        try:
            verdict = await assert_same_person(
                db,
                owner_identity_id=row.owner_identity_id,
                profile_id=profile_id,
                class_=row.class_,
                wallet_address=body.face_wallet_address,
                wallet_signature=body.face_wallet_signature,
                reference_digest=body.face_reference_digest,
                capture_digest=body.face_capture_digest,
                score=body.face_score,
                liveness=body.face_liveness,
                encryption=body.face_encryption,
                template_cipher=body.face_template_cipher,
            )
        except FaceError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    row.bound_wallet_address = wallet.lower()
    row.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(row)

    if rebind:
        record_security_event(
            SecurityMonitoringEventType.IDENTITY_WALLET_REBIND,
            metadata={
                "profile_id": profile_id,
                "owner_identity_id": row.owner_identity_id,
                "previous_wallet": previous,
                "new_wallet": wallet.lower(),
                "face_score": verdict["score"],
                "face_threshold": verdict["threshold"],
                "face_reviewer": verdict["reviewer"],
            },
        )
        # 换绑是不可逆动作：先把动作 commit 掉，再落一条站内回执（提醒写失败不影响换绑）。
        await db.commit()
        await add_notice_safe(
            db,
            karma_identity_id=row.owner_identity_id,
            kind=NOTICE_WALLET_REBOUND,
            payload={
                "profile_id": profile_id,
                "previous_wallet": previous,
                "new_wallet": wallet.lower(),
            },
        )
        await db.refresh(row)
    return _serialize(row, full=True)


@router.post("/{profile_id}/governance-revoke")
async def revoke_governance_role(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """收回一个治理岗（verifier / arbitrator）：治理发放方或管理员专属（G5）。

    收回 = 档案 ``status`` 置 ``disabled``（复核台入口与能力位都按 ``active`` 判，
    立即失效）；``arbitrator`` 同时把仲裁池成员置 ``inactive``，不再被派庭。
    动作落安全事件 + 给本人的站内回执。
    """
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if row is None:
        raise HTTPException(404, "role profile not found")
    if row.class_ not in GOVERNANCE_CLASSES:
        raise HTTPException(409, "only verifier / arbitrator profiles can be revoked this way")

    actor = await resolve_actor_identity_id(db, request)
    if not _may_grant_governance(actor):
        raise HTTPException(403, "only a governance issuer or admin can revoke a governance role")

    previous = row.status
    row.status = "disabled"
    row.updated_at = datetime.utcnow()

    pool_revoked = False
    if row.class_ == "arbitrator":
        pool_row = await db.get(ArbitrationPoolMemberModel, row.owner_identity_id)
        if pool_row is not None:
            pool_row.status = ArbitrationPoolMemberStatus.INACTIVE.value
            pool_row.updated_at = datetime.utcnow()
            pool_revoked = True

    await db.flush()
    await db.refresh(row)
    record_security_event(
        SecurityMonitoringEventType.GOVERNANCE_ROLE_REVOKED,
        metadata={
            "profile_id": profile_id,
            "owner_identity_id": row.owner_identity_id,
            "class": row.class_,
            "revoked_by": actor or "",
            "previous_status": previous,
            "arbitration_pool_inactivated": pool_revoked,
        },
    )
    await db.commit()
    await add_notice_safe(
        db,
        karma_identity_id=row.owner_identity_id,
        kind=NOTICE_GOVERNANCE_ROLE_REVOKED,
        payload={"profile_id": profile_id, "class": row.class_, "revoked_by": actor or ""},
    )
    await db.refresh(row)
    return _serialize(row, full=True)
