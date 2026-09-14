"""技能 / 插件登记与上架核验 —— 数据 API 商业化的第一层。

上架一个能被 agent 调用、按次收钱的 endpoint，必须回答三个问题，缺一不可：

1. **谁在卖（主体是谁）** —— 上架前先过 ``entity_verifications``：营业执照 +
   法定代表人 + 官网控制权。这一层认证的是**主体**，与 ``identity_verifications``
   认证的**自然人**（证件 + 扫脸）分开走。
2. **服务落在哪个域名下** —— ``endpoint_url`` 的主机必须落在认证过的
   ``official_domain`` 之下。认证过的官网是这家主体唯一能证明是自己控制的地盘；
   endpoint 挂在别人域名下，等于把收款权押在别人的资产上。
3. **上架这件事是不是本人做的** —— 只有在册钱包（SIWE 证明过、或已绑定的
   子身份钱包）签出的上架声明才作数。签名覆盖 slug / endpoint / 单价 / 阈值 /
   版本 / manifest 摘要，改任何一个字节都会验签失败。所以服务端不需要"审批价格"，
   价格由卖家自己的钱包背书。

服务端不代签、不代发：``publish()`` 只接收签名并核对。密钥始终在用户自己的钱包里，
Karma 这一侧从头到尾拿不到任何私钥。

上架声明（客户端按同样的规则拼串，再让钱包 ``personal_sign``）::

    Karma skill publish
    identity: <identity_id>
    slug: <slug>
    endpoint: <endpoint_url>
    unit_price_usdc: <6 位小数>
    settlement_threshold_usdc: <6 位小数>
    version: <int>
    manifest_digest: <sha256(canonical json)>

``manifest_digest`` 的规范化形式：把 manifest 字典用
``json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`` 序列化后取
sha256 十六进制 —— 与 ``manifest_digest()`` 完全一致，客户端可以自算校验。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import structlog
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import EntityVerificationModel, SkillModel
from services.chain import wallet_lock

logger = structlog.get_logger(__name__)

SKILL_STATUSES = ("draft", "published", "paused", "rejected")
SKILL_CATEGORIES = ("data_api", "skill_plugin", "compute", "agent_service", "other")
SKILL_METHODS = ("GET", "POST")
SKILL_UNITS = ("call", "record", "kb", "token", "hour")

PUBLISH_MESSAGE_PREFIX = "Karma skill publish"

#: slug：3-40 位小写字母 / 数字 / 连字符，首尾必须是字母或数字。
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")

MAX_UNIT_PRICE_USDC = 100.0
MAX_THRESHOLD_USDC = 100_000.0
MAX_CAP_USDC = 1_000_000.0
MIN_NAME = 2
MAX_NAME = 120
MIN_SUMMARY = 8
MAX_SUMMARY = 300
MAX_DESCRIPTION = 4000
MAX_ENDPOINT = 500
MAX_SIGNATURE = 200

EPSILON = 1e-9


class SkillError(Exception):
    """带 HTTP 状态的领域错误，路由层直接翻译。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def format_usdc(value: Any) -> str:
    """签名串里的金额格式：固定 6 位小数，客户端照抄即可复现同一串。"""
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:.6f}"


# --------------------------------------------------------------------- 字段


