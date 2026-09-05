"""
Karma — Identity Role Profile API (P1: one card, many identities)
===================================================================

统一入口：一张身份卡（owner_identity_id）可派生多个「角色身份档案」
（identity_role_profiles），每个档案绑定独立的 class + KYC 状态 + 可见性。

- class ∈ {individual, merchant, enterprise, verifier, arbitrator}
- kyc_status ∈ {none, pending, verified, rejected}
- visibility ∈ {public, private}；enterprise 默认 private（资金流保密），其余默认 public
- 对特定授权方开放某几笔明细（authorized disclosure）属于 P2/P3，暂不实现

区别于已存在的：
- IdentityProfileModel（identity_profiles，DID/法律身份）
- SubIdentityModel（sub_identities，交易角色）

两者不冲突，本特性使用独立表 identity_role_profiles。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import IdentityRoleProfile
from db.session import get_db
from services.path_param_safety import validate_public_url_segment

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

    model_config = {"populate_by_name": True}


class RoleProfileUpdate(BaseModel):
    class_: str | None = Field(default=None, alias="class", pattern=_CLASS_PATTERN)
    kyc_status: str | None = Field(default=None, pattern=_KYC_PATTERN)
    visibility: str | None = Field(default=None, pattern=_VISIBILITY_PATTERN)
    display_name: str | None = Field(default=None, max_length=256)
    kyc_payload: dict | None = None
    status: str | None = Field(default=None, max_length=16)

    model_config = {"populate_by_name": True}


def _serialize(row: IdentityRoleProfile) -> dict:
    return {
        "profile_id": row.profile_id,
        "owner_identity_id": row.owner_identity_id,
        "class": row.class_,
        "kyc_status": row.kyc_status,
        "visibility": row.visibility,
        "display_name": row.display_name,
        "kyc_payload": row.kyc_payload or {},
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("", status_code=201)
async def create_role_profile(
    body: RoleProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建一个角色身份档案；未显式指定 visibility 时按 class 取默认值。"""
    visibility = body.visibility or _default_visibility(body.class_)
    row = IdentityRoleProfile(
        owner_identity_id=body.owner_identity_id,
        class_=body.class_,
        kyc_status=body.kyc_status,
        visibility=visibility,
        display_name=body.display_name,
        kyc_payload=body.kyc_payload,
        status=body.status,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _serialize(row)


@router.get("")
async def list_role_profiles(
    owner_identity_id: str | None = Query(default=None, max_length=128),
    class_: str | None = Query(default=None, alias="class", pattern=_CLASS_PATTERN),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """按 owner / class 过滤的角色身份档案列表。"""
    base_q = select(IdentityRoleProfile)
    count_q = select(func.count(IdentityRoleProfile.profile_id))
    if owner_identity_id:
        base_q = base_q.where(IdentityRoleProfile.owner_identity_id == owner_identity_id)
        count_q = count_q.where(IdentityRoleProfile.owner_identity_id == owner_identity_id)
    if class_:
        base_q = base_q.where(IdentityRoleProfile.class_ == class_)
        count_q = count_q.where(IdentityRoleProfile.class_ == class_)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (
        await db.execute(
            base_q.order_by(IdentityRoleProfile.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {"profiles": [_serialize(r) for r in rows], "total": total}


@router.get("/{profile_id}")
async def get_role_profile(profile_id: str, db: AsyncSession = Depends(get_db)):
    """按 profile_id 读取单个角色身份档案。"""
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")
    return _serialize(row)


@router.put("/{profile_id}")
async def update_role_profile(
    profile_id: str,
    body: RoleProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新：仅更新请求中显式提供的字段。"""
    validate_public_url_segment("profile_id", profile_id)
    row = await db.get(IdentityRoleProfile, profile_id)
    if not row:
        raise HTTPException(404, "role profile not found")

    data = body.model_dump(exclude_unset=True)
    if "class_" in data:
        row.class_ = data["class_"]
    if "kyc_status" in data:
        row.kyc_status = data["kyc_status"]
    if "visibility" in data:
        row.visibility = data["visibility"]
    if "display_name" in data:
        row.display_name = data["display_name"]
    if "kyc_payload" in data:
        row.kyc_payload = data["kyc_payload"]
    if "status" in data:
        row.status = data["status"]
    row.updated_at = datetime.utcnow()

    await db.flush()
    await db.refresh(row)
    return _serialize(row)
