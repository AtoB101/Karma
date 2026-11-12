"""技能开发者实名：字段校验、协议摘要、签名、状态机、上架门（纯逻辑，不碰 DB）。"""
from __future__ import annotations

import base64
import hashlib

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from services import developer_registry as reg

ACCOUNT = Account.create()
KEY = ACCOUNT.key.hex()
WALLET = ACCOUNT.address.lower()


def _sign(message: str) -> str:
    return Account.sign_message(encode_defunct(text=message), private_key=KEY).signature.hex()


def _payload(**over) -> dict:
    body = {
        "real_name": "张三",
        "role_title": "数据平台负责人",
        "contact_email": "zhangsan@example.com",
        "role": "api_owner",
    }
    body.update(over)
    return body


# ------------------------------------------------------------------ 字段校验


def test_real_name_must_be_a_real_name():
    assert reg.normalize_real_name("  张三  ") == "张三"
    with pytest.raises(reg.DeveloperError) as e:
        reg.normalize_real_name("张")
    assert e.value.status == 400
    with pytest.raises(reg.DeveloperError):
        reg.normalize_real_name("张\x00三")


def test_role_title_and_email():
    assert reg.normalize_role_title(" API 负责人 ") == "API 负责人"
    assert reg.normalize_email("ops@example.com") == "ops@example.com"
    for bad in ("ops", "ops@", "@example.com", "ops@example", "a b@example.com"):
        with pytest.raises(reg.DeveloperError):
            reg.normalize_email(bad)


def test_materials_only_keep_name_and_digest():
    digest = "a" * 64
    out = reg.normalize_materials([{"kind": "WORK_BADGE", "name": "工牌", "digest": digest}])
    assert out == [{"kind": "WORK_BADGE", "name": "工牌", "digest": digest}]

    with pytest.raises(reg.DeveloperError):
        reg.normalize_materials([{"kind": "NOT_A_KIND", "name": "x", "digest": digest}])
    with pytest.raises(reg.DeveloperError):
        reg.normalize_materials([{"kind": "OTHER", "name": "x", "digest": "deadbeef"}])
    with pytest.raises(reg.DeveloperError):
        reg.normalize_materials([{"kind": "OTHER", "name": "x", "digest": digest}] * 9)


def test_developer_role_whitelist():
    assert reg.normalize_developer_role(None) == "developer"
    assert reg.normalize_developer_role("OPS") == "ops"
    with pytest.raises(reg.DeveloperError):
        reg.normalize_developer_role("superadmin")


# -------------------------------------------------------------------- 协议


def test_agreement_digest_is_the_hash_of_the_agreement_text():
    text = reg.agreement_text()
    assert reg.AGREEMENT_VERSION in text
    assert all(term in text for term in reg.AGREEMENT_TERMS)
    assert reg.agreement_digest() == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert reg.agreement_digest() == reg.agreement_digest()


def test_signup_message_binds_identity_entity_person_and_agreement():
    msg = reg.build_signup_message(
        identity_id="kid_1", legal_name="示例数据科技有限公司", real_name="张三", role_title="CTO"
    )
    assert msg.startswith(reg.SIGNUP_MESSAGE_PREFIX)
    for needle in (
        "identity: kid_1",
        "entity: 示例数据科技有限公司",
        "developer: 张三",
        "role_title: CTO",
        f"agreement_version: {reg.AGREEMENT_VERSION}",
        f"agreement_digest: {reg.agreement_digest()}",
    ):
        assert needle in msg
    # 同一个输入必须得到同一段文本，否则前端签的那一份和服务端算的那一份对不上
    again = reg.build_signup_message(
        identity_id="kid_1", legal_name="示例数据科技有限公司", real_name="张三", role_title="CTO"
    )
    assert msg == again


def test_changing_any_field_changes_the_signed_message():
    base = dict(identity_id="kid_1", legal_name="A 公司", real_name="张三", role_title="CTO")
    msg = reg.build_signup_message(**base)
    assert reg.build_signup_message(**{**base, "real_name": "李四"}) != msg
    assert reg.build_signup_message(**{**base, "legal_name": "B 公司"}) != msg
    assert reg.build_signup_message(**{**base, "identity_id": "kid_2"}) != msg


# -------------------------------------------------------------------- 签名


def test_recover_signer_returns_the_wallet_that_signed():
    msg = reg.build_signup_message(
        identity_id="kid_1", legal_name="A 公司", real_name="张三", role_title="CTO"
    )
    assert reg.recover_signer(message=msg, signature=_sign(msg)) == WALLET


def test_missing_or_broken_signature_is_a_400_not_a_crash():
    msg = "Karma developer signup"
    with pytest.raises(reg.DeveloperError) as e:
        reg.recover_signer(message=msg, signature="")
    assert e.value.status == 400
    with pytest.raises(reg.DeveloperError) as e2:
        reg.recover_signer(message=msg, signature="0x" + "11" * 65)
    assert e2.value.status == 400


