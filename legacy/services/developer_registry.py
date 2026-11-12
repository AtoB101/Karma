"""技能开发者实名（Skill Developer Registry）。

为什么还要这一层
----------------
主体认证回答的是「这家公司是谁、它控制哪个官网」；上架签名回答的是「这个签名钱包在
这个身份的在册钱包里」。两件事合起来仍然没有回答最后一个问题：**这家公司里，操作这个
身份、上架这个技能的，到底是哪个人。**

商业化的口径是：技能目录里每一个可收费的 endpoint，背后都要有一个可追责的自然人，
而且这个人**签署过开发者协议**（协议正文是服务端常量，摘要落库，签名由钱包背书）。
复核由「verifier 类档案」完成，且**不能自审自己**。

三条红线
--------
* 协议 ``message`` 由服务端生成，前端只负责让钱包签它 —— 前后端各写一遍规范化，
  差一个字节就是白签；
* 实名材料（选传）只存密文包 + sha256 摘要，明文在服务层被指名拒掉；
* 上架时签名钱包必须**就是签协议的那个钱包**，且该档案已通过复核 —— 这才叫
  「是不是本人」，而不是「这个身份有权限」。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import EntityVerificationModel, SkillDeveloperModel
from services.chain import wallet_lock
from services.identity_verification import (
    IdentityVerificationError,
    assert_no_plaintext_payload,
    sanitize_encryption,
    sanitize_package_cipher,
)

DEVELOPER_STATUSES = ("none", "pending", "verified", "rejected")

#: 状态机：提交 → 待审 → 通过 / 驳回；驳回后可以改了重交。
DEVELOPER_TRANSITIONS: dict[str, set[str]] = {
    "none": {"pending"},
    "pending": {"verified", "rejected"},
    "verified": set(),
    "rejected": {"pending"},
}

#: 开发者在公司里的角色 —— 只用于展示与复核，不参与权限判定。
DEVELOPER_ROLES = ("developer", "api_owner", "ops", "founder", "other")

#: 协议正文是不可变常量：改文本就必须换版本号，否则历史签名的摘要会对不上。
AGREEMENT_VERSION = "karma-developer-agreement-v1"
AGREEMENT_TERMS: tuple[str, ...] = (
    "1. 我以本人名义登记为 Karma 技能开发者，所填姓名、职务、所属主体真实有效。",
    "2. 我上架的技能、接口与数据来源合法，且我有权对外提供，不侵犯第三方权利。",
    "3. 我按上架声明中的单价与结算阈值计费；改价必须重新签名上架，旧签名即刻失效。",
    "4. 我接受 Karma 的验证机制：没有可验证的交付，就没有结算。",
    "5. 出现争议时我接受仲裁，并同意已质押的额度按规则被动用。",
    "6. 我知悉本协议由我的钱包签名存证，签名即代表本人的意思表示。",
)

SIGNUP_MESSAGE_PREFIX = "Karma developer signup"

MATERIAL_KINDS = ("ID_CARD", "WORK_BADGE", "EMPLOYMENT_PROOF", "AUTHORIZATION_LETTER", "OTHER")
MAX_MATERIALS = 8
MAX_SIGNATURE = 200
MAX_REAL_NAME = 64
MAX_ROLE_TITLE = 64
MAX_EMAIL = 200
MAX_NOTE = 2000

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]{1,190}\.[A-Za-z]{2,24}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class DeveloperError(Exception):
    """带 HTTP 状态的领域错误，路由层直接翻译。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------- 字段


def _clean_text(name: str, raw: Any, *, min_len: int, max_len: int) -> str:
    text = str(raw or "").strip()
    if len(text) < min_len:
        raise DeveloperError(400, f"{name} 至少 {min_len} 个字符")
    if len(text) > max_len:
        raise DeveloperError(400, f"{name} 不能超过 {max_len} 个字符")
    if _CONTROL_RE.search(text):
        raise DeveloperError(400, f"{name} 含不可见控制字符")
    return text


def normalize_real_name(raw: Any) -> str:
    """实名：真实姓名（中文 2 字起，西文 2 字符起）。"""
    return _clean_text("real_name", raw, min_len=2, max_len=MAX_REAL_NAME)


def normalize_role_title(raw: Any) -> str:
    return _clean_text("role_title", raw, min_len=2, max_len=MAX_ROLE_TITLE)


