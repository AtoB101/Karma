"""刷脸即激活 / 追加身份同人比对（L3-3）的单元测试。

这一层要证明的是**判据本身**站得住，而不是「跑通了」：

* 签名原文的格式（Python 拼一遍、操作台拼一遍，两边必须逐字一致）；
* 活体门槛（照片通道当不了「本人在场」的证据）；
* 模板密文的形状（小尺寸描述子，不是一张照片）；
* 追加身份的四道复核：签名 / 参考模板一致 / 非重放 / 分数过线 —— 任一条不成立都必须拒。
"""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import (
    IdentityFaceTemplateModel,
    IdentityProfileModel,
    IdentityRoleProfile,
    IdentityVerificationModel,
)
from services import face_activation as face


WALLET_KEY = "0x" + "11" * 32
OTHER_KEY = "0x" + "22" * 32
SIGNER = Account.from_key(WALLET_KEY)
OTHER = Account.from_key(OTHER_KEY)

CAPTURE = "a" * 64
TEMPLATE = "b" * 64
CIPHER = "ZmFrZS1jaXBoZXI=" * 12  # 够长、不是 data URL


def _sig(message: str, key: str = WALLET_KEY) -> str:
    return Account.from_key(key).sign_message(encode_defunct(text=message)).signature.hex()


def _liveness(**over) -> dict:
    base = {"angles": 5, "frames": 5, "source": "camera", "challenges": ["center", "left", "right"]}
    base.update(over)
    return base


async def _bind(db: AsyncSession, identity_id: str, wallet: str) -> None:
    row = await db.get(IdentityProfileModel, identity_id)
    if row is None:
        db.add(
            IdentityProfileModel(
                identity_id=identity_id, display_id="Karma-ID-TEST", bound_wallet_address=wallet
            )
        )
    else:
        row.bound_wallet_address = wallet
    await db.flush()


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "face_activation_enabled", True)
    monkeypatch.setattr(settings, "face_activation_min_angles", 3)
    monkeypatch.setattr(settings, "face_consistency_min_score", 0.35)


# ---------------------------------------------------------------------------
# 签名原文
# ---------------------------------------------------------------------------

def test_activation_message_shape_is_frozen():
    """Python 与操作台各拼一遍 —— 格式变了就是两边静默失配，所以钉死在这里。"""
    msg = face.build_face_activation_message(
        identity_id="kid-1", wallet_address=SIGNER.address, capture_digest=CAPTURE, template_digest=TEMPLATE
    )
    assert msg.splitlines() == [
        "Karma Face Activation v1",
        "identity_id:kid-1",
        f"wallet_address:{SIGNER.address}",
        f"capture_digest:{CAPTURE}",
        f"template_digest:{TEMPLATE}",
    ]


def test_consistency_message_shape_is_frozen_and_scores_are_four_decimals():
    msg = face.build_face_consistency_message(
        owner_identity_id="kid-1",
        profile_id="prof-9",
        class_="individual",
        wallet_address=SIGNER.address,
        reference_digest=TEMPLATE,
        capture_digest=CAPTURE,
        score=0.5,
    )
    assert msg.splitlines() == [
        "Karma Face Consistency v1",
        "owner_identity_id:kid-1",
        "profile_id:prof-9",
        "class:individual",
        f"wallet_address:{SIGNER.address}",
        f"reference_digest:{TEMPLATE}",
        f"capture_digest:{CAPTURE}",
        "score:0.5000",
    ]
    # JS 那边 toFixed(4) 出来的也是这个形状。
    assert face.format_score(0.123456) == "0.1235"
    assert face.format_score("nonsense") == "0.0000"


def test_console_side_rebuilds_the_same_messages():
    """操作台那份必须照着 Python 拼，字符串对不上就等于自己签了个无效结论。"""
    from pathlib import Path

    js = (
        Path(__file__).resolve().parents[2] / "apps/console/scripts/cyber-face-vault.js"
    ).read_text(encoding="utf-8")
    for literal in (
        "Karma Face Activation v1",
        "Karma Face Consistency v1",
        "identity_id:",
        "owner_identity_id:",
        "profile_id:",
        "template_digest:",
        "reference_digest:",
        "capture_digest:",
        "score:",
        "toFixed(4)",
    ):
        assert literal in js, f"操作台那边缺 {literal}"


# ---------------------------------------------------------------------------
# 采集证据
# ---------------------------------------------------------------------------

def test_liveness_keeps_only_the_whitelisted_fields():
    evidence = face.sanitize_liveness(_liveness(face_frames=["raw"], image="data:image/jpeg;base64,AA"))
    assert set(evidence) == {"angles", "frames", "source", "challenges", "motion"}
    # 夹带的人脸字段被丢掉，不是被存下来。
    assert "face_frames" not in evidence and "image" not in evidence


