"""主体资质认证（数据 API 提供方）。

为什么和自然人认证分开
----------------------
``identity_verifications`` 认证的是**人**（证件 + 扫脸）；数据 API 的调用方与提供方
都是**公司**，尽调要看的是：营业执照、统一社会信用代码、法定代表人、备案、数据来源授权，
以及**这家公司真的控制着它声称的官网**。这些字段、状态机和复核口径都不一样，所以单独一层。

三条红线（与自然人认证同一套约定）
----------------------------------
* 资质原件只存**密文包 + 摘要**：明文在服务层就被拒（``assert_no_plaintext_payload``）；
* 官网控制权不是自报的：发一次性 token，服务端**回读**域名下的
  ``/.well-known/karma-entity-verify.txt`` 才认；
* 回读是服务端发起的出网请求，必须防 SSRF：只允许 https、不跟随跳转、限长，
  且域名解析结果里只要出现内网地址就拒绝。
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import secrets
import socket
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog

from services.identity_verification import (
    IdentityVerificationError,
    assert_no_plaintext_payload,
    sanitize_encryption,
    sanitize_package_cipher,
)

logger = structlog.get_logger(__name__)

SUBJECT_TYPES = ("individual", "business")
ENTITY_STATUSES = ("none", "draft", "pending", "verified", "rejected")

#: 状态机：草稿 → 待审 → 通过 / 驳回；驳回后可以改了重交。
ENTITY_TRANSITIONS: dict[str, set[str]] = {
    "none": {"draft", "pending"},
    "draft": {"pending"},
    "pending": {"verified", "rejected"},
    "verified": set(),
    "rejected": {"draft", "pending"},
}

CERT_KINDS = (
    "BUSINESS_LICENSE",     # 营业执照
    "ICP_FILING",           # ICP / 备案
    "DATA_SOURCE_AUTH",     # 数据来源授权
    "BANK_ACCOUNT_PROOF",   # 对公账户证明
    "OTHER",
)

SERVICE_CATEGORIES = ("data_api", "skill_plugin", "compute", "agent_service", "other")

WEBSITE_PROOF_PATH = "/.well-known/karma-entity-verify.txt"
WEBSITE_PROOF_PREFIX = "karma-entity-verify="
WEBSITE_PROOF_TTL = timedelta(days=7)
WEBSITE_FETCH_TIMEOUT = 8.0
WEBSITE_BODY_MAX_CHARS = 4096

MAX_CERTIFICATIONS = 12
MIN_LEGAL_NAME = 2
MAX_LEGAL_NAME = 200
MAX_SERVICE_SCOPE = 2000

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_REG_NO_RE = re.compile(r"^[0-9A-Z]{8,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]{1,190}\.[A-Za-z]{2,24}$")


class EntityVerificationError(Exception):
    """带 HTTP 状态的领域错误，路由层直接翻译。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def require_digest(name: str, value: str | None) -> str:
    text = (value or "").strip().lower()
    if not _DIGEST_RE.match(text):
        raise EntityVerificationError(400, f"{name} 必须是 sha256 十六进制摘要")
    return text


def normalize_domain(raw: str) -> str:
    """把用户粘的官网地址归一成纯域名；IP / 端口 / 内网名一律拒。"""
    text = (raw or "").strip().lower()
    if not text:
        raise EntityVerificationError(400, "official_domain 必填")
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in text:
        raise EntityVerificationError(400, "official_domain 不允许带用户名密码")
    if ":" in text:
        raise EntityVerificationError(400, "official_domain 只填域名，不要带端口")
    if text.startswith("www."):
        text = text[4:]
    text = text.rstrip(".")
    if not text:
        raise EntityVerificationError(400, "official_domain 必填")
    if text in ("localhost",) or text.endswith(".local") or text.endswith(".internal"):
        raise EntityVerificationError(400, "official_domain 不能是内网域名")
    try:
        ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        raise EntityVerificationError(400, "official_domain 要填域名，不能填 IP")
    if not _DOMAIN_RE.match(text):
        raise EntityVerificationError(400, f"official_domain 格式不对：{text}")
    return text