def normalize_email(raw: Any) -> str:
    text = str(raw or "").strip()
    if not _EMAIL_RE.match(text):
        raise DeveloperError(400, "contact_email 格式不正确")
    if len(text) > MAX_EMAIL:
        raise DeveloperError(400, f"contact_email 不能超过 {MAX_EMAIL} 个字符")
    return text


def normalize_developer_role(raw: Any) -> str:
    text = str(raw or "developer").strip().lower() or "developer"
    if text not in DEVELOPER_ROLES:
        raise DeveloperError(400, f"role 只能是 {'/'.join(DEVELOPER_ROLES)}")
    return text


def normalize_materials(raw: Any) -> list[dict[str, str]]:
    """材料清单只留 kind / name / digest —— 原件在密文包里，永远不进数据库。"""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise DeveloperError(400, "materials 必须是数组")
    if len(raw) > MAX_MATERIALS:
        raise DeveloperError(400, f"materials 最多 {MAX_MATERIALS} 份")
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DeveloperError(400, "materials 每一项都必须是对象")
        kind = str(item.get("kind") or "OTHER").strip().upper()
        if kind not in MATERIAL_KINDS:
            raise DeveloperError(400, f"材料类型 {kind} 不支持")
        name = _clean_text("materials.name", item.get("name"), min_len=1, max_len=120)
        digest = str(item.get("digest") or "").strip().lower()
        if not _DIGEST_RE.match(digest):
            raise DeveloperError(400, "materials.digest 必须是 sha256 十六进制摘要")
        out.append({"kind": kind, "name": name, "digest": digest})
    return out


def agreement_text() -> str:
    return "\n".join((f"Karma 开发者协议 {AGREEMENT_VERSION}",) + AGREEMENT_TERMS)


def agreement_digest() -> str:
    return hashlib.sha256(agreement_text().encode("utf-8")).hexdigest()


def build_signup_message(
    *,
    identity_id: str,
    legal_name: str,
    real_name: str,
    role_title: str,
    agreement_digest_hex: str | None = None,
) -> str:
    return "\n".join(
        [
            SIGNUP_MESSAGE_PREFIX,
            f"identity: {identity_id}",
            f"entity: {legal_name}",
            f"developer: {real_name}",
            f"role_title: {role_title}",
            f"agreement_version: {AGREEMENT_VERSION}",
            f"agreement_digest: {agreement_digest_hex or agreement_digest()}",
        ]
    )


def build_submission(payload: dict[str, Any], *, raw_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """一份完整提交：实名信息 + 材料清单（选传）+ 密文包 + 加密参数。

    密文包的校验规则直接复用自然人认证那一套（同一套加密约定），但错误类型统一翻成
    ``DeveloperError`` —— 否则路由层要同时 catch 两种异常，很容易漏。
    """
    try:
        assert_no_plaintext_payload(raw_payload if raw_payload is not None else payload)
    except IdentityVerificationError as exc:
        raise DeveloperError(exc.status, exc.message) from exc

    real_name = normalize_real_name(payload.get("real_name"))
    role_title = normalize_role_title(payload.get("role_title"))
    contact_email = normalize_email(payload.get("contact_email"))
    materials = normalize_materials(payload.get("materials"))

    package_cipher = str(payload.get("package_cipher") or "").strip()
    package_digest: str | None = None
    encryption: dict[str, Any] = {}
    if package_cipher:
        try:
            package_cipher = sanitize_package_cipher(package_cipher)
            encryption = sanitize_encryption(payload.get("encryption"))
        except IdentityVerificationError as exc:
            raise DeveloperError(exc.status, exc.message) from exc
        package_digest = str(payload.get("package_digest") or "").strip().lower()
        if not _DIGEST_RE.match(package_digest):
            raise DeveloperError(400, "有密文包时 package_digest 必须是 sha256 十六进制摘要")
        if not materials:
            raise DeveloperError(400, "有密文包时 materials 至少要列一份材料")

    return {
        "real_name": real_name,
        "role_title": role_title,
        "contact_email": contact_email,
        "developer_role": normalize_developer_role(payload.get("role")),
        "materials": materials,
        "package_cipher": package_cipher or None,
        "package_digest": package_digest,
        "encryption": encryption,
        "agreement_version": AGREEMENT_VERSION,
        "agreement_digest": agreement_digest(),
    }


# --------------------------------------------------------------------- 签名


def recover_signer(*, message: str, signature: str) -> str:
    text = (signature or "").strip()
    if not text:
        raise DeveloperError(400, "提交开发者实名需要钱包签名（signature）")
    if len(text) > MAX_SIGNATURE:
        raise DeveloperError(400, "signature 格式不对")
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=text)
    except Exception as exc:  # noqa: BLE001 - 解析失败就是签名不对
        raise DeveloperError(400, f"签名无法解析：{exc}") from exc
    return str(recovered or "").strip().lower()


