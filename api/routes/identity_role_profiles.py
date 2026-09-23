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

from db.models.orm import IdentityRoleProfile
from db.session import get_db
from services import governance_stake
from services.face_activation import FaceError, assert_same_person
from services.identity_actor import resolve_actor_identity_id
from services.identity_verification import build_bind_wallet_message
from services.path_param_safety import validate_public_url_segment
from services.runtime_wallet import verify_personal_message

router = APIRouter()

CLASS_VALUES = ("individual", "merchant", "enterprise", "verifier", "arbitrator")
KYC_STATUS_VALUES = ("none", "pending", "verified", "rejected")
VISIBILITY_VALUES = ("public", "private")

_CLASS_PATTERN = "^(individual|merchant|enterprise|verifier|arbitrator)$"
_KYC_PATTERN = "^(none|pending|verified|rejected)$"
_VISIBILITY_PATTERN = "^(public|private)$"


def _default_visibility(class_: str) -> str:
    """enterprise 默认私有，其余角色默认公开。"""
    return "private" if class_ == "enterprise" else "public"


class RoleProfileCreate(BaseModel):
    owner_identity_id: str = Field(..., min_length=1, max_length=128)
    class_: str = Field(..., alias="class", pattern=_CLASS_PATTERN)
    kyc_status: str = Field(default="none", pattern=_KYC_PATTERN)
    visibility: str | None = Field(default=None, pattern=_VISIBILITY_PATTERN)
    display_name: str | None = Field(default=None, max_length=256)
    kyc_payload: dict = Field(default_factory=dict)
    status: str = Field(default="active", max_length=16)
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
    status: str | None = Field(default=None, max_length=16)
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
    """创建一个角色身份档案；仅 owner（认证身份 == owner_identity_id）可创建。"""
    actor = await resolve_actor_identity_id(db, request)
    if not actor:
        raise HTTPException(403, "authentication required to create a role profile")
    if actor != body.owner_identity_id:
        raise HTTPException(403, "owner_identity_id must match the authenticated identity")
    stake_amount = await _resolve_governance_stake(db, actor, body.class_, body.stake_amount)

    visibility = body.visibility or _default_visibility(body.class_)
    row = IdentityRoleProfile(
        owner_identity_id=body.owner_identity_id,
        class_=body.class_,
        kyc_status=body.kyc_status,
        visibility=visibility,
        display_name=body.display_name,
        kyc_payload=body.kyc_payload,
        status=body.status,
        stake_amount=stake_amount,
    )
    db.add(row)
    await db.flush()
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
        row.kyc_status = data["kyc_status"]
    if "visibility" in data:
        row.visibility = data["visibility"]
    if "display_name" in data:
        row.display_name = data["display_name"]
    if "kyc_payload" in data:
        row.kyc_payload = data["kyc_payload"]
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


@router.post("/{profile_id}/bind-wallet")
async def bind_role_profile_wallet(
    profile_id: str,
    body: BindWalletBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """把子身份绑定到一个操作钱包（需要该钱包的 personal_sign 签名）。

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

    row.bound_wallet_address = wallet.lower()
    row.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(row)
    return _serialize(row, full=True)