def sanitize_entity_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    """校验并归一化主体信息。字段缺失就说清楚缺哪个，别让用户猜。"""
    data = payload or {}
    subject = str(data.get("subject_type") or "business").strip().lower()
    if subject not in SUBJECT_TYPES:
        raise EntityVerificationError(400, f"subject_type 必须是 {' / '.join(SUBJECT_TYPES)}")

    legal_name = str(data.get("legal_name") or "").strip()
    if len(legal_name) < MIN_LEGAL_NAME:
        raise EntityVerificationError(400, "legal_name（主体全称）必填")
    legal_name = legal_name[:MAX_LEGAL_NAME]

    registration_no = str(data.get("registration_no") or "").strip().upper()
    if subject == "business":
        if not _REG_NO_RE.match(registration_no):
            raise EntityVerificationError(
                400, "registration_no（统一社会信用代码 / 注册号）必须是 8-32 位大写字母或数字"
            )

    legal_rep = str(data.get("legal_rep") or "").strip()[:120]
    if subject == "business" and len(legal_rep) < MIN_LEGAL_NAME:
        raise EntityVerificationError(400, "legal_rep（法定代表人）必填")

    official_domain = normalize_domain(str(data.get("official_domain") or ""))

    contact_email = str(data.get("contact_email") or "").strip().lower()[:200]
    if not _EMAIL_RE.match(contact_email):
        raise EntityVerificationError(400, "contact_email 格式不对")

    service_category = str(data.get("service_category") or "data_api").strip().lower()[:64]
    if service_category not in SERVICE_CATEGORIES:
        raise EntityVerificationError(400, f"service_category 必须是 {' / '.join(SERVICE_CATEGORIES)}")

    service_scope = str(data.get("service_scope") or "").strip()[:MAX_SERVICE_SCOPE]
    if len(service_scope) < 10:
        raise EntityVerificationError(400, "service_scope 请写清楚服务范围（数据来源 / 接口类型 / 更新频率）")

    return {
        "subject_type": subject,
        "legal_name": legal_name,
        "registration_no": registration_no[:64],
        "jurisdiction": str(data.get("jurisdiction") or "").strip()[:64],
        "legal_rep": legal_rep,
        "official_domain": official_domain,
        "contact_email": contact_email,
        "service_category": service_category,
        "service_scope": service_scope,
    }