async def verify_signer(
    db: AsyncSession, *, identity_id: str, message: str, signature: str
) -> str:
    """签名者必须是这个身份在册的钱包之一 —— 否则等于别人替你实名。"""
    signer = recover_signer(message=message, signature=signature)
    wallets = await wallet_lock.allowed_wallets(db, identity_id)
    allowed = {str(w or "").strip().lower() for w in (wallets or set())}
    if not allowed:
        raise DeveloperError(409, "这个身份还没有在册钱包，请先在操作台连接并绑定钱包")
    if signer not in allowed:
        raise DeveloperError(403, "开发者协议签名不是本人钱包签出的")
    return signer


# ------------------------------------------------------------------ 状态机


def assert_can_submit(current_status: str) -> None:
    current = (current_status or "none").strip() or "none"
    if "pending" not in DEVELOPER_TRANSITIONS.get(current, set()):
        raise DeveloperError(409, f"当前状态 {current} 不能提交复核")


def assert_can_decide(current_status: str, decision: str) -> None:
    current = (current_status or "none").strip() or "none"
    if decision not in DEVELOPER_TRANSITIONS.get(current, set()):
        raise DeveloperError(409, f"不能从 {current} 走到 {decision}")


def is_verified(row: Any) -> bool:
    return bool(row is not None and (row.status or "") == "verified")


def mark_verified(row: Any, *, reviewer_identity_id: str, note: str | None) -> None:
    row.status = "verified"
    row.reviewer_identity_id = reviewer_identity_id
    row.review_note = (note or "")[:MAX_NOTE] or None
    row.verified_at = datetime.utcnow()


def mark_rejected(row: Any, *, reviewer_identity_id: str, note: str | None) -> None:
    row.status = "rejected"
    row.reviewer_identity_id = reviewer_identity_id
    row.review_note = (note or "")[:MAX_NOTE] or None
    row.verified_at = None


# ------------------------------------------------------------------ 数据访问


async def get_entity(db: AsyncSession, identity_id: str) -> EntityVerificationModel | None:
    return await db.get(EntityVerificationModel, identity_id)


async def find_by_signer(
    db: AsyncSession, *, identity_id: str, signer_wallet: str
) -> SkillDeveloperModel | None:
    return (
        await db.execute(
            select(SkillDeveloperModel).where(
                SkillDeveloperModel.identity_id == identity_id,
                SkillDeveloperModel.signer_wallet == signer_wallet,
            )
        )
    ).scalars().first()


async def list_by_identity(db: AsyncSession, identity_id: str) -> list[SkillDeveloperModel]:
    rows = await db.execute(
        select(SkillDeveloperModel)
        .where(SkillDeveloperModel.identity_id == identity_id)
        .order_by(SkillDeveloperModel.created_at.asc())
    )
    return list(rows.scalars().all())


async def assert_entity_verified(db: AsyncSession, identity_id: str) -> EntityVerificationModel:
    """开发者实名必须挂在**已经过认证的主体**下，否则等于个人凭空挂靠一家公司。"""
    entity = await get_entity(db, identity_id)
    if entity is None or str(entity.status or "none") != "verified":
        raise DeveloperError(
            409,
            "开发者实名要先有通过认证的主体：请在「身份 → 主体认证」提交并由复核方通过",
        )
    return entity


async def assert_has_verified_developer(
    db: AsyncSession, identity_id: str
) -> SkillDeveloperModel | None:
    """「这个身份有没有至少一个已通过复核的开发者」。

    用在**生成待签声明**这一步：那一步还不知道最后会用哪个钱包签名，所以只做这一层
    粗筛（早失败，免得用户白签一次）；真正精确到钱包的判定在 ``assert_can_publish``。
    """
    if not bool(getattr(settings, "skill_require_developer_verification", True)):
        return None
    rows = await list_by_identity(db, identity_id)
    for row in rows:
        if is_verified(row):
            return row
    if rows:
        raise DeveloperError(
            409,
            "开发者实名还没有通过复核（当前状态：" + str(rows[0].status or "none") + "）",
        )
    raise DeveloperError(
        409,
        "上架技能需要先完成开发者实名：请在「身份 → 开发者实名」填真实姓名、职务，"
        "签署开发者协议并由复核方通过",
    )


