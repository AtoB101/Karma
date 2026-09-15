"""
Karma — Master identity verification (证件 + 扫脸) 与子身份钱包绑定。

设计红线（不许绕过）：
1. 服务端**永远不接收**证件 / 人脸明文。浏览器端先做 AES-GCM 加密，再上传
   密文包；这里只保存密文、摘要、加密参数与脱敏字段。
2. `extracted` 走白名单，只允许「已脱敏」的展示用字段；任何像原图的字段
   （data URL、base64 图片、image/selfie/photo 类键名）一律 400 拒绝。
3. 状态机 none/rejected → pending → verified|rejected，核验方必须是 verifier
   类档案且不是本人（与 role-profile KYC 同一条规则）。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException

# --- 状态机 -----------------------------------------------------------------

VERIFY_TRANSITIONS: dict[str, set[str]] = {
    "none": {"pending"},
    "pending": {"verified", "rejected"},
    "verified": set(),
    "rejected": {"pending"},
}

VERIFY_STATUSES = ("none", "pending", "verified", "rejected")
VERIFY_LEVELS = ("basic", "full")

DOC_TYPES = ("ID_CARD", "PASSPORT", "DRIVER_LICENSE", "RESIDENCE_PERMIT", "BUSINESS_LICENSE")

# 密文包上限：证件正反面 + 一张自拍，压缩后够用；超了说明没压缩或想塞原图。
MAX_PACKAGE_CHARS = 8_000_000
MIN_PACKAGE_CHARS = 64

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DATA_URL_RE = re.compile(r"^data:(image|video|application)/", re.IGNORECASE)
# 纯 base64 长串：证件 / 资质原件的裸编码。声明字段都有长度上限（最长 2000），
# 所以超过这个长度又整串是 base64 字符集的，只可能是原件本体换了层皮。
_B64_BLOB_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_B64_BLOB_MIN_CHARS = 2048

# 这些键名一旦出现，说明有明文 / 原图想蒙混过关，直接拒。
FORBIDDEN_KEYS = {
    "image", "images", "photo", "photos", "selfie", "face_image", "face_photo",
    "id_front", "id_back", "front_image", "back_image", "document_image",
    "doc_image", "raw", "raw_image", "data_url", "base64", "base64_image",
    "id_image", "证件", "照片", "人脸照片", "证件照", "原图",
}

# extracted 只允许这些展示字段，并且长度封顶。
EXTRACTED_FIELD_MAX = {
    "full_name": 128,
    "doc_type": 64,
    "doc_number_mask": 64,
    "valid_until": 32,
    "issued_by": 128,
    "nationality": 64,
    "birth_year": 8,
    "face_match_hint": 32,
    # 联系方式：商业流程要走完「认下来的人怎么被联系到」，但同样只留展示用的值。
    "contact_email": 200,
    "contact_phone": 40,
}
EXTRACTED_STRING_FIELDS = tuple(EXTRACTED_FIELD_MAX)

ENCRYPTION_ALGOS = ("AES-GCM-256", "AES-GCM-128")
KEY_WRAP_MODES = ("wallet-signature-v1", "operator-passphrase-v1")
MAX_KDF_ITERATIONS = 5_000_000


class IdentityVerificationError(Exception):
    """Domain error carrying an HTTP status for the route layer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _walk_keys(node: Any, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(str(key).strip().lower())
            _walk_keys(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_keys(item, found)
    return found


def _walk_pairs(node: Any):
    """(键, 值) 深走：判定要在整棵树上做，不能只看顶层。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key).strip().lower(), value
            yield from _walk_pairs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_pairs(item)


def _assert_no_plaintext(payload: dict[str, Any]) -> None:
    used = _walk_keys(payload, set())
    bad = sorted(used & FORBIDDEN_KEYS)
    if bad:
        raise IdentityVerificationError(
            400,
            "verification payload must not contain document/face plaintext "
            f"(offending keys: {', '.join(bad)})",
        )

    for key, value in _walk_pairs(payload or {}):
        # 密文包本体当然是长 base64 —— 它是唯一的合法例外。
        if key == "package_cipher":
            continue
        if not isinstance(value, str):
            continue
        text = value.strip()
        if _DATA_URL_RE.match(text):
            raise IdentityVerificationError(
                400,
                f"field '{key}' looks like an inline image/plaintext data URL; "
                "encrypt client-side and send only the ciphertext package",
            )
        # 换层皮不算：键名随便起，只要值是一整块裸 base64，就是原件明文。
        if len(text) >= _B64_BLOB_MIN_CHARS and _B64_BLOB_RE.match(text):
            raise IdentityVerificationError(
                400,
                f"field '{key}' looks like a raw base64 document blob "
                f"({len(text)} chars); encrypt client-side and send only the ciphertext package",
            )


def _require_digest(name: str, value: str | None) -> str:
    text = (value or "").strip().lower()
    if not _DIGEST_RE.match(text):
        raise IdentityVerificationError(400, f"{name} must be a lowercase sha256 hex digest")
    return text


def sanitize_extracted(extracted: dict[str, Any] | None) -> dict[str, Any]:
    """白名单 + 截断。只保留展示用的脱敏字段。"""
    if not extracted:
        return {}
    if not isinstance(extracted, dict):
        raise IdentityVerificationError(400, "extracted must be an object")
    out: dict[str, Any] = {}
    for key in EXTRACTED_STRING_FIELDS:
        if key not in extracted:
            continue
        raw = extracted[key]
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        limit = EXTRACTED_FIELD_MAX[key]
        out[key] = text[:limit]
    if isinstance(extracted.get("consent"), bool):
        out["consent"] = bool(extracted["consent"])
    if not out.get("consent"):
        raise IdentityVerificationError(400, "user consent is required to submit identity verification")
    if out.get("doc_type") and out["doc_type"] not in DOC_TYPES:
        out["doc_type"] = out["doc_type"][:64]
    return out


def sanitize_encryption(encryption: dict[str, Any] | None) -> dict[str, Any]:
    if not encryption or not isinstance(encryption, dict):
        raise IdentityVerificationError(400, "encryption parameters are required")

    algo = str(encryption.get("algo") or "").strip()
    if algo not in ENCRYPTION_ALGOS:
        raise IdentityVerificationError(400, f"unsupported encryption algo: {algo or '(empty)'}")

    kdf = str(encryption.get("kdf") or "").strip().upper()
    if kdf not in ("PBKDF2-SHA256", "PBKDF2-SHA512"):
        raise IdentityVerificationError(400, "encryption.kdf must be PBKDF2-SHA256 or PBKDF2-SHA512")

    try:
        iterations = int(encryption.get("iterations") or 0)
    except (TypeError, ValueError) as exc:
        raise IdentityVerificationError(400, "encryption.iterations must be an integer") from exc
    if iterations < 100_000 or iterations > MAX_KDF_ITERATIONS:
        raise IdentityVerificationError(
            400, f"encryption.iterations must be between 100000 and {MAX_KDF_ITERATIONS}"
        )

    salt = str(encryption.get("salt_b64") or "").strip()
    iv = str(encryption.get("iv_b64") or "").strip()
    if len(salt) < 16 or len(iv) < 12:
        raise IdentityVerificationError(400, "encryption.salt_b64 / iv_b64 are required")

    key_wrap = str(encryption.get("key_wrap") or "").strip()
    if key_wrap not in KEY_WRAP_MODES:
        raise IdentityVerificationError(
            400, "encryption.key_wrap must be wallet-signature-v1 or operator-passphrase-v1"
        )

    return {
        "algo": algo,
        "kdf": kdf,
        "iterations": iterations,
        "salt_b64": salt[:256],
        "iv_b64": iv[:256],
        "key_wrap": key_wrap,
    }


def sanitize_package_cipher(package_cipher: str | None) -> str:
    text = (package_cipher or "").strip()
    if len(text) < MIN_PACKAGE_CHARS:
        raise IdentityVerificationError(400, "package_cipher is too short to be a ciphertext package")
    if len(text) > MAX_PACKAGE_CHARS:
        raise IdentityVerificationError(
            400,
            f"package_cipher exceeds {MAX_PACKAGE_CHARS} characters; compress the capture "
            "before encrypting",
        )
    if _DATA_URL_RE.match(text):
        raise IdentityVerificationError(400, "package_cipher must be ciphertext, not a data URL")
    return text


def assert_no_plaintext_payload(payload: dict[str, Any] | None) -> None:
    """公开入口：任何「可能装着证件 / 人脸明文」的载荷都要先过这一关。

    子身份 KYC 也用同一条红线，避免有人绕过主身份认证把原图塞进 kyc_payload。
    """
    _assert_no_plaintext(payload or {})


def build_submission(
    *,
    level: str | None,
    doc_digest: str | None,
    face_digest: str | None,
    package_digest: str | None,
    package_cipher: str | None,
    encryption: dict[str, Any] | None,
    extracted: dict[str, Any] | None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验并归一化一份提交。任何明文痕迹都会在这里被拒。"""
    if raw_payload is not None:
        _assert_no_plaintext(raw_payload)

    lvl = (level or "basic").strip().lower()
    if lvl not in VERIFY_LEVELS:
        raise IdentityVerificationError(400, f"level must be one of {', '.join(VERIFY_LEVELS)}")

    return {
        "level": lvl,
        "doc_digest": _require_digest("doc_digest", doc_digest),
        "face_digest": _require_digest("face_digest", face_digest),
        "package_digest": _require_digest("package_digest", package_digest),
        "package_cipher": sanitize_package_cipher(package_cipher),
        "encryption": sanitize_encryption(encryption),
        "extracted": sanitize_extracted(extracted),
    }


def assert_can_submit(current_status: str) -> None:
    current = (current_status or "none").strip() or "none"
    if "pending" not in VERIFY_TRANSITIONS.get(current, set()):
        raise IdentityVerificationError(409, f"cannot submit verification from status {current}")


def assert_can_decide(current_status: str, decision: str) -> None:
    current = (current_status or "none").strip() or "none"
    if decision not in VERIFY_TRANSITIONS.get(current, set()):
        raise IdentityVerificationError(409, f"cannot move verification from {current} to {decision}")


def build_bind_wallet_message(*, profile_id: str, owner_identity_id: str, wallet_address: str) -> str:
    """子身份绑定操作钱包的签名原文（服务端可重现，所以能验签）。"""
    return "\n".join(
        [
            "Karma Sub-Identity Wallet Bind",
            f"profile_id:{profile_id}",
            f"owner_identity_id:{owner_identity_id}",
            f"wallet_address:{wallet_address}",
        ]
    )


def public_view(row: Any) -> dict[str, Any]:
    """给非 owner / verifier 的最小视图：只有状态，没有密文与脱敏字段。"""
    return {
        "identity_id": row.identity_id,
        "status": row.status,
        "level": row.level,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }


def owner_view(row: Any) -> dict[str, Any]:
    """给本人的完整视图。密文包不回传（几 MB），只给长度与摘要。"""
    cipher = row.package_cipher or ""
    return {
        "identity_id": row.identity_id,
        "status": row.status,
        "level": row.level,
        "doc_digest": row.doc_digest,
        "face_digest": row.face_digest,
        "package_digest": row.package_digest,
        "package_bytes": len(cipher),
        "has_package": bool(cipher),
        "encryption": row.encryption or {},
        "extracted": row.extracted or {},
        "reviewer_identity_id": row.reviewer_identity_id,
        "review_note": row.review_note,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def empty_view(identity_id: str) -> dict[str, Any]:
    return {
        "identity_id": identity_id,
        "status": "none",
        "level": "basic",
        "doc_digest": None,
        "face_digest": None,
        "package_digest": None,
        "package_bytes": 0,
        "has_package": False,
        "encryption": {},
        "extracted": {},
        "reviewer_identity_id": None,
        "review_note": None,
        "verified_at": None,
        "created_at": None,
        "updated_at": None,
        "configured": False,
    }


BOOTSTRAP_REVIEWER_ID = "platform:bootstrap"


def assert_can_bootstrap_approve(row: Any, *, reason: str) -> None:
    """平台自举审批的前置校验。

    只给服务器上的运维脚本用（scripts/maintenance/approve_identity_verification.py）：
    平台起步阶段只有一个身份、它是自己唯一的复核岗，路由层那条「不能复核自己」
    会把自己永远锁在 pending。这里放行的是**审批动作**，不是提交动作 —— 证件与
    刷脸仍然必须由本人先在操作台真实提交，且必须写清审批理由。
    """
    if row is None:
        raise IdentityVerificationError(404, "this identity has never submitted a verification")
    if not (reason or "").strip():
        raise IdentityVerificationError(400, "a bootstrap approval must carry an explicit reason")
    if row.status == "verified":
        raise IdentityVerificationError(409, "this verification is already approved")
    if row.status != "pending":
        raise IdentityVerificationError(409, f"cannot approve a verification in status {row.status}")
    if not (row.doc_digest or "").strip() or not (row.face_digest or "").strip():
        raise IdentityVerificationError(
            409, "the submission is missing the document digest or the face digest"
        )


def mark_verified(row: Any, *, reviewer_identity_id: str, note: str | None) -> None:
    row.status = "verified"
    row.reviewer_identity_id = reviewer_identity_id
    row.review_note = (note or "")[:2000] or None
    row.verified_at = datetime.utcnow()


__all__ = [
    "IdentityVerificationError",
    "VERIFY_STATUSES",
    "VERIFY_LEVELS",
    "DOC_TYPES",
    "FORBIDDEN_KEYS",
    "BOOTSTRAP_REVIEWER_ID",
    "assert_can_bootstrap_approve",
    "assert_can_decide",
    "assert_can_submit",
    "assert_no_plaintext_payload",
    "build_bind_wallet_message",
    "build_submission",
    "empty_view",
    "mark_verified",
    "owner_view",
    "public_view",
    "sanitize_extracted",
]
