"""
Karma — 刷脸即激活 / 追加身份同人比对。
======================================

它回答两个问题，而且只用**用户自己的设备**来回答：

1. **主身份激活** —— 刷脸一次就够。活体 + 多角度采集在浏览器里做，脸型模板用钱包签名
   派生的密钥加密后连同摘要一起上传；服务端只看得到密文、摘要和采集元数据，
   判定「这是活人、按规矩采的」之后直接把身份置为已激活，不再排队等人工复核。
2. **追加身份（第二张卡）** —— 填完标准字段后再刷一次脸，操作台在本机拿这一次的脸和
   **首次激活时留下的模板**比一个分数出来；分数过线即自动开通，不进复核队列。

判据为什么是这样
----------------
脸型模板是**密文**上传的：服务端解不开，也永远算不出「这张脸是谁」。所以比对只能发生在
用户自己的设备上 —— 本机拿钱包签名派生出的同一把密钥解出模板，和这一次现采的脸比出一个
相似度分数（NCC，见操作台 cyber-face-vault.js）。服务端复核的是四件事：

* 签名：这份结论确实由**这个身份的绑定钱包**签的（换个人签名立刻不成立）；
* 对齐：结论里引用的参考模板摘要**与我库里存的那一份一字不差**（换了模板 = 换了个人）；
* 新鲜：这一次的采集摘要与首次那一次不同（挡住「把老采集重放一遍」）；
* 过线：分数达到 ``FACE_CONSISTENCY_MIN_SCORE``（判严不判宽，宁可让人重采一次）。

边界（写清楚，别让人误以为这里做了生物识别）
--------------------------------------------
本机比对能挡住的是「拿别人的脸来加身份」和「拿旧记录重放」，挡不住一个**已经控制浏览器**
的攻击者伪造分数 —— 那一层由钱包签名（他签不了）和后续的交易风控兜。接了第三方实名 /
活体服务商之后，这条路会自动换成服务商的 1:1 比对，分数由服务商给（见
services/identity_provider）。**两者不冲突：服务商的结论更权威，本机结论更便宜。**
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models.orm import IdentityFaceTemplateModel, IdentityVerificationModel
from services.identity_provider.service import record_event
from services.identity_verification import (
    IdentityVerificationError,
    assert_can_submit,
    mark_verified,
    sanitize_encryption,
    sanitize_extracted,
)
from services.identity_wallet_binding import get_bound_wallet
from services.runtime_wallet import verify_personal_message

#: 盖章人写的是「平台判的」，而且写清了判据版本 —— 审计上一眼看得出这不是人工复核。
FACE_REVIEWER = "platform:face-liveness:v1"
CONSISTENCY_REVIEWER = "platform:face-consistency:v1"

#: 模板构造函数版本号。换算法 / 换维度时必须改这个字符串，旧模板才不会拿错尺子比。
TEMPLATE_ALGOS = ("KFC-GRAY32-NCC-v1",)
LIVENESS_SOURCES = ("camera", "photo")
#: 模板密文上限：本机模板是几十 KB 级别的小图，超了说明塞了别的东西。
MAX_TEMPLATE_CHARS = 2_000_000
MIN_TEMPLATE_CHARS = 64
#: 分数保留四位小数 —— 签名原文里用它，Python 与 JS 两边都按四位格式化，避免两边对不上。
SCORE_DECIMALS = 4
#: 采集元数据里的数字字段上下限（挡脏数据，不是业务判断）。
MAX_ANGLES = 12
MAX_FRAMES = 64


class FaceError(Exception):
    """带 HTTP 状态的刷脸域错误，路由层直接翻译成响应。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# 签名原文：Python / JS 各拼一次会静默失配，所以两个构造函数都放这里，JS 侧照抄一份，
# 单元测试逐字比对（见 tests/unit/test_face_activation.py）。
# ---------------------------------------------------------------------------

def build_face_activation_message(
    *, identity_id: str, wallet_address: str, capture_digest: str, template_digest: str
) -> str:
    return "\n".join(
        [
            "Karma Face Activation v1",
            f"identity_id:{identity_id}",
            f"wallet_address:{wallet_address}",
            f"capture_digest:{capture_digest}",
            f"template_digest:{template_digest}",
        ]
    )


