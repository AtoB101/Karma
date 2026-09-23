"""操作台第二把锁（TOTP / 2FA）的单元测试。

分三层：

1. **算法层**对着 RFC 6238 附录 B 的官方向量验 —— 不是「自己算的自己认」，
   而是拿标准里的期望值做尺子；
2. **状态层**（绑定 / 验证 / 失败锁定 / 恢复码一次性 / 解绑）走真实数据库会话；
3. **闸门**两种姿态：没绑的身份默认放行、开了强制开关就必须先绑。
"""
from __future__ import annotations

import base64

import pytest

from config.settings import settings
from db.models.orm import ConsoleTwoFactorModel
from services import console_2fa as totp


# ---------------------------------------------------------------------------
# 1. 算法层
# ---------------------------------------------------------------------------

#: RFC 6238 附录 B：密钥是 ASCII "12345678901234567890"，SHA-1，8 位。
_RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")
_RFC_VECTORS = (
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
)


@pytest.mark.parametrize("at,expected", _RFC_VECTORS)
def test_totp_matches_rfc6238_vectors(at, expected):
    assert totp.totp(_RFC_SECRET, at=at, digits=8) == expected


def test_verify_accepts_the_current_code_and_nothing_else():
    secret = totp.new_secret()
    code = totp.totp(secret)
    assert totp.verify_code(secret, code) is True
    assert totp.verify_code(secret, "000000") is False
    # 形状不对（长度 / 非数字）直接 False，不进 HMAC。
    assert totp.verify_code(secret, "12345") is False
    assert totp.verify_code(secret, "abcdef") is False
    assert totp.verify_code("", code) is False


def test_verify_tolerates_one_step_of_clock_drift():
    """客户端时钟差 30 秒是常态，差太多就不是时钟问题了。"""
    secret = totp.new_secret()
    now = 1_700_000_000.0
    assert totp.verify_code(secret, totp.totp(secret, at=now - 30), at=now) is True
    assert totp.verify_code(secret, totp.totp(secret, at=now + 30), at=now) is True
    assert totp.verify_code(secret, totp.totp(secret, at=now - 120), at=now) is False


def test_secret_is_base32_and_provisioning_uri_is_scannable():
    secret = totp.new_secret()
    assert len(secret) == 32
    assert all(ch in totp.BASE32_ALPHABET for ch in secret)
    uri = totp.provisioning_uri(secret, account="kid-abc", issuer="Karma Network")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri
    # 发行方与账号百分号编码进路径，认证器 App 才认得出分组。
    assert "Karma%20Network%3Akid-abc" in uri


def test_recovery_codes_are_hashed_not_stored_in_the_clear():
    code = totp.new_recovery_codes(1)[0]
    digest = totp.hash_recovery(code, "kid-1")
    assert code not in digest and len(digest) == 64
    # 归一化：用户抄成小写、忘打横线都算对；拌进身份 id，换个身份撞不出同一个值。
    assert totp.normalize_recovery(code.lower().replace("-", "")) == totp.normalize_recovery(code)
    assert totp.hash_recovery(code, "kid-1") != totp.hash_recovery(code, "kid-2")


# ---------------------------------------------------------------------------
# 2. 状态层
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "console_2fa_max_failures", 3)
    monkeypatch.setattr(settings, "console_2fa_lock_seconds", 300)
    monkeypatch.setattr(settings, "console_2fa_required_for_funds", False)
    monkeypatch.setattr(settings, "console_2fa_issuer", "Karma Network")


async def _enrolled(db_session, identity_id="kid-2fa"):
    """走完整流程绑一把：签发 → 用真码确认。返回 (row, secret, recovery_codes)。"""
    await totp.begin_enroll(db_session, identity_id)
    row = await db_session.get(ConsoleTwoFactorModel, identity_id)
    secret = row.pending_secret
    payload = await totp.confirm_enroll(db_session, identity_id, totp.totp(secret))
    return row, secret, payload["recovery_codes"]


async def test_enroll_needs_a_confirming_code(db_session):
    """签发密钥不等于绑上了 —— 刷出来就要确认，不然「绑定」二字没有含义。"""
    identity_id = "kid-enroll"
    await totp.begin_enroll(db_session, identity_id)
    with pytest.raises(totp.TwoFactorError) as err:
        await totp.confirm_enroll(db_session, identity_id, "000000")
    assert err.value.status == 400

    row = await db_session.get(ConsoleTwoFactorModel, identity_id)
    secret = row.pending_secret
    payload = await totp.confirm_enroll(db_session, identity_id, totp.totp(secret))
    assert payload["enabled"] is True
    assert len(payload["recovery_codes"]) == totp.RECOVERY_CODE_COUNT
    state = await totp.status(db_session, identity_id)
    assert state["enabled"] is True and state["recovery_left"] == totp.RECOVERY_CODE_COUNT
    # 密钥不回吐：状态视图里没有 secret 字段。
    assert "secret" not in state and "pending_secret" not in state


