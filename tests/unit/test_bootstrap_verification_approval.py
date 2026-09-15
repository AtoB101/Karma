"""平台自举审批（scripts/maintenance/approve_identity_verification.py）的闸门。

这个通道是「只有一个身份、它是自己唯一的复核岗」时的出口，所以它必须比正常复核更严：
没有提交不给批、没交刷脸不给批、没写理由不给批。
"""
from __future__ import annotations

import pytest

from services.identity_verification import (
    BOOTSTRAP_REVIEWER_ID,
    IdentityVerificationError,
    assert_can_bootstrap_approve,
    mark_verified,
)

DIGEST = "a" * 64


class _Row:
    def __init__(self, *, status="pending", doc_digest=DIGEST, face_digest=DIGEST):
        self.status = status
        self.doc_digest = doc_digest
        self.face_digest = face_digest
        self.level = "basic"
        self.reviewer_identity_id = None
        self.review_note = None
        self.verified_at = None


def test_bootstrap_reviewer_id_is_not_an_identity_id():
    # 它必须一眼看出不是某个人，否则以后会有人拿它当身份去鉴权。
    assert BOOTSTRAP_REVIEWER_ID == "platform:bootstrap"


def test_bootstrap_approvess_a_pending_submission_with_a_reason():
    row = _Row()
    assert_can_bootstrap_approve(row, reason="平台自举：本人提交已核对")
    mark_verified(row, reviewer_identity_id=BOOTSTRAP_REVIEWER_ID, note="平台自举：本人提交已核对")
    assert row.status == "verified"
    assert row.reviewer_identity_id == BOOTSTRAP_REVIEWER_ID
    assert row.verified_at is not None


def test_bootstrap_refuses_when_nobody_submitted():
    with pytest.raises(IdentityVerificationError) as e:
        assert_can_bootstrap_approve(None, reason="随便写点")
    assert e.value.status == 404


def test_bootstrap_refuses_without_a_reason():
    with pytest.raises(IdentityVerificationError) as e:
        assert_can_bootstrap_approve(_Row(), reason="   ")
    assert e.value.status == 400


def test_bootstrap_refuses_when_the_face_was_never_submitted():
    with pytest.raises(IdentityVerificationError) as e:
        assert_can_bootstrap_approve(_Row(face_digest=""), reason="平台自举")
    assert e.value.status == 409
    assert "face" in e.value.message


def test_bootstrap_refuses_when_the_document_was_never_submitted():
    with pytest.raises(IdentityVerificationError) as e:
        assert_can_bootstrap_approve(_Row(doc_digest=None), reason="平台自举")
    assert e.value.status == 409
    assert "document" in e.value.message


def test_bootstrap_refuses_a_second_approval():
    with pytest.raises(IdentityVerificationError) as e:
        assert_can_bootstrap_approve(_Row(status="verified"), reason="平台自举")
    assert e.value.status == 409
    assert "already" in e.value.message


def test_bootstrap_refuses_a_rejected_submission():
    with pytest.raises(IdentityVerificationError) as e:
        assert_can_bootstrap_approve(_Row(status="rejected"), reason="平台自举")
    assert e.value.status == 409