def normalize_slug(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if not SLUG_RE.match(text):
        raise SkillError(400, "slug 必须是 3-40 位小写字母 / 数字 / 连字符，且首尾是字母或数字")
    return text


def normalize_name(raw: str | None) -> str:
    text = (raw or "").strip()
    if len(text) < MIN_NAME:
        raise SkillError(400, "name（技能名称）必填")
    return text[:MAX_NAME]


def normalize_summary(raw: str | None) -> str:
    text = (raw or "").strip()
    if len(text) < MIN_SUMMARY:
        raise SkillError(400, f"summary 至少 {MIN_SUMMARY} 个字，写清楚这个技能做什么")
    return text[:MAX_SUMMARY]


def normalize_description(raw: str | None) -> str:
    return (raw or "").strip()[:MAX_DESCRIPTION]


def normalize_category(raw: str | None) -> str:
    text = (raw or "data_api").strip().lower()
    if text not in SKILL_CATEGORIES:
        raise SkillError(400, f"category 必须是 {' / '.join(SKILL_CATEGORIES)}")
    return text


def normalize_method(raw: str | None) -> str:
    text = (raw or "POST").strip().upper()
    if text not in SKILL_METHODS:
        raise SkillError(400, f"method 必须是 {' / '.join(SKILL_METHODS)}")
    return text


def normalize_unit(raw: str | None) -> str:
    text = (raw or "call").strip().lower()
    if text not in SKILL_UNITS:
        raise SkillError(400, f"unit 必须是 {' / '.join(SKILL_UNITS)}")
    return text


def normalize_price(raw: Any) -> float:
    try:
        value = round(float(raw), 6)
    except (TypeError, ValueError):
        raise SkillError(400, "unit_price_usdc 必须是数字") from None
    if value < 0:
        raise SkillError(400, "unit_price_usdc 不能为负")
    if value > MAX_UNIT_PRICE_USDC + EPSILON:
        raise SkillError(400, f"unit_price_usdc 单次不能超过 {MAX_UNIT_PRICE_USDC} USDC")
    return value


def normalize_threshold(raw: Any) -> float:
    try:
        value = round(float(raw), 6)
    except (TypeError, ValueError):
        raise SkillError(400, "settlement_threshold_usdc 必须是数字") from None
    if value < 0:
        raise SkillError(400, "settlement_threshold_usdc 不能为负")
    if value > MAX_THRESHOLD_USDC + EPSILON:
        raise SkillError(400, f"settlement_threshold_usdc 不能超过 {MAX_THRESHOLD_USDC} USDC")
    return value


def normalize_cap(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = round(float(raw), 6)
    except (TypeError, ValueError):
        raise SkillError(400, "default_cap_usdc 必须是数字或不填") from None
    if value <= 0:
        raise SkillError(400, "default_cap_usdc 必须大于 0（不填表示不设上限）")
    if value > MAX_CAP_USDC + EPSILON:
        raise SkillError(400, f"default_cap_usdc 不能超过 {MAX_CAP_USDC} USDC")
    return value


def validate_endpoint_under_domain(endpoint_url: str | None, domain: str) -> str:
    """endpoint 必须 https、且主机落在主体认证过的官网域名之下。"""
    text = (endpoint_url or "").strip()
    if not text:
        raise SkillError(400, "endpoint_url 必填")
    if len(text) > MAX_ENDPOINT:
        raise SkillError(400, f"endpoint_url 不能超过 {MAX_ENDPOINT} 个字符")
    parts = urlsplit(text)
    if parts.scheme != "https":
        raise SkillError(400, "endpoint_url 必须是 https://（明文 http 不收）")
    if "@" in (parts.netloc or ""):
        raise SkillError(400, "endpoint_url 不能带用户名密码")
    host = (parts.hostname or "").strip().lower()
    if not host:
        raise SkillError(400, "endpoint_url 缺少主机名")
    if parts.port not in (None, 443):
        raise SkillError(400, "endpoint_url 只能走标准 https 端口（不要带端口号）")
    root = (domain or "").strip().lower()
    if not root:
        raise SkillError(409, "主体认证里还没有官网域名，无法校验 endpoint")
    if host != root and not host.endswith("." + root):
        raise SkillError(
            400,
            f"endpoint_url 的主机 {host} 不在你认证过的官网域名 {root} 之下；"
            "如果你确实要卖别人域名上的服务，请让该域名的主体自己上架",
        )
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"https://{host}{path}{query}"


# --------------------------------------------------------------- manifest


def build_manifest(payload: dict[str, Any], *, version: int) -> dict[str, Any]:
    """上架内容的规范化清单 —— 摘要与签名都基于它。"""
    return {
        "slug": payload["slug"],
        "name": payload["name"],
        "category": payload["category"],
        "summary": payload["summary"],
        "description": payload["description"],
        "endpoint_url": payload["endpoint_url"],
        "method": payload["method"],
        "unit": payload["unit"],
        "unit_price_usdc": format_usdc(payload["unit_price_usdc"]),
        "settlement_threshold_usdc": format_usdc(payload["settlement_threshold_usdc"]),
        "default_cap_usdc": (
            format_usdc(payload["default_cap_usdc"]) if payload["default_cap_usdc"] else None
        ),
        "version": int(version),
    }


def manifest_digest(manifest: dict[str, Any]) -> str:
    body = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_publish_message(
    *,
    identity_id: str,
    manifest: dict[str, Any],
    digest: str,
) -> str:
    return "\n".join(
        [
            PUBLISH_MESSAGE_PREFIX,
            f"identity: {identity_id}",
            f"slug: {manifest['slug']}",
            f"endpoint: {manifest['endpoint_url']}",
            f"unit_price_usdc: {manifest['unit_price_usdc']}",
            f"settlement_threshold_usdc: {manifest['settlement_threshold_usdc']}",
            f"version: {int(manifest['version'])}",
            f"manifest_digest: {digest}",
        ]
    )


def recover_publisher(*, message: str, signature: str) -> str:
    text = (signature or "").strip()
    if not text:
        raise SkillError(400, "上架需要钱包签名（publisher_signature）")
    if len(text) > MAX_SIGNATURE:
        raise SkillError(400, "publisher_signature 格式不对")
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=text)
    except Exception as exc:  # noqa: BLE001 - 解析失败就是签名不对
        raise SkillError(400, f"签名无法解析：{exc}") from exc
    return str(recovered or "").strip().lower()


def verify_publisher_signature(*, message: str, signature: str, wallets: set[str]) -> str:
    """签名者必须是这个身份在册的钱包之一 —— 否则等于别人替你上架。"""
    recovered = recover_publisher(message=message, signature=signature)
    allowed = {str(w or "").strip().lower() for w in (wallets or set())}
    if not allowed:
        raise SkillError(409, "这个身份还没有在册钱包，请先在操作台连接并绑定钱包")
    if recovered not in allowed:
        raise SkillError(403, "上架签名不是本人钱包签出的")
    return recovered


# ------------------------------------------------------------------ 状态机


def normalize_payload(payload: dict[str, Any], *, official_domain: str) -> dict[str, Any]:
    return {
        "slug": normalize_slug(payload.get("slug")),
        "name": normalize_name(payload.get("name")),
        "category": normalize_category(payload.get("category")),
        "summary": normalize_summary(payload.get("summary")),
        "description": normalize_description(payload.get("description")),
        "endpoint_url": validate_endpoint_under_domain(payload.get("endpoint_url"), official_domain),
        "method": normalize_method(payload.get("method")),
        "unit": normalize_unit(payload.get("unit")),
        "unit_price_usdc": normalize_price(payload.get("unit_price_usdc")),
        "settlement_threshold_usdc": normalize_threshold(
            payload.get("settlement_threshold_usdc")
        ),
        "default_cap_usdc": normalize_cap(payload.get("default_cap_usdc")),
    }


async def get_entity(db: AsyncSession, identity_id: str) -> EntityVerificationModel | None:
    return await db.get(EntityVerificationModel, identity_id)


async def assert_can_publish(db: AsyncSession, identity_id: str) -> EntityVerificationModel:
    """没有通过主体认证的身份不能上架 —— 这是商业化的门槛，不是可选项。"""
    row = await get_entity(db, identity_id)
    if row is None or str(row.status or "none") != "verified":
        raise SkillError(
            409,
            "上架技能需要先完成主体认证（营业执照 + 法定代表人 + 官网控制权）；"
            "请在操作台「身份 → 主体认证」提交并等待复核",
        )
    if not (row.official_domain or "").strip():
        raise SkillError(409, "主体认证缺少官网域名，请先补齐")
    return row


async def find_by_slug(db: AsyncSession, slug: str) -> SkillModel | None:
    return (
        await db.execute(select(SkillModel).where(SkillModel.slug == slug))
    ).scalars().first()


async def prepare_publish(db: AsyncSession, *, identity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把「待签声明」交给客户端去签。

    规范化 JSON、金额格式、版本号这些一旦前后端各写一遍就迟早会漂移（差一个字节
    验签就失败）。所以由服务端算出 ``message`` 原样返回，客户端只负责让钱包签它，
    顺便也能把内容显示给用户看 —— 签的是什么，用户自己看得见。
    """
    entity = await assert_can_publish(db, identity_id)
    normalized = normalize_payload(payload, official_domain=str(entity.official_domain))

    existing = await find_by_slug(db, normalized["slug"])
    if existing is not None and existing.owner_identity_id != identity_id:
        raise SkillError(409, f"slug {normalized['slug']} 已被其他主体占用")

    version = int(existing.version or 0) + 1 if existing is not None else 1
    manifest = build_manifest(normalized, version=version)
    digest = manifest_digest(manifest)
    return {
        "identity_id": identity_id,
        "verified_domain": str(entity.official_domain),
        "version": version,
        "republish": existing is not None,
        "manifest": manifest,
        "manifest_digest": digest,
        "message": build_publish_message(identity_id=identity_id, manifest=manifest, digest=digest),
    }

async def publish(
    db: AsyncSession,
    *,
    identity_id: str,
    payload: dict[str, Any],
    signature: str,
) -> SkillModel:
    """上架（或重新上架）一个技能：主体已认证 + endpoint 在官网域名下 + 本人钱包签名。"""
    entity = await assert_can_publish(db, identity_id)
    normalized = normalize_payload(payload, official_domain=str(entity.official_domain))

    existing = await find_by_slug(db, normalized["slug"])
    if existing is not None and existing.owner_identity_id != identity_id:
        raise SkillError(409, f"slug {normalized['slug']} 已被其他主体占用")

    version = int(existing.version or 0) + 1 if existing is not None else 1
    manifest = build_manifest(normalized, version=version)
    digest = manifest_digest(manifest)
    message = build_publish_message(identity_id=identity_id, manifest=manifest, digest=digest)

    wallets = await wallet_lock.allowed_wallets(db, identity_id)
    publisher = verify_publisher_signature(message=message, signature=signature, wallets=wallets)

    if existing is None:
        row = SkillModel(owner_identity_id=identity_id, slug=normalized["slug"])
        db.add(row)
    else:
        row = existing
    row.name = normalized["name"]
    row.category = normalized["category"]
    row.summary = normalized["summary"]
    row.description = normalized["description"]
    row.endpoint_url = normalized["endpoint_url"]
    row.method = normalized["method"]
    row.unit = normalized["unit"]
    row.unit_price_usdc = normalized["unit_price_usdc"]
    row.settlement_threshold_usdc = normalized["settlement_threshold_usdc"]
    row.default_cap_usdc = normalized["default_cap_usdc"]
    row.version = version
    row.manifest_digest = digest
    row.publisher_signature = signature.strip()
    row.publisher_wallet = publisher
    row.verified_domain = str(entity.official_domain)
    row.status = "published"
    row.published_at = datetime.utcnow()
    row.paused_at = None
    row.updated_at = datetime.utcnow()

    await db.flush()
    logger.info(
        "skill_published",
        identity_id=identity_id,
        slug=row.slug,
        version=version,
        publisher_wallet=publisher,
        unit_price_usdc=row.unit_price_usdc,
    )
    return row


async def pause(db: AsyncSession, *, identity_id: str, slug: str) -> SkillModel:
    row = await find_by_slug(db, slug)
    if row is None or row.owner_identity_id != identity_id:
        raise SkillError(404, f"技能 {slug} 不存在或不属于这个身份")
    if str(row.status) == "paused":
        return row
    if str(row.status) != "published":
        raise SkillError(409, f"当前状态 {row.status} 不能暂停")
    row.status = "paused"
    row.paused_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    await db.flush()
    logger.info("skill_paused", identity_id=identity_id, slug=row.slug)
    return row


async def resume(db: AsyncSession, *, identity_id: str, slug: str, signature: str | None = None) -> SkillModel:
    row = await find_by_slug(db, slug)
    if row is None or row.owner_identity_id != identity_id:
        raise SkillError(404, f"技能 {slug} 不存在或不属于这个身份")
    if str(row.status) != "paused":
        raise SkillError(409, f"当前状态 {row.status} 不能恢复")
    # 暂停 → 恢复：内容没变，但要让本人重新表态，防止"暂停期间被改"。
    if signature is not None:
        manifest = build_manifest(
            {
                "slug": row.slug,
                "name": row.name,
                "category": row.category,
                "summary": row.summary,
                "description": row.description,
                "endpoint_url": row.endpoint_url,
                "method": row.method,
                "unit": row.unit,
                "unit_price_usdc": row.unit_price_usdc,
                "settlement_threshold_usdc": row.settlement_threshold_usdc,
                "default_cap_usdc": row.default_cap_usdc,
            },
            version=int(row.version or 1),
        )
        digest = manifest_digest(manifest)
        message = build_publish_message(identity_id=identity_id, manifest=manifest, digest=digest)
        wallets = await wallet_lock.allowed_wallets(db, identity_id)
        verify_publisher_signature(message=message, signature=signature, wallets=wallets)
    row.status = "published"
    row.paused_at = None
    row.updated_at = datetime.utcnow()
    await db.flush()
    logger.info("skill_resumed", identity_id=identity_id, slug=row.slug)
    return row


async def list_published(
    db: AsyncSession,
    *,
    category: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SkillModel]:
    stmt = select(SkillModel).where(SkillModel.status == "published")
    if category:
        stmt = stmt.where(SkillModel.category == str(category).strip().lower())
    text = (query or "").strip()
    if text:
        pattern = f"%{text}%"
        stmt = stmt.where(
            or_(
                SkillModel.name.ilike(pattern),
                SkillModel.summary.ilike(pattern),
                SkillModel.slug.ilike(pattern),
            )
        )
    stmt = stmt.order_by(SkillModel.published_at.desc(), SkillModel.slug).limit(
        max(1, min(int(limit), 200))
    ).offset(max(0, int(offset)))
    return list((await db.execute(stmt)).scalars().all())


async def list_by_owner(db: AsyncSession, identity_id: str) -> list[SkillModel]:
    stmt = (
        select(SkillModel)
        .where(SkillModel.owner_identity_id == identity_id)
        .order_by(SkillModel.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


# ------------------------------------------------------------------- 视图


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def skill_view(row: SkillModel, *, owner: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "skill_id": row.skill_id,
        "slug": row.slug,
        "name": row.name,
        "category": row.category,
        "summary": row.summary,
        "description": row.description,
        "endpoint_url": row.endpoint_url,
        "method": row.method,
        "unit": row.unit,
        "unit_price_usdc": float(row.unit_price_usdc or 0.0),
        "settlement_threshold_usdc": float(row.settlement_threshold_usdc or 0.0),
        "default_cap_usdc": (
            float(row.default_cap_usdc) if row.default_cap_usdc is not None else None
        ),
        "version": int(row.version or 1),
        "manifest_digest": row.manifest_digest,
        "verified_domain": row.verified_domain,
        "status": row.status,
        "published_at": _iso(row.published_at),
        "paused_at": _iso(row.paused_at),
    }
    if owner:
        data.update(
            {
                "owner_identity_id": row.owner_identity_id,
                "publisher_wallet": row.publisher_wallet,
                "publisher_signature": row.publisher_signature,
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
            }
        )
    return data


def empty_catalog(*, category: str | None = None) -> dict[str, Any]:
    return {"count": 0, "category": category, "skills": []}


__all__ = [
    "EPSILON",
    "MAX_CAP_USDC",
    "MAX_THRESHOLD_USDC",
    "MAX_UNIT_PRICE_USDC",
    "PUBLISH_MESSAGE_PREFIX",
    "SKILL_CATEGORIES",
    "SKILL_METHODS",
    "SKILL_STATUSES",
    "SKILL_UNITS",
    "SLUG_RE",
    "SkillError",
    "assert_can_publish",
    "build_manifest",
    "build_publish_message",
    "empty_catalog",
    "find_by_slug",
    "format_usdc",
    "get_entity",
    "list_by_owner",
    "list_published",
    "manifest_digest",
    "normalize_cap",
    "normalize_category",
    "normalize_description",
    "normalize_method",
    "normalize_name",
    "normalize_payload",
    "normalize_price",
    "normalize_slug",
    "normalize_summary",
    "normalize_threshold",
    "normalize_unit",
    "pause",
    "prepare_publish",
    "publish",
    "recover_publisher",
    "resume",
    "skill_view",
    "validate_endpoint_under_domain",
    "verify_publisher_signature",
]