def build_face_consistency_message(
    *,
    owner_identity_id: str,
    profile_id: str,
    class_: str,
    wallet_address: str,
    reference_digest: str,
    capture_digest: str,
    score: float,
) -> str:
    return "\n".join(
        [
            "Karma Face Consistency v1",
            f"owner_identity_id:{owner_identity_id}",
            f"profile_id:{profile_id}",
            f"class:{class_}",
            f"wallet_address:{wallet_address}",
            f"reference_digest:{reference_digest}",
            f"capture_digest:{capture_digest}",
            f"score:{format_score(score)}",
        ]
    )


def format_score(score: Any) -> str:
    """分数在签名原文里的形状：固定四位小数。非数字一律按 0 处理（随后会被判不达标）。"""
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    return f"{value:.{SCORE_DECIMALS}f}"


# ---------------------------------------------------------------------------
# 校验层
# ---------------------------------------------------------------------------

def _digest(value: str | None, *, name: str) -> str:
    text = (value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise FaceError(400, f"{name} must be a lowercase sha256 hex digest")
    return text


def sanitize_liveness(raw: dict[str, Any] | None) -> dict[str, Any]:
    """采集元数据只留白名单字段：角度数、帧数、活体动作、来源。

    **不收人脸数据**：角度 / 动作名是流程证据，不是生物特征。
    """
    if not isinstance(raw, dict):
        raise FaceError(400, "liveness evidence is required")
    angles = raw.get("angles")
    try:
        angles = int(angles)
    except (TypeError, ValueError) as exc:
        raise FaceError(400, "liveness.angles must be an integer") from exc
    if angles < 0 or angles > MAX_ANGLES:
        raise FaceError(400, f"liveness.angles must be between 0 and {MAX_ANGLES}")
    frames = raw.get("frames", 0)
    try:
        frames = int(frames)
    except (TypeError, ValueError) as exc:
        raise FaceError(400, "liveness.frames must be an integer") from exc
    frames = max(0, min(frames, MAX_FRAMES))
    source = str(raw.get("source") or "").strip().lower()
    if source not in LIVENESS_SOURCES:
        raise FaceError(400, f"liveness.source must be one of {', '.join(LIVENESS_SOURCES)}")
    challenges: list[str] = []
    for item in list(raw.get("challenges") or [])[:MAX_ANGLES]:
        text = str(item or "").strip()[:32]
        if text:
            challenges.append(text)
    return {
        "angles": angles,
        "frames": frames,
        "source": source,
        "challenges": challenges,
        "motion": round(float(raw.get("motion") or 0.0), 6),
    }


def assert_liveness_minimum(liveness: dict[str, Any], *, min_angles: int | None = None) -> None:
    """活体的最低标准：**必须来自摄像头**，且采集到足够多的角度。

    照片通道（source=photo）能做题目的补充材料，但当不了「本人在场」的证据 ——
    刷脸激活走的是后者，所以这里直接拒。
    """
    floor = min_angles
    if floor is None:
        floor = int(getattr(get_settings(), "face_activation_min_angles", 3) or 3)
    if liveness.get("source") != "camera":
        raise FaceError(
            422,
            "face activation needs a live camera capture: uploading a photo cannot prove "
            "the person is present",
        )
    if int(liveness.get("angles") or 0) < max(1, floor):
        raise FaceError(
            422,
            f"face activation needs at least {max(1, floor)} captured angles, "
            f"got {int(liveness.get('angles') or 0)}",
        )


def sanitize_template_cipher(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) < MIN_TEMPLATE_CHARS:
        raise FaceError(400, "template_cipher is too short to be an encrypted face template")
    if len(text) > MAX_TEMPLATE_CHARS:
        raise FaceError(
            400,
            f"template_cipher exceeds {MAX_TEMPLATE_CHARS} characters; the template must be a "
            "small fixed-size descriptor, not a photo",
        )
    if text.lower().startswith("data:"):
        raise FaceError(400, "template_cipher must be ciphertext, not a data URL")
    return text


def sanitize_algorithm(value: str | None) -> str:
    text = (value or "").strip()
    if text not in TEMPLATE_ALGOS:
        raise FaceError(400, f"algorithm must be one of {', '.join(TEMPLATE_ALGOS)}")
    return text


def _wallet_of(identity_id: str) -> str:
    return str(identity_id or "").strip().lower()


async def assert_wallet_signature(
    *,
    message: str,
    wallet_address: str,
    wallet_signature: str,
    bound_wallet: str | None,
) -> str:
    """一次签名同时证明两件事：句子是他签的，而且用的是**这个身份绑定的钱包**。"""
    wallet = str(wallet_address or "").strip()
    if not wallet.startswith("0x") or len(wallet) < 10:
        raise FaceError(400, "invalid wallet_address")
    if bound_wallet and _wallet_of(bound_wallet) != wallet.lower():
        raise FaceError(
            403,
            "the signing wallet is not the wallet bound to this identity",
        )
    try:
        verify_personal_message(
            message=message, wallet_address=wallet, wallet_signature=wallet_signature
        )
    except Exception as exc:  # noqa: BLE001 - 底层是各种验签异常，统一翻成 401
        raise FaceError(401, f"wallet signature check failed: {exc}") from exc
    return wallet.lower()


# ---------------------------------------------------------------------------
# 主身份：刷脸即激活
# ---------------------------------------------------------------------------

async def activate_by_face(
    db: AsyncSession,
    *,
    identity_id: str,
    wallet_address: str,
    wallet_signature: str,
    capture_digest: str | None,
    template_cipher: str | None,
    template_digest: str | None,
    algorithm: str | None = None,
    encryption: dict[str, Any] | None = None,
    liveness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """刷脸激活：验签 → 验活体 → 写模板密文 → 走状态机置位 → 记审计。"""
    if not bool(getattr(get_settings(), "face_activation_enabled", True)):
        raise FaceError(
            409,
            "face activation is switched off on this node; submit documents and wait for review",
        )

    capture = _digest(capture_digest, name="capture_digest")
    template_hash = _digest(template_digest, name="template_digest")
    cipher = sanitize_template_cipher(template_cipher)
    algo = sanitize_algorithm(algorithm)
    evidence = sanitize_liveness(liveness)
    assert_liveness_minimum(evidence)

    bound = await get_bound_wallet(db, identity_id)
    wallet = await assert_wallet_signature(
        message=build_face_activation_message(
            identity_id=identity_id,
            wallet_address=wallet_address,
            capture_digest=capture,
            template_digest=template_hash,
        ),
        wallet_address=wallet_address,
        wallet_signature=wallet_signature,
        bound_wallet=bound,
    )

    try:
        enc = sanitize_encryption(encryption)
        extracted = sanitize_extracted(
            {"consent": True, "face_match_hint": f"live-camera-{evidence['angles']}angles"}
        )
    except IdentityVerificationError as exc:
        raise FaceError(exc.status, exc.message) from exc

    row = await db.get(IdentityVerificationModel, identity_id)
    current = row.status if row else "none"
    try:
        assert_can_submit(current)
    except IdentityVerificationError as exc:
        raise FaceError(exc.status, exc.message) from exc

    if row is None:
        row = IdentityVerificationModel(identity_id=identity_id)
        db.add(row)

    row.status = "pending"
    row.doc_digest = None  # 刷脸激活不提交证件；证件留给「更高等级」那条路
    row.face_digest = capture
    row.package_digest = template_hash
    row.package_cipher = cipher
    row.encryption = enc
    row.extracted = extracted
    row.reviewer_identity_id = None
    row.review_note = None
    row.verified_at = None
    row.updated_at = datetime.utcnow()
    # 状态机的第二跳：pending -> verified。和人工复核、服务商回调走的是同一组合法迁移，
    # 只不过盖章人写的是 platform:face-liveness:v1。
    mark_verified(
        row,
        reviewer_identity_id=FACE_REVIEWER,
        note=(
            "刷脸即激活：活体 + "
            f"{evidence['angles']} 个角度采集，模板摘要 {template_hash[:12]}…"
            "（证件未提交；需要更高等级时再补）"
        ),
    )
    record_event(
        row,
        "face_activation",
        applied=True,
        mode="face_liveness",
        angles=evidence["angles"],
        frames=evidence["frames"],
        algorithm=algo,
    )

    template = await db.get(IdentityFaceTemplateModel, identity_id)
    if template is None:
        template = IdentityFaceTemplateModel(identity_id=identity_id)
        db.add(template)
    template.template_cipher = cipher
    template.template_digest = template_hash
    template.algorithm = algo
    template.encryption = enc
    template.liveness = evidence
    template.capture_digest = capture
    template.wallet_address = wallet
    template.level = "face_liveness"
    template.updated_at = datetime.utcnow()

    await db.flush()
    return {
        "identity_id": identity_id,
        "status": row.status,
        "level": row.level,
        "reviewer_identity_id": row.reviewer_identity_id,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "face_digest": capture,
        "template_digest": template_hash,
        "wallet_address": wallet,
        "liveness": evidence,
        "activated": True,
    }


async def template_view(db: AsyncSession, identity_id: str) -> dict[str, Any]:
    """把模板密文交给本人（操作台在本机解密后跟现采的脸比对）。

    密文只回给本人：别人拿到也解不开，但没必要给。
    """
    row = await db.get(IdentityFaceTemplateModel, identity_id)
    if row is None:
        return {
            "identity_id": identity_id,
            "enrolled": False,
            "template_cipher": None,
            "template_digest": None,
            "algorithm": None,
            "encryption": {},
            "liveness": {},
            "created_at": None,
        }
    return {
        "identity_id": identity_id,
        "enrolled": True,
        "template_cipher": row.template_cipher,
        "template_digest": row.template_digest,
        "algorithm": row.algorithm,
        "encryption": row.encryption or {},
        "liveness": row.liveness or {},
        "wallet_address": row.wallet_address,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def assert_same_person(
    db: AsyncSession,
    *,
    owner_identity_id: str,
    profile_id: str,
    class_: str,
    wallet_address: str,
    wallet_signature: str,
    reference_digest: str | None,
    capture_digest: str | None,
    score: Any,
    liveness: dict[str, Any] | None = None,
    encryption: dict[str, Any] | None = None,
    template_cipher: str | None = None,
) -> dict[str, Any]:
    """追加身份的判据。返回判定细节，调用方据此把档案置为已核验。"""
    template = await db.get(IdentityFaceTemplateModel, owner_identity_id)
    if template is None:
        raise FaceError(
            409,
            "this identity has no face template yet: activate the master identity with a face "
            "scan first, then add more identities",
        )

    reference = _digest(reference_digest, name="reference_digest")
    if reference != str(template.template_digest or "").lower():
        raise FaceError(
            409,
            "the reference face template does not match the one on file for this identity",
        )

    capture = _digest(capture_digest, name="capture_digest")
    if template.capture_digest and capture == str(template.capture_digest).lower():
        raise FaceError(409, "this capture is a replay of the enrollment capture")

    evidence = sanitize_liveness(liveness)
    assert_liveness_minimum(evidence)
    try:
        enc = sanitize_encryption(encryption)
    except IdentityVerificationError as exc:
        raise FaceError(exc.status, exc.message) from exc
    # 第二次采集也可以顺手把模板刷新一遍（同一张脸的新样本），但**必须**是本人签的，
    # 所以刷新走同一个签名闸门，不额外开口子。
    cipher = sanitize_template_cipher(template_cipher) if template_cipher else None

    bound = await get_bound_wallet(db, owner_identity_id)
    wallet = await assert_wallet_signature(
        message=build_face_consistency_message(
            owner_identity_id=owner_identity_id,
            profile_id=profile_id,
            class_=class_,
            wallet_address=wallet_address,
            reference_digest=reference,
            capture_digest=capture,
            score=score,
        ),
        wallet_address=wallet_address,
        wallet_signature=wallet_signature,
        bound_wallet=bound,
    )

    threshold = float(getattr(get_settings(), "face_consistency_min_score", 0.35) or 0.0)
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    if value < threshold:
        raise FaceError(
            422,
            f"the fresh face does not match the enrolled template (score {format_score(value)} "
            f"< {format_score(threshold)}); re-capture in better light, or use the provider route",
        )

    if cipher:
        template.template_cipher = cipher
        template.encryption = enc
        template.liveness = evidence
        template.capture_digest = capture
        template.wallet_address = wallet
        template.updated_at = datetime.utcnow()

    return {
        "score": value,
        "threshold": threshold,
        "wallet_address": wallet,
        "reference_digest": reference,
        "capture_digest": capture,
        "liveness": evidence,
        "reviewer": CONSISTENCY_REVIEWER,
        "checked_at": datetime.utcnow().isoformat(),
    }


__all__ = [
    "CONSISTENCY_REVIEWER",
    "FACE_REVIEWER",
    "FaceError",
    "MAX_TEMPLATE_CHARS",
    "SCORE_DECIMALS",
    "TEMPLATE_ALGOS",
    "assert_liveness_minimum",
    "assert_same_person",
    "assert_wallet_signature",
    "activate_by_face",
    "build_face_activation_message",
    "build_face_consistency_message",
    "format_score",
    "sanitize_algorithm",
    "sanitize_liveness",
    "sanitize_template_cipher",
    "template_view",
]