async def test_confirm_before_enroll_is_rejected(db_session):
    with pytest.raises(totp.TwoFactorError) as err:
        await totp.confirm_enroll(db_session, "kid-none", "123456")
    assert err.value.status == 409


async def test_require_code_accepts_totp_then_rejects_reuse_of_a_bad_one(db_session):
    _, secret, _ = await _enrolled(db_session, "kid-gate")
    ok = await totp.require_code(db_session, "kid-gate", totp.totp(secret), what="allocations")
    assert ok["mode"] == "totp"

    with pytest.raises(totp.TwoFactorError) as err:
        await totp.require_code(db_session, "kid-gate", "000000", what="allocations")
    assert err.value.status == 401


async def test_recovery_code_works_once_and_is_burned(db_session):
    _, _, codes = await _enrolled(db_session, "kid-recover")
    used = await totp.require_code(db_session, "kid-recover", codes[0], what="allocations")
    assert used["mode"] == "recovery"
    assert used["recovery_left"] == len(codes) - 1
    # 同一张码不能再用第二次。
    with pytest.raises(totp.TwoFactorError) as err:
        await totp.require_code(db_session, "kid-recover", codes[0], what="allocations")
    assert err.value.status == 401
    # 别的恢复码不受影响。
    still = await totp.require_code(db_session, "kid-recover", codes[1], what="allocations")
    assert still["recovery_left"] == len(codes) - 2


async def test_failures_lock_the_identity_not_the_ip(db_session):
    _, secret, _ = await _enrolled(db_session, "kid-lock")
    for _ in range(3):
        with pytest.raises(totp.TwoFactorError):
            await totp.require_code(db_session, "kid-lock", "000000", what="allocations")
    row = await db_session.get(ConsoleTwoFactorModel, "kid-lock")
    assert row.locked_until is not None
    # 锁上之后**正确的验证码也不放行** —— 否则爆破只是变慢，没有变难。
    with pytest.raises(totp.TwoFactorError) as err:
        await totp.require_code(db_session, "kid-lock", totp.totp(secret), what="allocations")
    assert err.value.status == 423
    assert (await totp.status(db_session, "kid-lock"))["locked"] is True


async def test_disable_also_requires_a_code(db_session):
    """拆锁也要过锁：不然偷到会话就能把第二把锁摘掉。"""
    _, secret, _ = await _enrolled(db_session, "kid-disable")
    with pytest.raises(totp.TwoFactorError) as err:
        await totp.disable(db_session, "kid-disable", "000000")
    assert err.value.status == 401
    payload = await totp.disable(db_session, "kid-disable", totp.totp(secret))
    assert payload["enabled"] is False
    row = await db_session.get(ConsoleTwoFactorModel, "kid-disable")
    assert row.secret is None and row.recovery_hashes == []


async def test_rotate_recovery_replaces_the_old_sheet(db_session):
    _, secret, old_codes = await _enrolled(db_session, "kid-rotate")
    payload = await totp.rotate_recovery(db_session, "kid-rotate", totp.totp(secret))
    assert payload["recovery_left"] == totp.RECOVERY_CODE_COUNT
    with pytest.raises(totp.TwoFactorError):
        await totp.require_code(db_session, "kid-rotate", old_codes[0], what="allocations")


# ---------------------------------------------------------------------------
# 3. 闸门姿态
# ---------------------------------------------------------------------------

async def test_unenrolled_identity_passes_by_default_but_is_flagged(db_session):
    verdict = await totp.require_code(db_session, "kid-unbound", None, what="allocations")
    assert verdict["mode"] == "unenrolled"
    state = await totp.status(db_session, "kid-unbound")
    assert state["enabled"] is False and state["required_for_funds"] is False


async def test_forced_mode_refuses_to_move_money_without_enrollment(db_session, monkeypatch):
    monkeypatch.setattr(settings, "console_2fa_required_for_funds", True)
    with pytest.raises(totp.TwoFactorError) as err:
        await totp.require_code(db_session, "kid-forced", None, what="allocations")
    assert err.value.status == 409
    assert err.value.code == "enroll_required"