def test_signature_over_a_different_message_recovers_a_different_wallet():
    msg = reg.build_signup_message(
        identity_id="kid_1", legal_name="A 公司", real_name="张三", role_title="CTO"
    )
    tampered = msg.replace("developer: 张三", "developer: 李四")
    assert reg.recover_signer(message=tampered, signature=_sign(msg)) != WALLET


# ------------------------------------------------------------------ 提交体


def test_submission_rejects_plaintext_documents():
    with pytest.raises(reg.DeveloperError) as e:
        reg.build_submission(_payload(id_image="data:image/png;base64,AAAA"))
    assert e.value.status == 400
    assert "id_image" in e.value.message


def test_submission_package_requires_digest_and_materials():
    body = _payload(package_cipher="A" * 400, encryption={"algo": "AES-GCM-256"})
    with pytest.raises(reg.DeveloperError):
        reg.build_submission(body)
    body = _payload(
        package_cipher="A" * 400,
        package_digest="b" * 64,
        materials=[{"kind": "WORK_BADGE", "name": "工牌", "digest": "c" * 64}],
        encryption={
            "algo": "AES-GCM-256",
            "kdf": "PBKDF2-SHA256",
            "iterations": 250000,
            "salt_b64": base64.b64encode(b"\x01" * 32).decode("ascii"),
            "iv_b64": base64.b64encode(b"\x02" * 12).decode("ascii"),
            "key_wrap": "wallet-signature-v1",
        },
    )
    out = reg.build_submission(body)
    assert out["package_digest"] == "b" * 64
    assert out["agreement_version"] == reg.AGREEMENT_VERSION


def test_submission_without_materials_is_fine():
    out = reg.build_submission(_payload())
    assert out["materials"] == []
    assert out["package_cipher"] is None
    assert out["real_name"] == "张三"


# ------------------------------------------------------------------ 状态机


def test_state_machine_only_allows_real_transitions():
    reg.assert_can_submit("none")
    reg.assert_can_submit("rejected")
    with pytest.raises(reg.DeveloperError):
        reg.assert_can_submit("pending")
    with pytest.raises(reg.DeveloperError):
        reg.assert_can_submit("verified")

    reg.assert_can_decide("pending", "verified")
    reg.assert_can_decide("pending", "rejected")
    with pytest.raises(reg.DeveloperError):
        reg.assert_can_decide("none", "verified")
    with pytest.raises(reg.DeveloperError):
        reg.assert_can_decide("verified", "rejected")


class _Row:
    def __init__(self, **over):
        self.developer_id = "dev-1"
        self.identity_id = "kid_1"
        self.legal_name = "示例数据科技有限公司"
        self.real_name = "张三"
        self.role_title = "CTO"
        self.contact_email = "zhangsan@example.com"
        self.developer_role = "developer"
        self.status = "pending"
        self.agreement_version = reg.AGREEMENT_VERSION
        self.agreement_digest = reg.agreement_digest()
        self.signer_wallet = WALLET
        self.signature = "0xdead"
        self.materials = []
        self.package_digest = None
        self.package_cipher = None
        self.encryption = {}
        self.reviewer_identity_id = None
        self.review_note = None
        self.verified_at = None
        self.submitted_at = None
        self.updated_at = None
        for k, v in over.items():
            setattr(self, k, v)


def test_mark_verified_and_rejected_keep_the_audit_trail():
    row = _Row()
    reg.mark_verified(row, reviewer_identity_id="ops-1", note="ok")
    assert row.status == "verified"
    assert row.reviewer_identity_id == "ops-1"
    assert row.verified_at is not None
    assert reg.is_verified(row) is True

    reg.mark_rejected(row, reviewer_identity_id="ops-1", note="资料不清" * 500)
    assert row.status == "rejected"
    assert row.verified_at is None
    assert len(row.review_note) == reg.MAX_NOTE
    assert reg.is_verified(row) is False


def test_public_view_never_leaks_the_email_or_the_ciphertext():
    row = _Row(status="verified")
    view = reg.public_view(row)
    assert view["real_name"] == "张三"
    assert view["signer_wallet"] == WALLET
    assert "contact_email" not in view
    assert "package_cipher" not in view
    assert "encryption" not in view


def test_owner_view_exposes_state_but_not_the_ciphertext_body():
    row = _Row(package_cipher="A" * 128)
    view = reg.owner_view(row)
    assert view["has_package"] is True
    assert view["package_bytes"] == 128
    assert "package_cipher" not in view
    assert view["contact_email"] == "zhangsan@example.com"


def test_empty_view_carries_the_agreement_so_the_form_can_render_it():
    view = reg.empty_view("kid_1")
    assert view["identity_id"] == "kid_1"
    assert view["count"] == 0
    assert view["developers"] == []
    assert view["agreement_version"] == reg.AGREEMENT_VERSION
    assert reg.AGREEMENT_TERMS[0] in view["agreement_text"]