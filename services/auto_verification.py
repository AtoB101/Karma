"""自动核验：能算出来的结论，不要留给复核岗用眼睛看。

复核岗要判的是「这份材料是不是真的」，而不是「这个统一社会信用代码有没有抄错一位」。
所以凡是能自动判的，都在这里判掉，复核台只显示「已自动通过 / 自动不通过 / 需要人工判断」。

三类检查，都是**只读**的，不改任何状态：

1. 统一社会信用代码校验位（GB 32100-2015）：本地可算，抄错一位立刻现形。
2. 企业邮箱域名 MX 记录：纯 Python 发一次 UDP DNS 查询（不引第三方依赖），
   查得到 MX 说明这个域名真的在收邮件；查不到就标「无法确认」，不阻断提交。
3. 邮箱域名与官网域名一致性：同域名 / 同站点（去掉 www 与二级后缀）都算一致。

工商核验（营业执照真伪）需要第三方数据源，**没有配置就老实说没接入**，
不许假装通过 —— 见 ``registry_check``。
"""
from __future__ import annotations

import os
import random
import re
import socket
import struct
import threading
import time
from typing import Any

# --------------------------------------------------------------------------
# 统一社会信用代码（GB 32100-2015）
# --------------------------------------------------------------------------

#: 官方字符集：31 个字符，去掉了容易看错的 I / O / S / V / Z。
USCC_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
USCC_LEN = 18
_LEGACY_REG_NO_RE = re.compile(r"^[0-9]{15}$")

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_MANUAL = "manual"
STATUS_UNAVAILABLE = "unavailable"


def check_registration_no(value: str | None) -> dict[str, Any]:
    """统一社会信用代码 / 老版 15 位注册号。

    没填 -> ``empty``（选填项，不算错）；填了但抄错 -> ``fail``。
    """
    raw = str(value or "").strip().upper()
    if not raw:
        return {"status": "empty", "note": "未填写（选填）"}

    if _LEGACY_REG_NO_RE.match(raw):
        return {"status": STATUS_PASS, "note": "15 位老版注册号格式正确（真伪仍需人工/工商核验）"}

    if len(raw) != USCC_LEN:
        return {"status": STATUS_FAIL, "note": f"长度应为 {USCC_LEN} 位，当前 {len(raw)} 位"}
    bad = [c for c in raw if c not in USCC_CHARSET]
    if bad:
        return {
            "status": STATUS_FAIL,
            "note": "含非法字符（该字符集不含 I / O / S / V / Z）：" + "".join(sorted(set(bad))),
        }

    total = 0
    for idx, char in enumerate(raw[: USCC_LEN - 1]):
        total += USCC_CHARSET.index(char) * USCC_WEIGHTS[idx]
    expected = USCC_CHARSET[(31 - total % 31) % 31]
    if expected != raw[-1]:
        return {
            "status": STATUS_FAIL,
            "note": f"校验位不对：按前 17 位算应为 {expected}，填的是 {raw[-1]}",
        }
    return {"status": STATUS_PASS, "note": "校验位正确"}


# --------------------------------------------------------------------------
# 邮箱与域名
# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
#: 常见二级后缀：a.com.cn 这种要取三段，否则会把 "com.cn" 当成站点。
_TWO_LEVEL_SUFFIXES = (
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "com.hk", "com.tw", "co.jp", "co.uk", "co.kr", "com.sg",
)


def email_domain(email: str | None) -> str:
    match = _EMAIL_RE.match(str(email or "").strip().lower())
    return match.group(1) if match else ""


def site_of(host: str | None) -> str:
    """站点名：去掉 www 与常见二级后缀，用来判断「邮箱和官网是不是同一家」。"""
    clean = str(host or "").strip().lower().lstrip(".")
    if clean.startswith("www."):
        clean = clean[4:]
    labels = [p for p in clean.split(".") if p]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(left: str | None, right: str | None) -> bool:
    a, b = site_of(left), site_of(right)
    return bool(a) and a == b


# --------------------------------------------------------------------------
# MX：纯 Python 的 DNS 查询（不引依赖，容器里也能跑）
# --------------------------------------------------------------------------

_MX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MX_CACHE_TTL = 600.0
_MX_LOCK = threading.Lock()
_QTYPE_MX = 15


def _system_resolver() -> str:
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    return parts[1]
    except Exception:  # noqa: BLE001
        pass
    return "1.1.1.1"


