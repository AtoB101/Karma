"""主身份认证（证件 + 刷脸）的自动预检。

这一层的价值是**把人工从「每一份都要看」降到「只看异常」**，所以门禁要卡住两件事：
① 机器真的判得出来的，必须判出来（过期证件、没勾承诺、没交刷脸、包大小离谱）；
② 机器判不了的，必须如实说判不了，不许假装通过（证件真伪、活体）。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from services import auto_verification


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch):
    """自检里会查 MX。测试不许碰真实 DNS：断网会让测试红成假红。"""
    monkeypatch.setattr(
        auto_verification,
        "lookup_mx",
        lambda domain, **kw: {
            "status": auto_verification.STATUS_PASS,
            "records": ["mx.example.com"],
            "note": "stub",
        },
    )


DIGEST = "a" * 64


def _check(result, key):
    for row in result["checks"]:
        if row["key"] == key:
            return row
    raise AssertionError(f"no such check: {key}")


def _ok_kwargs(**over):
    kwargs = dict(
        level="basic",
        doc_type="PASSPORT",
        full_name="张三",
        doc_number_mask="*****5908",
        valid_until="2028.8.26",
        contact_email="zhangsan@example.test",
        doc_digest=DIGEST,
        face_digest=DIGEST,
        package_cipher_chars=646_452,
        face_match_hint="5角度采集:正面/向左转/向右转/抬高/低头",
        consent=True,
    )
    kwargs.update(over)
    return kwargs


def test_a_complete_submission_has_nothing_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs())
    assert result["ok"] is True
    assert result["blocking_failures"] == []
    assert _check(result, "doc_validity")["status"] == auto_verification.STATUS_PASS
    assert _check(result, "face_angles")["status"] == auto_verification.STATUS_PASS


def test_a_liveness_check_never_pretends_to_pass():
    """没接第三方活体服务：这一条必须是「未接入」，不能是「已通过」。"""
    result = auto_verification.precheck_identity(**_ok_kwargs())
    liveness = _check(result, "liveness")
    assert liveness["status"] == auto_verification.STATUS_UNAVAILABLE
    assert "liveness" in result["needs_human"]
    assert "未接入" in liveness["note"]


def test_an_expired_document_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(valid_until="2020.1.1"))
    assert result["ok"] is False
    assert "doc_validity" in result["blocking_failures"]
    assert "过期" in _check(result, "doc_validity")["note"]


def test_a_missing_consent_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(consent=False))
    assert result["ok"] is False
    assert "consent" in result["blocking_failures"]


def test_a_submission_without_a_face_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(face_digest=""))
    assert result["ok"] is False
    assert "face_digest" in result["blocking_failures"]


def test_a_submission_without_a_document_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(doc_digest=None))
    assert result["ok"] is False
    assert "doc_digest" in result["blocking_failures"]


def test_an_unknown_document_type_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(doc_type="LIBRARY_CARD"))
    assert result["ok"] is False
    assert "doc_type" in result["blocking_failures"]


def test_an_oversized_package_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(package_cipher_chars=99_000_000))
    assert result["ok"] is False
    assert "package" in result["blocking_failures"]


def test_a_package_that_is_too_small_is_blocking():
    result = auto_verification.precheck_identity(**_ok_kwargs(package_cipher_chars=8))
    assert result["ok"] is False
    assert "package" in result["blocking_failures"]


def test_fewer_face_angles_are_flagged_but_not_blocked():
    """走「本角度改用照片」降级通道的人不能被挡在门外，但复核岗必须看得见。"""
    result = auto_verification.precheck_identity(**_ok_kwargs(face_match_hint="1角度采集:正面"))
    assert result["ok"] is True
    assert "face_angles" in result["needs_human"]
    assert _check(result, "face_angles")["blocking"] is False


def test_a_document_expiring_soon_goes_to_a_human():
    soon = (date.today() + timedelta(days=30)).isoformat()
    result = auto_verification.precheck_identity(**_ok_kwargs(valid_until=soon))
    assert result["ok"] is True
    assert "doc_validity" in result["needs_human"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2028.8.26", date(2028, 8, 26)),
        ("2028-08-26", date(2028, 8, 26)),
        ("2028/08/26", date(2028, 8, 26)),
        ("20280826", date(2028, 8, 26)),
        ("长期", None),
        ("长期有效", None),
        ("", None),
        ("看不懂", None),
    ],
)
def test_document_validity_parser(raw, expected):
    assert auto_verification.parse_document_valid_until(raw) == expected


def test_personal_id_long_term_is_not_treated_as_expired():
    result = auto_verification.precheck_identity(**_ok_kwargs(valid_until="长期"))
    assert result["ok"] is True
    assert _check(result, "doc_validity")["status"] == auto_verification.STATUS_PASS


@pytest.mark.parametrize(
    "hint,expected",
    [
        ("5角度采集:正面/向左转/向右转/抬高/低头", 5),
        ("1角度采集:正面", 1),
        ("正面/向左转/向右转", 3),
        ("", None),
        (None, None),
    ],
)
def test_face_angle_count(hint, expected):
    assert auto_verification.face_angle_count(hint) == expected