def sanitize_certifications(items: Any, *, subject_type: str) -> list[dict[str, str]]:
    """资质清单：只留「是什么 + 叫什么 + 摘要」，原件在密文包里。"""
    if not isinstance(items, list) or not items:
        raise EntityVerificationError(400, "certifications 至少上传一份资质")
    if len(items) > MAX_CERTIFICATIONS:
        raise EntityVerificationError(400, f"certifications 最多 {MAX_CERTIFICATIONS} 份")
    out: list[dict[str, str]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise EntityVerificationError(400, f"certifications[{idx}] 必须是对象")
        kind = str(item.get("kind") or "OTHER").strip().upper()
        if kind not in CERT_KINDS:
            raise EntityVerificationError(400, f"certifications[{idx}].kind 必须是 {' / '.join(CERT_KINDS)}")
        out.append(
            {
                "kind": kind,
                "name": str(item.get("name") or "").strip()[:120],
                "digest": require_digest(f"certifications[{idx}].digest", item.get("digest")),
            }
        )
    if subject_type == "business" and not any(c["kind"] == "BUSINESS_LICENSE" for c in out):
        raise EntityVerificationError(400, "企业主体必须上传营业执照（BUSINESS_LICENSE）")
    return out


def sanitize_extracted_fields(extracted: dict[str, Any] | None) -> dict[str, Any]:
    """脱敏展示字段白名单。原件永远不进来，这里只放「看得见的结论」。"""
    if not extracted:
        return {}
    if not isinstance(extracted, dict):
        raise EntityVerificationError(400, "extracted 必须是对象")
    if not extracted.get("consent"):
        raise EntityVerificationError(400, "提交主体认证需要勾选授权（consent）")
    out: dict[str, Any] = {"consent": True}
    for key, limit in (
        ("legal_name", 200),
        ("registration_no_mask", 32),
        ("legal_rep", 120),
        ("official_domain", 255),
        ("register_capital", 64),
        ("established_on", 32),
        # 商业注册流程要落下来的「看得见的结论」：办公地点、对外 API 入口、企业邮箱。
        ("office_address", 300),
        ("api_endpoint", 300),
        ("api_docs_url", 300),
        ("contact_email", 200),
    ):
        value = extracted.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[key] = text[:limit]
    return out


def build_submission(payload: dict[str, Any], *, raw_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """一份完整的主体提交：主体信息 + 资质清单 + 密文包 + 加密参数。

    密文包的校验规则直接复用自然人认证那一套（同一套加密约定），但错误类型统一
    翻成 ``EntityVerificationError`` —— 否则路由层要同时 catch 两种异常，很容易漏。
    """
    try:
        assert_no_plaintext_payload(raw_payload if raw_payload is not None else payload)
        package_cipher = sanitize_package_cipher(payload.get("package_cipher"))
        encryption = sanitize_encryption(payload.get("encryption"))
    except IdentityVerificationError as exc:
        raise EntityVerificationError(exc.status, exc.message) from exc

    profile = sanitize_entity_profile(payload)
    return {
        **profile,
        "certifications": sanitize_certifications(payload.get("certifications"), subject_type=profile["subject_type"]),
        "doc_digest": require_digest("doc_digest", payload.get("doc_digest")),
        "package_digest": require_digest("package_digest", payload.get("package_digest")),
        "package_cipher": package_cipher,
        "encryption": encryption,
        "extracted": sanitize_extracted_fields(payload.get("extracted")),
    }


# --------------------------------------------------------------- 官网控制权


def issue_website_challenge(domain: str) -> dict[str, str]:
    """一次性 token：用户把它放到官网的固定路径下，我们回读比对。"""
    token = secrets.token_hex(16)
    return {
        "domain": domain,
        "path": WEBSITE_PROOF_PATH,
        "url": f"https://{domain}{WEBSITE_PROOF_PATH}",
        "token": token,
        "expected_line": f"{WEBSITE_PROOF_PREFIX}{token}",
    }


def parse_proof_body(body: str) -> str | None:
    for line in (body or "").splitlines():
        text = line.strip()
        if text.startswith(WEBSITE_PROOF_PREFIX):
            return text[len(WEBSITE_PROOF_PREFIX):].strip()
    return None


async def _assert_public_host(domain: str) -> None:
    """解析域名，出现任何内网地址就拒 —— 否则这个接口就成了打内网的跳板。"""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise EntityVerificationError(400, f"official_domain 解析失败：{exc}") from exc
    addresses = {info[4][0] for info in infos if info[4]}
    if not addresses:
        raise EntityVerificationError(400, "official_domain 解析不到地址")
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise EntityVerificationError(400, f"official_domain 解析出无法识别的地址：{addr}") from None
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise EntityVerificationError(400, "official_domain 指向内网地址，拒绝回读")


async def fetch_website_proof(
    domain: str, *, client: httpx.AsyncClient | None = None, timeout: float = WEBSITE_FETCH_TIMEOUT
) -> str:
    """回读官网校验文件：只允许 https、不跟随跳转、限长。"""
    await _assert_public_host(domain)
    url = f"https://{domain}{WEBSITE_PROOF_PATH}"
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        response = await client.get(url)
    except Exception as exc:  # 网络失败要如实回话，不能让用户以为 DNS 配好了
        raise EntityVerificationError(400, f"回读 {url} 失败：{exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code != 200:
        raise EntityVerificationError(
            400, f"官网校验文件返回 HTTP {response.status_code}（需要 200 的纯文本）"
        )
    return (response.text or "")[:WEBSITE_BODY_MAX_CHARS]


def assert_website_token(token: str | None, expected: str | None, *, challenged_at: datetime | None) -> None:
    if not expected or not token:
        raise EntityVerificationError(409, "还没有生成官网校验 token，请先点「生成校验文件」")
    if challenged_at and datetime.utcnow() - challenged_at > WEBSITE_PROOF_TTL:
        raise EntityVerificationError(409, "官网校验 token 已过期（7 天），请重新生成")
    if not secrets.compare_digest(str(token), str(expected)):
        raise EntityVerificationError(400, "官网校验文件里的 token 对不上，请确认文件内容没有多余空格或换行")


def website_digest(domain: str, token: str) -> str:
    return hashlib.sha256(f"{domain}|{token}".encode("utf-8")).hexdigest()


def build_verify_message(*, identity_id: str, domain: str, token: str) -> str:
    """用户可选：自己钱包签一下，证明「这个域名是我在 Karma 的这个身份」。"""
    return "\n".join(
        [
            "Karma Entity Website Proof",
            f"identity_id:{identity_id}",
            f"official_domain:{domain}",
            f"token:{token}",
        ]
    )


# ------------------------------------------------------------------ 状态机


def assert_can_submit(current_status: str) -> None:
    current = (current_status or "none").strip() or "none"
    if "pending" not in ENTITY_TRANSITIONS.get(current, set()):
        raise EntityVerificationError(409, f"当前状态 {current} 不能提交审核")


def assert_can_decide(current_status: str, decision: str) -> None:
    current = (current_status or "none").strip() or "none"
    if decision not in ENTITY_TRANSITIONS.get(current, set()):
        raise EntityVerificationError(409, f"不能从 {current} 走到 {decision}")


def is_verified(row: Any) -> bool:
    return bool(row is not None and (row.status or "") == "verified")


def mark_verified(row: Any, *, reviewer_identity_id: str, note: str | None) -> None:
    row.status = "verified"
    row.reviewer_identity_id = reviewer_identity_id
    row.review_note = (note or "")[:2000] or None
    row.verified_at = datetime.utcnow()


def mark_rejected(row: Any, *, reviewer_identity_id: str, note: str | None) -> None:
    row.status = "rejected"
    row.reviewer_identity_id = reviewer_identity_id
    row.review_note = (note or "")[:2000] or None
    row.verified_at = None


# -------------------------------------------------------------------- 视图


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def empty_view(identity_id: str) -> dict[str, Any]:
    return {
        "identity_id": identity_id,
        "status": "none",
        "subject_type": "business",
        "legal_name": None,
        "registration_no": None,
        "legal_rep": None,
        "official_domain": None,
        "contact_email": None,
        "service_category": None,
        "service_scope": None,
        "certifications": [],
        "website_verified_at": None,
        "verified_at": None,
        "review_note": None,
        "has_package": False,
        "package_bytes": 0,
        "extracted": {},
    }


def owner_view(row: Any) -> dict[str, Any]:
    """本人视图：不回传密文包本体（几 MB），只给长度与摘要。"""
    cipher = row.package_cipher or ""
    return {
        "identity_id": row.identity_id,
        "status": row.status,
        "subject_type": row.subject_type,
        "legal_name": row.legal_name or None,
        "registration_no": row.registration_no or None,
        "jurisdiction": row.jurisdiction or None,
        "legal_rep": row.legal_rep or None,
        "official_domain": row.official_domain or None,
        "contact_email": row.contact_email or None,
        "service_category": row.service_category or None,
        "service_scope": row.service_scope or None,
        "certifications": row.certifications or [],
        "doc_digest": row.doc_digest,
        "package_digest": row.package_digest,
        "package_bytes": len(cipher),
        "has_package": bool(cipher),
        "encryption": row.encryption or {},
        "extracted": row.extracted or {},
        "website_token": row.website_token,
        "website_path": WEBSITE_PROOF_PATH,
        "website_challenge_at": _iso(row.website_challenge_at),
        "website_verified_at": _iso(row.website_verified_at),
        "website_verified": bool(row.website_verified_at),
        "reviewer_identity_id": row.reviewer_identity_id,
        "review_note": row.review_note,
        "verified_at": _iso(row.verified_at),
        "submitted_at": _iso(row.submitted_at),
        "updated_at": _iso(row.updated_at),
    }


def public_view(row: Any) -> dict[str, Any]:
    """对外只暴露工商信息与状态 —— 这是尽调要看的部分，不含密文与联系方式。"""
    return {
        "identity_id": row.identity_id,
        "status": row.status,
        "subject_type": row.subject_type,
        "legal_name": row.legal_name or None,
        "official_domain": row.official_domain or None,
        "service_category": row.service_category or None,
        "certifications": [
            {"kind": c.get("kind"), "name": c.get("name")} for c in (row.certifications or [])
        ],
        "website_verified": bool(row.website_verified_at),
        "website_verified_at": _iso(row.website_verified_at),
        "verified_at": _iso(row.verified_at),
    }


__all__ = [
    "ENTITY_STATUSES",
    "ENTITY_TRANSITIONS",
    "CERT_KINDS",
    "SERVICE_CATEGORIES",
    "SUBJECT_TYPES",
    "EntityVerificationError",
    "assert_can_decide",
    "assert_can_submit",
    "assert_website_token",
    "build_submission",
    "build_verify_message",
    "empty_view",
    "fetch_website_proof",
    "is_verified",
    "issue_website_challenge",
    "mark_rejected",
    "mark_verified",
    "normalize_domain",
    "owner_view",
    "parse_proof_body",
    "public_view",
    "sanitize_certifications",
    "sanitize_entity_profile",
    "website_digest",
]