def _encode_name(name: str) -> bytes:
    out = b""
    for label in str(name).strip(".").split("."):
        raw = label.encode("idna") if label else b""
        if not raw or len(raw) > 63:
            raise ValueError("invalid dns label")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _decode_name(packet: bytes, offset: int, depth: int = 0) -> tuple[str, int]:
    """解 DNS 名字，处理 0xC0 压缩指针（MX 的 exchange 基本都是指针）。"""
    labels: list[str] = []
    position = offset
    jumped = False
    end = offset
    while True:
        if position >= len(packet):
            raise ValueError("dns packet truncated")
        length = packet[position]
        if length == 0:
            position += 1
            if not jumped:
                end = position
            break
        if length & 0xC0 == 0xC0:
            if depth > 8:
                raise ValueError("dns pointer loop")
            pointer = struct.unpack(">H", packet[position : position + 2])[0] & 0x3FFF
            if not jumped:
                end = position + 2
            sub, _ = _decode_name(packet, pointer, depth + 1)
            labels.append(sub)
            jumped = True
            break
        position += 1
        labels.append(packet[position : position + length].decode("ascii", "replace"))
        position += length
    return ".".join([p for p in labels if p]), end


def _parse_mx(packet: bytes) -> list[str]:
    if len(packet) < 12:
        raise ValueError("dns packet too short")
    _tid, flags, qdcount, ancount, _ns, _ar = struct.unpack(">HHHHHH", packet[:12])
    if flags & 0x000F:  # RCODE != 0
        return []
    offset = 12
    for _ in range(qdcount):
        _name, offset = _decode_name(packet, offset)
        offset += 4  # qtype + qclass
    exchanges: list[str] = []
    for _ in range(ancount):
        _name, offset = _decode_name(packet, offset)
        if offset + 10 > len(packet):
            break
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", packet[offset : offset + 10])
        offset += 10
        rdata = packet[offset : offset + rdlength]
        if rtype == _QTYPE_MX and len(rdata) >= 3:
            exchange, _ = _decode_name(packet, offset + 2)
            if exchange:
                exchanges.append(exchange.rstrip(".").lower())
        offset += rdlength
    return sorted(set(exchanges))


def lookup_mx(domain: str, *, timeout: float = 2.0) -> dict[str, Any]:
    """查 MX。任何网络问题都归成 ``unavailable`` —— 不能把「查不到」当成「不通过」。"""
    host = str(domain or "").strip().lower().rstrip(".")
    if not host:
        return {"status": STATUS_UNAVAILABLE, "records": [], "note": "没有域名可查"}

    now = time.time()
    with _MX_LOCK:
        cached = _MX_CACHE.get(host)
        if cached and cached[0] > now:
            return dict(cached[1])

    result: dict[str, Any]
    try:
        query_id = random.randrange(0, 0xFFFF)
        packet = struct.pack(">HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + _encode_name(host) + struct.pack(">HH", _QTYPE_MX, 1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(packet, (_system_resolver(), 53))
            data, _addr = sock.recvfrom(4096)
        records = _parse_mx(data)
        if records:
            result = {"status": STATUS_PASS, "records": records, "note": "MX：" + ", ".join(records[:3])}
        else:
            result = {"status": STATUS_MANUAL, "records": [], "note": "查不到 MX 记录（可能是纯接收转发或域名未启用邮箱）"}
    except Exception as exc:  # noqa: BLE001
        result = {"status": STATUS_UNAVAILABLE, "records": [], "note": f"DNS 查询不可用（{type(exc).__name__}）"}

    with _MX_LOCK:
        _MX_CACHE[host] = (now + _MX_CACHE_TTL, dict(result))
    return result


# --------------------------------------------------------------------------
# 工商核验（需要第三方数据源，没配就说没接入）
# --------------------------------------------------------------------------


def registry_check(registration_no: str | None, legal_name: str | None) -> dict[str, Any]:
    provider = (os.getenv("BUSINESS_REGISTRY_PROVIDER") or "").strip()
    if not provider:
        return {
            "status": STATUS_UNAVAILABLE,
            "note": "未接入工商核验数据源（需要第三方接口；当前只能核格式与校验位）",
        }
    # 接上第三方后在这里调它，并把结论归一化成上面的三种状态。
    return {"status": STATUS_MANUAL, "note": f"已配置数据源 {provider}，待接入调用实现"}


# --------------------------------------------------------------------------
# 汇总：三张认证页各自的自检清单
# --------------------------------------------------------------------------


def _row(key: str, label: str, check: dict[str, Any], *, blocking: bool = True) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": check.get("status", STATUS_MANUAL),
        "note": check.get("note", ""),
        "blocking": bool(blocking),
    }


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """把结论分成三堆：可以先改再提交的、提交后必须有人看的、剩下的。

    ``needs_human`` 除了「自动判不了」（manual / unavailable），还要收**非阻断的自动不通过**——
    例如个体工商户的信用代码抄错一位：不挡着提交，但绝不能因此沉到队尾没人看。
    """
    blocking_failures = [c["key"] for c in checks if c["blocking"] and c["status"] == STATUS_FAIL]
    needs_human = [
        c["key"]
        for c in checks
        if c["status"] in (STATUS_MANUAL, STATUS_UNAVAILABLE)
        or (c["status"] == STATUS_FAIL and not c["blocking"])
    ]
    return {
        "checks": checks,
        "ok": not blocking_failures,
        "blocking_failures": blocking_failures,
        "needs_human": needs_human,
    }