def test_liveness_rejects_unknown_source_and_bad_shapes():
    with pytest.raises(face.FaceError):
        face.sanitize_liveness(_liveness(source="guess"))
    with pytest.raises(face.FaceError):
        face.sanitize_liveness({"source": "camera"})
    with pytest.raises(face.FaceError):
        face.sanitize_liveness(_liveness(angles=99))
    with pytest.raises(face.FaceError):
        face.sanitize_liveness(None)


def test_photo_channel_cannot_prove_the_person_is_present():
    with pytest.raises(face.FaceError) as err:
        face.assert_liveness_minimum(face.sanitize_liveness(_liveness(source="photo")))
    assert err.value.status == 422


def test_angles_below_the_floor_are_refused():
    with pytest.raises(face.FaceError) as err:
        face.assert_liveness_minimum(face.sanitize_liveness(_liveness(angles=2)))
    assert err.value.status == 422
    face.assert_liveness_minimum(face.sanitize_liveness(_liveness(angles=3)))


def test_template_cipher_must_be_a_small_ciphertext():
    with pytest.raises(face.FaceError):
        face.sanitize_template_cipher("short")
    with pytest.raises(face.FaceError) as err:
        face.sanitize_template_cipher("data:image/jpeg;base64," + "A" * 4000)
    assert err.value.status == 400
    with pytest.raises(face.FaceError) as err:
        face.sanitize_template_cipher("A" * (face.MAX_TEMPLATE_CHARS + 10))
    assert err.value.status == 400
    assert face.sanitize_template_cipher(CIPHER) == CIPHER


# ---------------------------------------------------------------------------
# 主身份：刷脸即激活
# ---------------------------------------------------------------------------

async def _activate(db, identity_id="kid-face", **over):
    params = dict(
        identity_id=identity_id,
        wallet_address=SIGNER.address,
        capture_digest=CAPTURE,
        template_cipher=CIPHER,
        template_digest=TEMPLATE,
        algorithm="KFC-GRAY32-NCC-v1",
        encryption={
            "algo": "AES-GCM-256",
            "kdf": "PBKDF2-SHA256",
            "iterations": 200_000,
            "salt_b64": "c2FsdHNhbHRzYWx0c2FsdA==",
            "iv_b64": "aXZpdml2aXZpdg==",
            "key_wrap": "wallet-signature-v1",
        },
        liveness=_liveness(),
    )
    params.update(over)
    message = face.build_face_activation_message(
        identity_id=identity_id,
        wallet_address=params["wallet_address"],
        capture_digest=params["capture_digest"],
        template_digest=params["template_digest"],
    )
    params.setdefault("wallet_signature", _sig(message, over.get("_key", WALLET_KEY)))
    params.pop("_key", None)
    return await face.activate_by_face(db, **params)


async def test_face_scan_activates_the_identity_without_a_review_queue(db_session):
    await _bind(db_session, "kid-face", SIGNER.address)
    payload = await _activate(db_session)

    assert payload["activated"] is True and payload["status"] == "verified"
    assert payload["reviewer_identity_id"] == face.FACE_REVIEWER
    row = await db_session.get(IdentityVerificationModel, "kid-face")
    assert row.status == "verified" and row.verified_at is not None
    # 证件没提交 —— 这条路不碰证件；摘要留的是刷脸那一次的。
    assert row.doc_digest is None and row.face_digest == CAPTURE
    # 审计里看得出「这是平台按活体判的」，不是人工复核。
    events = [e["event"] for e in (row.provider or {}).get("events", [])]
    assert "face_activation" in events

    template = await db_session.get(IdentityFaceTemplateModel, "kid-face")
    assert template.template_digest == TEMPLATE and template.capture_digest == CAPTURE
    assert template.liveness["angles"] == 5


async def test_activation_refuses_a_wallet_that_is_not_the_bound_one(db_session):
    await _bind(db_session, "kid-face2", SIGNER.address)
    message = face.build_face_activation_message(
        identity_id="kid-face2",
        wallet_address=OTHER.address,
        capture_digest=CAPTURE,
        template_digest=TEMPLATE,
    )
    with pytest.raises(face.FaceError) as err:
        await _activate(
            db_session,
            identity_id="kid-face2",
            wallet_address=OTHER.address,
            wallet_signature=_sig(message, OTHER_KEY),
        )
    assert err.value.status == 403
    assert "not the wallet bound" in err.value.message


async def test_activation_refuses_a_tampered_signature(db_session):
    await _bind(db_session, "kid-face3", SIGNER.address)
    with pytest.raises(face.FaceError) as err:
        await _activate(db_session, identity_id="kid-face3", wallet_signature="00" * 65)
    assert err.value.status == 401


