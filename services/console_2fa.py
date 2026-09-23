"""
Karma — 操作台第二把锁：授权 / 取消授权的 TOTP 验证码（RFC 6238）。
=================================================================

为什么要有这一层
----------------
绑到操作台上的钥匙（钱包会话、运行时密钥）是**不记名**的：谁拿到谁就能动。
用户按「授权额度」的那一刻，钱虽然还在自己的钱包里，但额度是实打实的支配权；
「取消授权」更是不可逆动作。所以这两类动作在钱包签名之外，再过一道**只有本人手机上
那个 App 才有**的 6 位口令 —— 偷到钥匙的人到这里就停住了。

三条纪律
--------
1. **零依赖**：TOTP 就是 HMAC-SHA1 + 动态截断，40 行写完，对着 RFC 6238 附录 B 的
   测试向量验（见 tests/unit/test_console_2fa.py）。多引一个库就多一份供应链风险，
   而这段代码的每一行都能被读明白。
2. **验证码不落库**：它是 30 秒一换的一次性口令，存下来只会变成新的秘密。
   落库的是 TOTP 密钥（base32）与**恢复码的哈希**。
3. **失败要付代价**：连续错 N 次锁一段时间。锁是按身份锁的，不是按 IP ——
   攻击者换机器没有用。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models.orm import ConsoleTwoFactorModel

#: RFC 6238 默认参数（Authy / Google Authenticator / 1Password 都认这一套）。
STEP_SECONDS = 30
DIGITS = 6
#: 允许前后各一个时间窗（±30 秒），挡客户端时钟漂移；再宽就等于给爆破留门。
WINDOW_STEPS = 1
ALGORITHM = hashlib.sha1

BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
#: 绑定时给用户看的恢复码：一次性，用掉即焚；每张 8 位，分两段好看好抄。
RECOVERY_CODE_COUNT = 10
RECOVERY_GROUP_CHARS = 4


class TwoFactorError(Exception):
    """带 HTTP 状态的 2FA 错误，路由层直接翻译成响应。"""

    def __init__(self, status: int, message: str, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        #: 机器可读的原因码，操作台靠它决定弹哪个框（例如去设置里绑定）。
        self.code = code


# ---------------------------------------------------------------------------
# 纯函数层：不碰数据库，可以单独对着 RFC 向量测
# ---------------------------------------------------------------------------

def new_secret(num_bytes: int = 20) -> str:
    """签发一把新的 TOTP 密钥（base32，空填充 —— 认证器 App 认这个形状）。"""
    return base64.b32encode(secrets.token_bytes(num_bytes)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    raw = (secret or "").strip().replace(" ", "").upper()
    if not raw:
        raise ValueError("empty TOTP secret")
    padding = (-len(raw)) % 8
    try:
        return base64.b32decode(raw + "=" * padding, casefold=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("TOTP secret is not valid base32") from exc


def counter_at(at: float | None = None, *, step: int = STEP_SECONDS) -> int:
    return int((time.time() if at is None else at) // step)


def totp(secret: str, *, at: float | None = None, step: int = STEP_SECONDS, digits: int = DIGITS) -> str:
    """RFC 6238：T = (now - T0) / X，HMAC-SHA1 之后动态截断取 digits 位。"""
    message = struct.pack(">Q", counter_at(at, step=step))
    digest = hmac.new(_decode_secret(secret), message, ALGORITHM).digest()
    offset = digest[-1] & 0x0F
    chunk = digest[offset : offset + 4]
    value = struct.unpack(">I", chunk)[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def verify_code(secret: str, code: str, *, at: float | None = None, window: int = WINDOW_STEPS) -> bool:
    """常量时间比对当前时间窗 ±window。输入形状不对直接 False，不抛。"""
    candidate = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(candidate) != DIGITS or not secret:
        return False
    now = time.time() if at is None else at
    hit = False
    for offset in range(-window, window + 1):
        try:
            expected = totp(secret, at=now + offset * STEP_SECONDS)
        except ValueError:
            return False
        # 不短路：每一次都跑完，免得时间差泄露出「第几个窗口对了」。
        if hmac.compare_digest(expected, candidate):
            hit = True
    return hit


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    """otpauth:// 链接：操作台把它渲染成二维码，认证器 App 扫一下即可。

    形状照 Key URI Format 写：路径里是 ``发行方:账号``（百分号编码），参数只放
    必要的那几个。认证器 App 靠 issuer 参数把这条挂到分组下 —— 所以标签里也带上
    发行方，扫出来的名字才不是一串身份 id。
    """
    from urllib.parse import quote

    label = f"{issuer}:{account}" if issuer else account
    return (
        "otpauth://totp/"
        + quote(label, safe="")
        + f"?secret={secret}&issuer={quote(str(issuer or ''), safe='')}"
        + f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def new_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """恢复码：手机丢了 / 换机时的一次性出口。分组只为好抄，拼接时把横线去掉。"""
    out = []
    for _ in range(count):
        raw = "".join(secrets.choice(BASE32_ALPHABET) for _ in range(RECOVERY_GROUP_CHARS * 2))
        out.append(f"{raw[:RECOVERY_GROUP_CHARS]}-{raw[RECOVERY_GROUP_CHARS:]}")
    return out


def normalize_recovery(code: str) -> str:
    """把用户抄进来的恢复码归一化（大小写 / 横线 / 空格都不计较）。"""
    return "".join(ch for ch in str(code or "").upper() if ch in BASE32_ALPHABET)


def hash_recovery(code: str, identity_id: str) -> str:
    """恢复码只存哈希，而且把身份 id 拌进去 —— 换个身份撞同一张表也换不出原文。"""
    payload = f"karma:2fa-recovery:v1:{identity_id}:{normalize_recovery(code)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# 状态层：一张表一条记录，按身份 id 主键
# ---------------------------------------------------------------------------

def _settings_int(name: str, fallback: int) -> int:
    try:
        value = int(getattr(get_settings(), name, fallback) or fallback)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _now() -> datetime:
    return datetime.utcnow()


async def _load(db: AsyncSession, identity_id: str) -> ConsoleTwoFactorModel:
    row = await db.get(ConsoleTwoFactorModel, identity_id)
    if row is None:
        row = ConsoleTwoFactorModel(identity_id=identity_id)
        db.add(row)
    return row


def _enabled(row: ConsoleTwoFactorModel) -> bool:
    return bool(row.secret and row.enabled_at)


def public_view(row: ConsoleTwoFactorModel | None, identity_id: str) -> dict[str, Any]:
    """给操作台看的状态：只说「绑没绑」，**绝不回吐密钥**。"""
    locked_until = getattr(row, "locked_until", None) if row else None
    return {
        "identity_id": identity_id,
        "enabled": bool(row and _enabled(row)),
        "pending": bool(row and row.pending_secret and not _enabled(row)),
        "recovery_left": len(row.recovery_hashes or []) if row else 0,
        "failures": int(getattr(row, "failures", 0) or 0) if row else 0,
        "locked_until": locked_until.isoformat() if locked_until else None,
        "locked": bool(locked_until and locked_until > _now()),
        "last_used_at": row.last_used_at.isoformat() if row and row.last_used_at else None,
        "required_for_funds": bool(getattr(get_settings(), "console_2fa_required_for_funds", False)),
    }


async def status(db: AsyncSession, identity_id: str) -> dict[str, Any]:
    return public_view(await db.get(ConsoleTwoFactorModel, identity_id), identity_id)


async def begin_enroll(db: AsyncSession, identity_id: str, *, account: str | None = None) -> dict[str, Any]:
    """签发一把待确认的密钥。**确认之前不生效** —— 免得刷出密钥就等于绑上了。"""
    row = await _load(db, identity_id)
    if _enabled(row):
        raise TwoFactorError(409, "2FA is already enabled for this identity", "already_enabled")
    secret = new_secret()
    row.pending_secret = secret
    row.pending_created_at = _now()
    await db.flush()
    issuer = str(getattr(get_settings(), "console_2fa_issuer", "Karma Network") or "Karma Network")
    return {
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, account=account or identity_id, issuer=issuer),
        "issuer": issuer,
        "digits": DIGITS,
        "period": STEP_SECONDS,
        "algorithm": "SHA1",
    }


async def confirm_enroll(db: AsyncSession, identity_id: str, code: str) -> dict[str, Any]:
    """验证码对得上才算绑上，同时发一组一次性恢复码（只在这个响应里出现一次）。"""
    row = await _load(db, identity_id)
    if _enabled(row):
        raise TwoFactorError(409, "2FA is already enabled for this identity", "already_enabled")
    if not row.pending_secret:
        raise TwoFactorError(409, "start the 2FA enrollment first", "no_pending_enroll")
    if not verify_code(row.pending_secret, code):
        raise TwoFactorError(400, "the verification code is not valid", "bad_code")
    codes = new_recovery_codes()
    row.secret = row.pending_secret
    row.pending_secret = None
    row.pending_created_at = None
    row.enabled_at = _now()
    row.recovery_hashes = [hash_recovery(c, identity_id) for c in codes]
    row.failures = 0
    row.locked_until = None
    await db.flush()
    return {"enabled": True, "recovery_codes": codes, "recovery_left": len(codes)}


async def disable(db: AsyncSession, identity_id: str, code: str) -> dict[str, Any]:
    """解绑同样要过一次验证码：不然偷到会话就能把第二把锁拆了。"""
    row = await db.get(ConsoleTwoFactorModel, identity_id)
    if row is None or not _enabled(row):
        raise TwoFactorError(409, "2FA is not enabled for this identity", "not_enabled")
    await _consume_code(db, row, code, what="disable 2FA")
    row.secret = None
    row.enabled_at = None
    row.recovery_hashes = []
    row.failures = 0
    row.locked_until = None
    await db.flush()
    return {"enabled": False}


async def rotate_recovery(db: AsyncSession, identity_id: str, code: str) -> dict[str, Any]:
    row = await db.get(ConsoleTwoFactorModel, identity_id)
    if row is None or not _enabled(row):
        raise TwoFactorError(409, "2FA is not enabled for this identity", "not_enabled")
    await _consume_code(db, row, code, what="rotate recovery codes")
    codes = new_recovery_codes()
    row.recovery_hashes = [hash_recovery(c, identity_id) for c in codes]
    await db.flush()
    return {"recovery_codes": codes, "recovery_left": len(codes)}


# ---------------------------------------------------------------------------
# 闸门：动钱之前过这一道
# ---------------------------------------------------------------------------

def _locked(row: ConsoleTwoFactorModel) -> bool:
    return bool(row.locked_until and row.locked_until > _now())


def _register_failure(row: ConsoleTwoFactorModel) -> None:
    max_failures = _settings_int("console_2fa_max_failures", 5)
    lock_seconds = _settings_int("console_2fa_lock_seconds", 300)
    row.failures = int(row.failures or 0) + 1
    if row.failures >= max_failures:
        row.locked_until = _now() + timedelta(seconds=lock_seconds)
        row.failures = 0


async def _consume_code(
    db: AsyncSession, row: ConsoleTwoFactorModel, code: str, *, what: str
) -> str:
    """吃掉一次口令。返回用掉的是 totp 还是 recovery —— 审计里要看得出来。"""
    if _locked(row):
        raise TwoFactorError(
            423,
            f"too many failed codes; try again after {row.locked_until.isoformat()}Z",
            "locked",
        )
    # 6 位纯数字 = TOTP；其余形状按恢复码试（恢复码是 8 位 base32）。
    if str(code or "").strip().isdigit():
        if verify_code(row.secret or "", code):
            row.failures = 0
            row.last_used_at = _now()
            await db.flush()
            return "totp"
    else:
        digest = hash_recovery(code, row.identity_id)
        for index, stored in enumerate(list(row.recovery_hashes or [])):
            if isinstance(stored, str) and hmac.compare_digest(stored, digest):
                remaining = list(row.recovery_hashes or [])
                remaining.pop(index)
                row.recovery_hashes = remaining  # 一次性：用掉即焚
                row.failures = 0
                row.last_used_at = _now()
                await db.flush()
                return "recovery"
    # 错就是错：不管是哪种形状，记一次失败。**不能只在「像恢复码」时才记** ——
    # 恢复码的字母表里没有 0 和 1，于是 000000 这种最典型的瞎猜反而不计数。
    _register_failure(row)
    await db.flush()
    raise TwoFactorError(401, f"invalid 2FA code for {what}", "bad_code")


async def require_code(
    db: AsyncSession, identity_id: str, code: str | None, *, what: str
) -> dict[str, Any]:
    """授权 / 取消授权前的统一入口。

    没绑 2FA 时：默认放行（记审计），``CONSOLE_2FA_REQUIRED_FOR_FUNDS=true`` 时拒绝，
    让调用方先去绑定 —— 这是运维能把「全员强制」打开的旋钮。
    """
    row = await db.get(ConsoleTwoFactorModel, identity_id)
    if row is None or not _enabled(row):
        if bool(getattr(get_settings(), "console_2fa_required_for_funds", False)):
            raise TwoFactorError(
                409,
                "this identity has no 2FA yet: bind an authenticator in the console settings "
                "before moving funds",
                "enroll_required",
            )
        return {"mode": "unenrolled", "what": what}
    method = await _consume_code(db, row, code or "", what=what)
    return {
        "mode": method,
        "what": what,
        "recovery_left": len(row.recovery_hashes or []),
        "used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


__all__ = [
    "DIGITS",
    "STEP_SECONDS",
    "TwoFactorError",
    "begin_enroll",
    "confirm_enroll",
    "disable",
    "hash_recovery",
    "new_recovery_codes",
    "new_secret",
    "normalize_recovery",
    "provisioning_uri",
    "public_view",
    "require_code",
    "rotate_recovery",
    "status",
    "totp",
    "verify_code",
]
