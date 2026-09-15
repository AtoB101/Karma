"""自检引擎离线单测。

这里只测**能离线算准**的部分：统一社会信用代码校验位、邮箱/官网同站判定、
以及 DNS 报文的解析（用手工构造的报文，不去碰真实 DNS —— 测试不能因为断网变红，
也不能因为真实域名过期变红）。

MX 查询本身（``lookup_mx``）的网络分支不在这里测：它只在服务器上有意义，
而且设计上任何网络异常都必须归成 ``unavailable``，不允许当成「不通过」。
"""
from __future__ import annotations

import struct

import pytest

from services import auto_verification as av


# ---------------------------------------------------------------- 信用代码

#: GB 32100-2015 合法的统一社会信用代码（校验位算得对）。
VALID_USCC = "91330100MA2ABCDE1R"


def test_uscc_valid_code_passes():
    out = av.check_registration_no(VALID_USCC)
    assert out["status"] == av.STATUS_PASS


def test_uscc_wrong_check_digit_fails_and_says_what_it_should_be():
    broken = VALID_USCC[:-1] + "X"
    out = av.check_registration_no(broken)
    assert out["status"] == av.STATUS_FAIL
    # 提示要能直接抄回去改：告诉用户正确校验位是什么
    assert VALID_USCC[-1] in out["note"]


def test_uscc_typo_inside_body_also_fails():
    """改中间一位，校验位也必然对不上 —— 抄错一位不能混过去。"""
    assert av.check_registration_no("9133010AMA2ABCDE1R")["status"] == av.STATUS_FAIL


def test_uscc_wrong_length_fails_with_length_hint():
    out = av.check_registration_no("91330100MA2ABCDE1")
    assert out["status"] == av.STATUS_FAIL
    assert "18" in out["note"]


def test_uscc_illegal_letters_fail():
    """官方字符集去掉了易混的 I / O / S / V / Z。"""
    for bad in ("91330100MA2ABCDEIR", "91330100MA2ABCDEO1", "91330100MA2ABCDES1"):
        out = av.check_registration_no(bad)
        assert out["status"] == av.STATUS_FAIL, bad


def test_legacy_15_digit_registration_no_is_accepted_as_format():
    out = av.check_registration_no("123456789012345")
    assert out["status"] == av.STATUS_PASS
    assert "15" in out["note"]


def test_blank_registration_no_is_empty_not_fail():
    for value in (None, "", "   "):
        assert av.check_registration_no(value)["status"] == "empty"


def test_lowercase_input_is_normalized():
    assert av.check_registration_no(VALID_USCC.lower())["status"] == av.STATUS_PASS


# ---------------------------------------------------------------- 邮箱 / 站点


def test_email_domain_extracts_and_lowercases():
    assert av.email_domain("Someone@Example.COM") == "example.com"
    assert av.email_domain("  a@b.co  ") == "b.co"


@pytest.mark.parametrize("bad", [None, "", "no-at-sign", "a@", "a@b", "@b.com", "a b@c.com"])
def test_email_domain_rejects_junk(bad):
    assert av.email_domain(bad) == ""


def test_site_of_strips_www_and_keeps_full_country_suffix():
    assert av.site_of("www.example.com") == "example.com"
    assert av.site_of("mail.example.com") == "example.com"
    # 两级后缀 com.cn 不能被砍成 "com.cn"
    assert av.site_of("mail.example.com.cn") == "example.com.cn"
    assert av.site_of("EXAMPLE.COM.CN.") == "example.com.cn"


def test_same_site_matches_www_variants_and_subdomains():
    assert av.same_site("mail.example.com.cn", "www.example.com.cn") is True
    assert av.same_site("example.com", "shop.example.com") is True
    assert av.same_site("example.com", "example.org") is False


def test_same_site_is_false_when_either_side_is_missing():
    assert av.same_site("", "example.com") is False
    assert av.same_site("example.com", None) is False


# ---------------------------------------------------------------- DNS 报文


def _name(name: str) -> bytes:
    out = b""
    for label in name.split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def _mx_response(*exchanges: str, rcode: int = 0) -> bytes:
    """构造一个带答案的 MX 响应；答案里的 owner name 用 0xC0 压缩指针。"""
    answers = b""
    for pref, host in enumerate(exchanges, start=10):
        rdata = struct.pack(">H", pref) + _name(host)
        answers += b"\xc0\x0c" + struct.pack(">HHIH", av._QTYPE_MX, 1, 300, len(rdata)) + rdata
    header = struct.pack(">HHHHHH", 0x1234, 0x8180 | rcode, 1, len(exchanges), 0, 0)
    question = _name("example.com") + struct.pack(">HH", av._QTYPE_MX, 1)
    return header + question + answers


def test_parse_mx_reads_records_and_follows_compression_pointer():
    packet = _mx_response("mx1.mail.example.com", "mx2.mail.example.com")
    assert av._parse_mx(packet) == ["mx1.mail.example.com", "mx2.mail.example.com"]


def test_parse_mx_dedupes_and_sorts():
    packet = _mx_response("b.example.com", "a.example.com", "b.example.com")
    assert av._parse_mx(packet) == ["a.example.com", "b.example.com"]


def test_parse_mx_empty_answer_returns_empty_list():
    assert av._parse_mx(_mx_response()) == []


def test_parse_mx_returns_empty_on_error_rcode():
    """NXDOMAIN 之类的错误码不能被当成「有记录」以外的结论。"""
    assert av._parse_mx(_mx_response("mx.example.com", rcode=3)) == []