async def assert_can_publish(
    db: AsyncSession, identity_id: str, *, signer_wallet: str | None
) -> SkillDeveloperModel | None:
    """上架前的最后一道门：签名人必须有已通过复核的开发者实名档案。

    ``SKILL_REQUIRE_DEVELOPER_VERIFICATION=false`` 时这道门关闭（只留主体认证），
    返回 ``None`` 表示这一版不强制。
    """
    if not bool(getattr(settings, "skill_require_developer_verification", True)):
        return None

    wallet = str(signer_wallet or "").strip().lower()
    rows = await list_by_identity(db, identity_id)
    if not rows:
        raise DeveloperError(
            409,
            "上架技能需要先完成开发者实名：请在「身份 → 开发者实名」填真实姓名、职务，"
            "签署开发者协议并由复核方通过",
        )
    if not wallet:
        raise DeveloperError(403, "上架签名没有解析出钱包地址，无法核对开发者实名")
    for row in rows:
        if str(row.signer_wallet or "").strip().lower() == wallet and is_verified(row):
            return row
    pending = [r for r in rows if str(r.status or "") in ("pending", "rejected", "none")]
    if pending:
        raise DeveloperError(
            409,
            "这个钱包的开发者实名还没有通过复核（当前状态："
            + str(pending[0].status or "none")
            + "）；复核通过后即可上架",
        )
    raise DeveloperError(
        403,
        "上架签名必须用签过开发者协议的那个钱包 —— 请用本人钱包重新签署开发者协议，"
        "或改用已通过实名的钱包上架",
    )


# -------------------------------------------------------------------- 视图


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def empty_view(identity_id: str) -> dict[str, Any]:
    return {
        "identity_id": identity_id,
        "developers": [],
        "count": 0,
        "agreement_version": AGREEMENT_VERSION,
        "agreement_digest": agreement_digest(),
        "agreement_text": agreement_text(),
    }


def owner_view(row: Any) -> dict[str, Any]:
    cipher = row.package_cipher or ""
    return {
        "developer_id": row.developer_id,
        "identity_id": row.identity_id,
        "legal_name": row.legal_name or None,
        "real_name": row.real_name or None,
        "role_title": row.role_title or None,
        "contact_email": row.contact_email or None,
        "developer_role": getattr(row, "developer_role", None) or "developer",
        "status": row.status,
        "agreement_version": row.agreement_version,
        "agreement_digest": row.agreement_digest,
        "signer_wallet": row.signer_wallet,
        "signature": row.signature,
        "materials": row.materials or [],
        "package_digest": row.package_digest,
        "package_bytes": len(cipher),
        "has_package": bool(cipher),
        "encryption": row.encryption or {},
        "reviewer_identity_id": row.reviewer_identity_id,
        "review_note": row.review_note,
        "verified_at": _iso(row.verified_at),
        "submitted_at": _iso(row.submitted_at),
        "updated_at": _iso(row.updated_at),
    }


def public_view(row: Any) -> dict[str, Any]:
    """对外只给「这个人是谁、签没签协议、谁复核的」，邮箱与密文一概不出。"""
    return {
        "developer_id": row.developer_id,
        "identity_id": row.identity_id,
        "legal_name": row.legal_name or None,
        "real_name": row.real_name or None,
        "role_title": row.role_title or None,
        "developer_role": getattr(row, "developer_role", None) or "developer",
        "status": row.status,
        "agreement_version": row.agreement_version,
        "agreement_digest": row.agreement_digest,
        "signer_wallet": row.signer_wallet,
        "verified_at": _iso(row.verified_at),
    }


__all__ = [
    "AGREEMENT_TERMS",
    "AGREEMENT_VERSION",
    "DEVELOPER_ROLES",
    "DEVELOPER_STATUSES",
    "DEVELOPER_TRANSITIONS",
    "DeveloperError",
    "SIGNUP_MESSAGE_PREFIX",
    "agreement_digest",
    "agreement_text",
    "assert_can_decide",
    "assert_can_publish",
    "assert_can_submit",
    "assert_entity_verified",
    "assert_has_verified_developer",
    "build_signup_message",
    "build_submission",
    "empty_view",
    "find_by_signer",
    "get_entity",
    "is_verified",
    "list_by_identity",
    "mark_rejected",
    "mark_verified",
    "normalize_email",
    "normalize_materials",
    "normalize_real_name",
    "normalize_role_title",
    "owner_view",
    "public_view",
    "recover_signer",
    "verify_signer",
]