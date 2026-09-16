"""
Karma — 回调报文的签名校验。

服务商的回调是**服务商的服务器**打过来的，它没有、也不可能有 Karma 的访问令牌：
鉴权只能靠「只有我们和服务商知道的那把密钥」算出来的签名。所以这里的判定必须严格：

* 缺签名 / 签名格式不对 → 拒；
* 时间戳超出容忍窗口 → 拒（挡住重放）；
* 比对用 ``hmac.compare_digest``（定时安全），不用 ``==``。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from services.identity_provider.base import ProviderSignatureError


def sha256_hex(payload: bytes | str) -> str:
    """原始报文的指纹：库里只留这个，报文本身不留存。"""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def hmac_sha256_hex(secret: str, message: bytes | str) -> str:
    key = (secret or "").encode("utf-8")
    data = message.encode("utf-8") if isinstance(message, str) else message
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def parse_timestamped_signature(header: str | None) -> tuple[int, str]:
    """拆 ``t=<unix>,v1=<hex>`` 这种签名头（Persona / Stripe 一脉的写法）。"""
    if not header:
        raise ProviderSignatureError(401, "callback is missing its signature header")
    timestamp_raw: str | None = None
    signature: str | None = None
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp_raw = value.strip()
        elif key in ("v1", "v0"):
            signature = value.strip()
    if not timestamp_raw or not signature:
        raise ProviderSignatureError(
            401, "signature header must look like t=<unix>,v1=<hex>"
        )
    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise ProviderSignatureError(401, "signature timestamp is not an integer") from exc
    return timestamp, signature


def assert_fresh(timestamp: int, *, tolerance_seconds: int, now: float | None = None) -> None:
    """时间戳必须落在窗口内：旧报文重放不能再生效一次。"""
    current = time.time() if now is None else now
    if abs(current - timestamp) > max(1, int(tolerance_seconds)):
        raise ProviderSignatureError(401, "callback timestamp is outside the tolerance window")


def assert_signature(secret: str, raw_body: bytes, signature: str) -> None:
    if not (secret or "").strip():
        # 没配密钥就绝不能「放行」—— 否则任何人都能伪造一条「核验通过」。
        raise ProviderSignatureError(401, "no callback secret is configured for this provider")
    expected = hmac_sha256_hex(secret, raw_body)
    if not hmac.compare_digest(expected, (signature or "").strip().lower()):
        raise ProviderSignatureError(401, "callback signature does not match")


def verify_timestamped_hmac(
    *,
    secret: str,
    raw_body: bytes,
    header: str | None,
    tolerance_seconds: int,
    now: float | None = None,
) -> None:
    """``t=<unix>,v1=<hmac_sha256(secret, "<t>.<body>")>`` 一条龙校验。"""
    timestamp, signature = parse_timestamped_signature(header)
    assert_fresh(timestamp, tolerance_seconds=tolerance_seconds, now=now)
    assert_signature(secret, b"%d." % timestamp + raw_body, signature)


def sign_timestamped_hmac(*, secret: str, raw_body: bytes, timestamp: int | None = None) -> str:
    """生成上面那种签名头：本地模拟服务商、以及自查用。"""
    ts = int(time.time()) if timestamp is None else int(timestamp)
    digest = hmac_sha256_hex(secret, b"%d." % ts + raw_body)
    return "t=%d,v1=%s" % (ts, digest)


def header_value(headers: Any, name: str, default: str | None = None) -> str | None:
    """大小写不敏感地取一个请求头。

    Starlette 的 Headers 本来是大小写不敏感的，但适配器也要能被直接调用（测试、脚本），
    所以这里自己再兜一层 —— 服务商各家header 写法不一致（X-Persona-Signature /
    persona-signature），漏读一个等于把签名校验关掉。
    """
    lowered = name.lower()
    try:
        value = headers.get(name)
    except Exception:  # noqa: BLE001
        value = None
    if value is None:
        try:
            for key in list(headers.keys()):
                if str(key).lower() == lowered:
                    value = headers[key]
                    break
        except Exception:  # noqa: BLE001
            value = None
    if value is None:
        return default
    return str(value)