def test_parse_mx_rejects_truncated_packet():
    with pytest.raises(ValueError):
        av._parse_mx(b"\x00\x01\x02")


def test_decode_name_follows_pointer_and_detects_loop():
    packet = _name("example.com") + b"\xc0\x00"
    name, _ = av._decode_name(packet, len(_name("example.com")))
    assert name == "example.com"

    # 指向自己 -> 必须报错，不能无限递归
    with pytest.raises(ValueError):
        av._decode_name(b"\xc0\x00", 0)


def test_encode_name_rejects_overlong_label():
    with pytest.raises(ValueError):
        av._encode_name("x" * 64 + ".com")


# ---------------------------------------------------------------- 汇总清单


def _monkey_mx(monkeypatch, status=av.STATUS_PASS, records=("mx.example.com",)):
    """把 MX 查询钉死，避免单测依赖真实 DNS。"""
    monkeypatch.setattr(
        av, "lookup_mx", lambda domain, **kw: {"status": status, "records": list(records), "note": "stub"}
    )


def test_precheck_entity_flags_bad_registration_no_as_blocking(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_entity(
        legal_name="示例数据科技有限公司",
        registration_no=VALID_USCC[:-1] + "X",
        official_domain="example.com",
        contact_email="ops@example.com",
        service_scope="提供行情快照与历史数据的按次调用接口服务",
    )
    assert out["ok"] is False
    assert "registration_no" in out["blocking_failures"]


def test_precheck_entity_passes_when_everything_lines_up(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_entity(
        legal_name="示例数据科技有限公司",
        registration_no=VALID_USCC,
        official_domain="example.com",
        contact_email="ops@example.com",
        service_scope="提供行情快照与历史数据的按次调用接口服务",
        website_verified=True,
    )
    assert out["ok"] is True
    assert out["blocking_failures"] == []
    # 工商核验没接数据源时永远只能进人工清单 —— 不接就是不可用，不能假装通过
    assert out["needs_human"] == ["registry"]


def test_precheck_entity_puts_website_and_registry_in_needs_human(monkeypatch):
    """官网没回读、工商没接数据源 —— 都要进人工清单，而不是假装通过。"""
    _monkey_mx(monkeypatch)
    out = av.precheck_entity(
        legal_name="示例数据科技有限公司",
        registration_no=VALID_USCC,
        official_domain="example.com",
        contact_email="ops@example.com",
        service_scope="提供行情快照与历史数据的按次调用接口服务",
    )
    assert out["ok"] is True
    assert "website" in out["needs_human"]
    assert "registry" in out["needs_human"]


def test_precheck_entity_mailbox_mismatch_is_not_blocking(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_entity(
        legal_name="示例数据科技有限公司",
        registration_no=VALID_USCC,
        official_domain="example.com",
        contact_email="ops@other-site.com",
        service_scope="提供行情快照与历史数据的按次调用接口服务",
    )
    assert out["ok"] is True
    assert "email_matches_site" in out["needs_human"]


def test_precheck_entity_mx_failure_is_not_treated_as_rejection(monkeypatch):
    """DNS 查不动时只能是 unavailable，绝不能把用户判成不通过。"""
    _monkey_mx(monkeypatch, status=av.STATUS_UNAVAILABLE)
    out = av.precheck_entity(
        legal_name="示例数据科技有限公司",
        registration_no=VALID_USCC,
        official_domain="example.com",
        contact_email="ops@example.com",
        service_scope="提供行情快照与历史数据的按次调用接口服务",
    )
    assert out["ok"] is True
    assert "email_mx" in out["needs_human"]


def test_precheck_merchant_requires_operator_and_address(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_merchant(
        business_name="老王面馆",
        operator_name="",
        registration_no="",
        business_scope="餐饮服务",
        business_address="",
        contact_email="wang@example.com",
    )
    assert out["ok"] is False
    assert set(out["blocking_failures"]) == {"operator_name", "business_address"}


def test_precheck_merchant_bad_registration_no_is_not_blocking_but_still_surfaces(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_merchant(
        business_name="老王面馆",
        operator_name="王大明",
        registration_no=VALID_USCC[:-1] + "X",
        business_scope="餐饮服务",
        business_address="浙江省杭州市西湖区某路 1 号",
        contact_email="wang@example.com",
    )
    assert out["ok"] is True
    assert "registration_no" in out["needs_human"]


def test_precheck_personal_always_leaves_face_to_human(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_personal(full_name="张三", contact_email="zhangsan@example.com")
    assert out["ok"] is True
    assert "face" in out["needs_human"]


def test_precheck_personal_missing_name_blocks(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_personal(full_name="", contact_email="zhangsan@example.com")
    assert out["ok"] is False
    assert "full_name" in out["blocking_failures"]


def test_precheck_personal_bad_email_format_blocks(monkeypatch):
    _monkey_mx(monkeypatch)
    out = av.precheck_personal(full_name="张三", contact_email="not-an-email")
    assert out["ok"] is False
    assert "email_mx" in out["blocking_failures"]


# ---------------------------------------------------------------- 工商核验


def test_registry_check_is_honest_about_missing_provider(monkeypatch):
    monkeypatch.delenv("BUSINESS_REGISTRY_PROVIDER", raising=False)
    out = av.registry_check(VALID_USCC, "示例数据科技有限公司")
    assert out["status"] == av.STATUS_UNAVAILABLE