async def test_activation_refuses_a_photo(db_session):
    await _bind(db_session, "kid-face4", SIGNER.address)
    with pytest.raises(face.FaceError) as err:
        await _activate(db_session, identity_id="kid-face4", liveness=_liveness(source="photo"))
    assert err.value.status == 422


async def test_activation_can_be_switched_off_for_a_node(db_session, monkeypatch):
    monkeypatch.setattr(settings, "face_activation_enabled", False)
    with pytest.raises(face.FaceError) as err:
        await _activate(db_session, identity_id="kid-face5")
    assert err.value.status == 409


async def test_template_view_only_says_enrolled_after_a_real_scan(db_session):
    empty = await face.template_view(db_session, "kid-nobody")
    assert empty["enrolled"] is False and empty["template_cipher"] is None
    await _bind(db_session, "kid-face6", SIGNER.address)
    await _activate(db_session, identity_id="kid-face6")
    view = await face.template_view(db_session, "kid-face6")
    assert view["enrolled"] is True and view["template_cipher"] == CIPHER


# ---------------------------------------------------------------------------
# 追加身份：同人比对
# ---------------------------------------------------------------------------

async def _enrolled_identity(db, identity_id="kid-owner"):
    await _bind(db, identity_id, SIGNER.address)
    await _activate(db, identity_id=identity_id)
    return identity_id


async def _profile(db, identity_id, class_="individual", profile_id="prof-1"):
    row = IdentityRoleProfile(
        profile_id=profile_id, owner_identity_id=identity_id, class_=class_, kyc_status="none"
    )
    db.add(row)
    await db.flush()
    return row


async def _consistent(db, *, identity_id="kid-owner", profile_id="prof-1", class_="individual", score=0.62, capture="c" * 64, reference=TEMPLATE, key=WALLET_KEY):
    message = face.build_face_consistency_message(
        owner_identity_id=identity_id,
        profile_id=profile_id,
        class_=class_,
        wallet_address=SIGNER.address,
        reference_digest=reference,
        capture_digest=capture,
        score=score,
    )
    return await face.assert_same_person(
        db,
        owner_identity_id=identity_id,
        profile_id=profile_id,
        class_=class_,
        wallet_address=SIGNER.address,
        wallet_signature=_sig(message, key),
        reference_digest=reference,
        capture_digest=capture,
        score=score,
        liveness=_liveness(),
        encryption={
            "algo": "AES-GCM-256",
            "kdf": "PBKDF2-SHA256",
            "iterations": 200_000,
            "salt_b64": "c2FsdHNhbHRzYWx0c2FsdA==",
            "iv_b64": "aXZpdml2aXZpdg==",
            "key_wrap": "wallet-signature-v1",
        },
    )


async def test_same_person_passes_and_reports_the_evidence(db_session):
    await _enrolled_identity(db_session)
    await _profile(db_session, "kid-owner")
    verdict = await _consistent(db_session)
    assert verdict["reviewer"] == face.CONSISTENCY_REVIEWER
    assert verdict["score"] == pytest.approx(0.62)
    assert verdict["reference_digest"] == TEMPLATE


async def test_more_identities_need_a_face_template_first(db_session):
    await _bind(db_session, "kid-fresh", SIGNER.address)
    await _profile(db_session, "kid-fresh")
    with pytest.raises(face.FaceError) as err:
        await _consistent(db_session, identity_id="kid-fresh")
    assert err.value.status == 409
    assert "no face template" in err.value.message


async def test_a_different_reference_template_is_refused(db_session):
    """换了参考模板 = 换了个人（或者有人想拿别人的模板过闸）。"""
    await _enrolled_identity(db_session)
    await _profile(db_session, "kid-owner")
    with pytest.raises(face.FaceError) as err:
        await _consistent(db_session, reference="d" * 64)
    assert err.value.status == 409
    assert "does not match" in err.value.message


async def test_replaying_the_enrollment_capture_is_refused(db_session):
    await _enrolled_identity(db_session)
    await _profile(db_session, "kid-owner")
    with pytest.raises(face.FaceError) as err:
        await _consistent(db_session, capture=CAPTURE)
    assert err.value.status == 409
    assert "replay" in err.value.message


async def test_a_face_below_the_threshold_is_refused(db_session):
    await _enrolled_identity(db_session)
    await _profile(db_session, "kid-owner")
    with pytest.raises(face.FaceError) as err:
        await _consistent(db_session, score=0.2)
    assert err.value.status == 422
    assert "0.2000" in err.value.message


async def test_another_persons_signature_is_refused(db_session):
    await _enrolled_identity(db_session)
    await _profile(db_session, "kid-owner")
    with pytest.raises(face.FaceError) as err:
        await _consistent(db_session, key=OTHER_KEY)
    assert err.value.status in (401, 403)