def precheck_entity(
    *,
    legal_name: str | None,
    registration_no: str | None,
    official_domain: str | None,
    contact_email: str | None,
    service_scope: str | None,
    website_verified: bool = False,
) -> dict[str, Any]:
    """企业助理认证的自检清单。"""
    domain = str(official_domain or "").strip().lower()
    mail_domain = email_domain(contact_email)
    checks = [
        _row("legal_name", "主体全称", {
            "status": STATUS_PASS if len(str(legal_name or "").strip()) >= 2 else STATUS_FAIL,
            "note": "已填写" if len(str(legal_name or "").strip()) >= 2 else "主体全称太短",
        }),
        _row("registration_no", "统一社会信用代码校验位", check_registration_no(registration_no)),
        _row("website", "官网控制权", {
            "status": STATUS_PASS if website_verified else STATUS_MANUAL,
            "note": "已通过校验文件回读" if website_verified else "还没做官网回读校验",
        }),
        _row("email_mx", "企业邮箱 MX", lookup_mx(mail_domain) if mail_domain else {
            "status": STATUS_FAIL, "note": "联系邮箱格式不对，取不到域名",
        }),
        _row("email_matches_site", "邮箱域名与官网一致", {
            "status": STATUS_PASS if (mail_domain and domain and same_site(mail_domain, domain)) else STATUS_MANUAL,
            "note": ("同一站点：" + site_of(mail_domain)) if (mail_domain and domain and same_site(mail_domain, domain))
            else "邮箱域名与官网不同（用企业邮箱以外的邮箱也能提交，但要人工确认）",
        }, blocking=False),
        _row("service_scope", "服务范围", {
            "status": STATUS_PASS if len(str(service_scope or "").strip()) >= 10 else STATUS_FAIL,
            "note": "已填写" if len(str(service_scope or "").strip()) >= 10 else "服务范围请写清楚（至少 10 个字）",
        }),
        _row("registry", "工商核验", registry_check(registration_no, legal_name), blocking=False),
    ]
    return _summarize(checks)


def precheck_merchant(
    *,
    business_name: str | None,
    operator_name: str | None,
    registration_no: str | None,
    business_scope: str | None,
    business_address: str | None,
    contact_email: str | None,
) -> dict[str, Any]:
    """个体助理认证的自检清单。个体户没有官网，所以不查官网控制权。"""
    mail_domain = email_domain(contact_email)
    checks = [
        _row("business_name", "字号 / 主体名称", {
            "status": STATUS_PASS if len(str(business_name or "").strip()) >= 2 else STATUS_FAIL,
            "note": "已填写" if len(str(business_name or "").strip()) >= 2 else "字号太短",
        }),
        _row("operator_name", "经营者姓名", {
            "status": STATUS_PASS if len(str(operator_name or "").strip()) >= 2 else STATUS_FAIL,
            "note": "已填写" if len(str(operator_name or "").strip()) >= 2 else "经营者姓名必填",
        }),
        _row("registration_no", "统一社会信用代码校验位", check_registration_no(registration_no), blocking=False),
        _row("business_scope", "经营范围", {
            "status": STATUS_PASS if len(str(business_scope or "").strip()) >= 4 else STATUS_FAIL,
            "note": "已填写" if len(str(business_scope or "").strip()) >= 4 else "经营范围必填",
        }),
        _row("business_address", "经营地址", {
            "status": STATUS_PASS if len(str(business_address or "").strip()) >= 6 else STATUS_FAIL,
            "note": "已填写" if len(str(business_address or "").strip()) >= 6 else "经营地址请写详细（至少 6 个字）",
        }),
        _row("email_mx", "联系邮箱 MX", lookup_mx(mail_domain) if mail_domain else {
            "status": STATUS_FAIL, "note": "联系邮箱格式不对，取不到域名",
        }),
        _row("registry", "工商核验", registry_check(registration_no, business_name), blocking=False),
    ]
    return _summarize(checks)


def precheck_personal(*, full_name: str | None, contact_email: str | None) -> dict[str, Any]:
    """个人助理认证的自检清单。"""
    mail_domain = email_domain(contact_email)
    checks = [
        _row("full_name", "姓名", {
            "status": STATUS_PASS if len(str(full_name or "").strip()) >= 2 else STATUS_FAIL,
            "note": "已填写" if len(str(full_name or "").strip()) >= 2 else "姓名必填",
        }),
        _row("email_mx", "联系邮箱 MX", lookup_mx(mail_domain) if mail_domain else {
            "status": STATUS_FAIL, "note": "联系邮箱格式不对，取不到域名",
        }),
        _row("face", "刷脸", {"status": STATUS_MANUAL, "note": "活体识别未接入自动判读，由复核岗看密文包"}, blocking=False),
    ]
    return _summarize(checks)
