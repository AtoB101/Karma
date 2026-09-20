"""Runtime Key issuance, verification, and lightweight spend / replay tracking."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import RuntimeKeyModel


ALLOWED_PERMISSIONS = frozenset(
    {
        "request_voucher",
        "verify_voucher",
        "submit_receipt",
        "update_progress",
        "request_settlement",
        "sync_task_status",
        # 发现：让 agent 自己去找能办事的 agent / 商家（只读）。
        "discover_agents",
        # 下单：在操作台设的额度内自己发起一笔委托（钱仍要过验证才划转）。
        "place_order",
    }
)

# 一把 Runtime Key 最长能用多久。铸造端只接受 90 天以内的到期时间：
# 「十年有效的钥匙」等于没有到期时间，出事时用户没有任何兜底。
MAX_KEY_LIFETIME_DAYS = 90

# 这些权限会动钱 / 会替主人拍板 —— 对应的 key 每请求强制带 nonce 并做重放检查。
NONCE_REQUIRED_PERMISSIONS = frozenset({"place_order", "request_settlement"})

# agent 请求签名的时间戳容忍窗口（秒）。超出直接 401，配合 nonce 去重拦住重放。
AGENT_SIGNATURE_TOLERANCE_SECONDS = 300

# 匹配码：agent 申请接入后拿到这串码，用户看到它、在操作台手输一次，绑定才算生效。
# 字母表去掉了 0/O/1/I —— 这是要人念、人敲的码，形近字符只会制造事故。
BIND_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
# 码 3 分钟有效 —— 这就是全部的「激活窗口」：agent 申请接入、把码交到主人手里，
# 主人在操作台输对码才算激活。没输对 / 没来得及输，这次申请就作废（码没了，
# 重新申请一次即可，不用重铸钥匙）。
BIND_CODE_TTL_SECONDS = 180
BIND_CODE_MAX_ATTEMPTS = 5

# 铸造时就写明「这把钥匙是给某个 agent 的」时落到这个状态。
# 它和 "agent"（公钥已绑、逐请求验签）是两回事：这个状态下 key 字符串还是不记名
# 令牌 —— 谁抄到都能花。所以只要 key_binding=agent_pending 且还没绑上公钥，
# 动钱的调用一律拒绝（见 api/routes/runtime_gateway.py 的 get_runtime_context）。
PENDING_KEY_BINDING = "agent_pending"

# In-process replay / idempotency (single worker — use Redis in multi-instance production).
_replay: dict[str, deque[tuple[str, float]]] = defaultdict(deque)
_DAILY: dict[str, dict[str, float]] = defaultdict(dict)  # key_id -> iso_date -> cumulative amount


def _server_material() -> bytes:
    return (settings.app_secret_key + ":karma_runtime_key_v1").encode()


def hash_runtime_secret(*, key_id: str, secret: str) -> str:
    return hmac.new(_server_material(), f"{key_id}:{secret}".encode(), hashlib.sha256).hexdigest()


def verify_runtime_secret(*, key_id: str, secret: str, secret_hash: str) -> bool:
    expect = hash_runtime_secret(key_id=key_id, secret=secret)
    return hmac.compare_digest(expect, secret_hash)


def hash_binding_scope(scope: str) -> str:
    """「这把 key 授权给哪个 agent」这份声明的服务端指纹。

    声明本身是明文（要给 agent 和操作台看），指纹用来在回执 / 审计里做完整性比对：
    少一个字符就对不上，避免有人把 key 悄悄挪给另一个 agent。
    """
    return hmac.new(_server_material(), f"binding_scope:{scope}".encode(), hashlib.sha256).hexdigest()


def binding_scope(*, key_id: str, karma_identity_id: str, agent_id: str) -> str:
    """「这把 key 授权给这个 agent」的明文声明（agent 侧可校验、操作台可展示）。"""
    return "\n".join(
        [
            "Karma Runtime Key Binding",
            f"key_id:{key_id.strip()}",
            f"karma_identity_id:{karma_identity_id.strip()}",
            f"agent_id:{agent_id.strip()}",
        ]
    )


def new_activation_code() -> str:
    """生成 8 位匹配码，显示成 XXXX-XXXX（好念、好手输）。"""
    raw = "".join(secrets.choice(BIND_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_activation_code(value: str) -> str:
    """把用户手输的匹配码收敛成 8 位大写字母数字（容忍空格、连字符、小写）。"""
    compact = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    if len(compact) != 8 or any(ch not in BIND_CODE_ALPHABET for ch in compact):
        raise HTTPException(
            status_code=400,
            detail="activation code must be 8 characters (XXXX-XXXX)",
        )
    return compact


def display_activation_code(compact: str) -> str:
    """把 8 位紧凑码还原成给人看的 XXXX-XXXX。签名消息用这个形式。"""
    text = (compact or "").strip().upper()
    if len(text) == 8:
        return f"{text[:4]}-{text[4:]}"
    return text


def hash_activation_code(*, key_id: str, code: str) -> str:
    """匹配码只存 HMAC —— 库被看到也还原不出码，码只在 agent 手里。"""
    normalized = normalize_activation_code(code)
    return hmac.new(
        _server_material(), f"bind_code:{key_id}:{normalized}".encode(), hashlib.sha256
    ).hexdigest()


class PublicKeyError(ValueError):
    """agent 交上来的 Ed25519 公钥形状不对。"""


def normalize_agent_public_key(value: str) -> str:
    """把 agent 公钥收敛成 canonical base64(raw 32 bytes)。

    只认 32 字节裸公钥：base64（44 字符）或 64 位 hex。PEM、带前缀的写法一律拒绝，
    免得同一把钥匙有两种解读，让验签结果变成「看谁写的解析器」。
    """
    text = (value or "").strip()
    if not text:
        raise PublicKeyError("agent_public_key is required")
    compact = "".join(text.split())
    if compact[:2].lower() == "0x":
        compact = compact[2:]
    digest: bytes
    if len(compact) == 64 and all(c in "0123456789abcdefABCDEF" for c in compact):
        digest = bytes.fromhex(compact)
    else:
        try:
            digest = base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PublicKeyError("agent_public_key must be base64 or hex") from exc
    if len(digest) != 32:
        raise PublicKeyError(f"agent_public_key must decode to 32 bytes, got {len(digest)}")
    return base64.b64encode(digest).decode()


def agent_binding_fingerprint(agent_public_key: str) -> str:
    """公钥指纹（前 16 位给用户在操作台肉眼对照）。"""
    raw = base64.b64decode(normalize_agent_public_key(agent_public_key), validate=True)
    return hashlib.sha256(raw).hexdigest()[:32]


def is_nonce_required(permissions: Iterable[str]) -> bool:
    """会动钱的权限必须逐请求带 nonce —— 光有签名挡不住原样重放。"""
    return bool(NONCE_REQUIRED_PERMISSIONS.intersection(permissions or []))


def parse_runtime_key_token(token: str) -> tuple[str, str]:
    raw = (token or "").strip()
    if not raw.startswith("KRM_RT_"):
        raise HTTPException(status_code=401, detail="invalid runtime key format")
    rest = raw[len("KRM_RT_") :]
    try:
        sep = rest.index("_")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid runtime key format") from exc
    key_id, secret = rest[:sep], rest[sep + 1 :]
    if len(key_id) != 32 or not all(c in "0123456789abcdef" for c in key_id.lower()):
        raise HTTPException(status_code=401, detail="invalid runtime key id segment")
    if len(secret) != 64 or not all(c in "0123456789abcdef" for c in secret.lower()):
        raise HTTPException(status_code=401, detail="invalid runtime key secret segment")
    return key_id, secret.lower()


def normalize_permissions(perms: Iterable[str]) -> list[str]:
    out = sorted({p.strip() for p in perms if (p or "").strip()})
    for p in out:
        if p not in ALLOWED_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"unknown or disallowed permission: {p}")
    if not out:
        raise HTTPException(status_code=400, detail="permissions must be a non-empty subset of allowed scopes")
    return out


def assert_permission(ctx: "RuntimeKeyContext", permission: str) -> None:
    if permission not in ctx.permissions:
        raise HTTPException(status_code=403, detail=f"runtime key missing permission: {permission}")


def check_replay_nonce(*, key_id: str, endpoint: str, nonce: str, ttl_seconds: int = 600) -> None:
    if not nonce or len(nonce) > 128:
        raise HTTPException(status_code=400, detail="client_nonce is required (max 128 chars)")
    bucket = _replay[key_id]
    now = time.monotonic()
    while bucket and now - bucket[0][1] > ttl_seconds:
        bucket.popleft()
    tag = f"{endpoint}:{nonce}"
    if any(existing == tag for existing, _ in bucket):
        raise HTTPException(status_code=409, detail="duplicate client_nonce (replay protection)")
    bucket.append((tag, now))
    while len(bucket) > 2000:
        bucket.popleft()


def check_single_and_daily_limits(
    *,
    key_id: str,
    amount: float,
    single_limit: float,
    daily_limit: float,
    daily_used: float | None = None,
) -> None:
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if amount > single_limit + 1e-9:
        raise HTTPException(status_code=403, detail="amount exceeds runtime key single_limit")
    today = date.today().isoformat()
    used = float(daily_used) if daily_used is not None else float(_DAILY[key_id].get(today, 0.0))
    if used + amount > daily_limit + 1e-9:
        raise HTTPException(status_code=403, detail="amount exceeds runtime key daily_limit")


def record_daily_spend(*, key_id: str, amount: float) -> None:
    today = date.today().isoformat()
    _DAILY[key_id][today] = _DAILY[key_id].get(today, 0.0) + amount


def get_daily_used(key_id: str) -> float:
    today = date.today().isoformat()
    return float(_DAILY.get(key_id, {}).get(today, 0.0))


@dataclass
class RuntimeKeyContext:
    key_id: str
    karma_identity_id: str
    profile_id: str | None
    wallet_address: str
    permissions: list[str]
    single_limit: float
    daily_limit: float
    expire_at: datetime
    agent_name: str
    status: str
    agent_binding: str | None = None
    # service = 老路径（服务端托管，认 key 不认人）；agent = 已绑定 agent 公钥，逐请求验签。
    key_binding: str = "service"
    agent_public_key: str | None = None
    nonce_required: bool = False
    created_at: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_key_lifetime_sane(expire_at: datetime, *, now: datetime | None = None) -> datetime:
    """到期时间必须落在未来 90 天以内。

    旧代码不检查，操作台能铸出 10 年有效的钥匙 —— 那等于没有到期时间，
    用户想收回只能靠吊销，而这把钥匙已经在外面了。
    """
    exp = _as_utc(expire_at)
    current = _as_utc(now or _utcnow())
    if exp <= current:
        raise HTTPException(status_code=400, detail="expire_time must be in the future")
    if exp - current > timedelta(days=MAX_KEY_LIFETIME_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"expire_time must be within {MAX_KEY_LIFETIME_DAYS} days",
        )
    return exp


def _canonical_signature_timestamp(raw: str) -> tuple[datetime, str]:
    """解析 agent 传来的时间戳，并给出签名用的规范化字符串。

    规范化成 YYYY-MM-DDTHH:MM:SSZ，这样 Z / +00:00 / 带毫秒三种写法都能对上，
    不会因为序列化差异把正确签名判成错的。
    """
    text = (raw or "").strip()
    if not text:
        raise HTTPException(
            status_code=401,
            detail="X-Karma-Runtime-Timestamp header is required for signed requests",
        )
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise HTTPException(
            status_code=401, detail="X-Karma-Runtime-Timestamp must be ISO-8601"
        ) from exc
    utc = _as_utc(parsed)
    return utc, utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_signed_request(
    *,
    ctx: "RuntimeKeyContext",
    method: str,
    path: str,
    body: bytes,
    signature_b64: str | None,
    timestamp_header: str | None,
    nonce_header: str | None,
) -> None:
    """已绑定公钥的 key：每个请求都要带签名 + 时间戳 + nonce。

    这是「使用时刻硬校验」：key 字符串本身不再是通行证，签名对上才算数。
    没绑公钥的老 key 直接放行（行为与升级前完全一致）；但如果老 key 带了签名，
    说明调用方搞错了对象，回报 403 而不是静默忽略。
    """
    sig = (signature_b64 or "").strip()
    if not ctx.agent_public_key:
        if sig:
            raise HTTPException(
                status_code=403,
                detail="runtime key has no bound agent public key; call /runtime/bind-key first",
            )
        return
    from services.runtime_wallet import build_agent_request_message

    if not sig:
        raise HTTPException(
            status_code=401,
            detail="X-Karma-Agent-Signature header is required for this runtime key",
        )
    sent_at, canonical_ts = _canonical_signature_timestamp(timestamp_header or "")
    if abs((_utcnow() - sent_at).total_seconds()) > AGENT_SIGNATURE_TOLERANCE_SECONDS:
        raise HTTPException(
            status_code=401,
            detail="X-Karma-Runtime-Timestamp is outside the accepted window",
        )
    nonce = (nonce_header or "").strip()
    if not nonce or len(nonce) > 128:
        raise HTTPException(
            status_code=401,
            detail="X-Karma-Runtime-Nonce header is required for signed requests (max 128 chars)",
        )
    message = build_agent_request_message(
        key_id=ctx.key_id,
        method=method,
        path=path,
        timestamp=canonical_ts,
        nonce=nonce,
        body_sha256=hashlib.sha256(body or b"").hexdigest(),
    )
    from services.signing import signing_service

    if not signing_service.verify(message.encode("utf-8"), sig, ctx.agent_public_key):
        raise HTTPException(status_code=401, detail="agent request signature verification failed")
    # 签名过了才记 nonce：错签不该把 nonce 烧掉。
    check_replay_nonce(key_id=ctx.key_id, endpoint=path, nonce=nonce)


async def load_active_context(
    *,
    db: AsyncSession,
    token: str,
    require_signature: bool = False,
) -> RuntimeKeyContext:
    key_id, secret = parse_runtime_key_token(token)
    row = await db.get(RuntimeKeyModel, key_id)
    if not row or row.status != "active":
        raise HTTPException(status_code=401, detail="invalid or revoked runtime key")
    if not verify_runtime_secret(key_id=key_id, secret=secret, secret_hash=row.secret_hash):
        raise HTTPException(status_code=401, detail="invalid runtime key")
    exp = _as_utc(row.expire_at)
    if _utcnow() > exp + timedelta(seconds=30):
        raise HTTPException(status_code=401, detail="runtime key expired")
    if require_signature and not (row.agent_public_key or "").strip():
        raise HTTPException(
            status_code=401,
            detail="runtime key is not bound to an agent public key; call /runtime/bind-key first",
        )
    return RuntimeKeyContext(
        key_id=row.key_id,
        karma_identity_id=row.karma_identity_id,
        profile_id=row.profile_id,
        wallet_address=row.wallet_address,
        permissions=list(row.permissions or []),
        single_limit=float(row.single_limit),
        daily_limit=float(row.daily_limit),
        expire_at=exp,
        agent_name=row.agent_name,
        status=row.status,
        agent_binding=row.agent_binding,
        key_binding=(row.key_binding or "service"),
        agent_public_key=(row.agent_public_key or None),
        nonce_required=bool(row.nonce_required),
        created_at=_as_utc(row.created_at) if row.created_at else None,
    )


async def create_runtime_key_record(
    *,
    db: AsyncSession,
    wallet_address: str,
    karma_identity_id: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
    expire_at: datetime,
    agent_name: str,
    agent_binding: str | None,
    profile_id: str | None = None,
    key_binding: str = "service",
    agent_public_key: str | None = None,
) -> tuple[str, RuntimeKeyModel]:
    if single_limit <= 0 or daily_limit <= 0:
        raise HTTPException(status_code=400, detail="single_limit and daily_limit must be > 0")
    if daily_limit + 1e-9 < single_limit:
        raise HTTPException(status_code=400, detail="daily_limit must be >= single_limit")
    perms = normalize_permissions(permissions)
    expire_at = assert_key_lifetime_sane(expire_at)
    binding_mode = (key_binding or "service").strip().lower()
    if binding_mode not in {"service", "agent"}:
        raise HTTPException(status_code=400, detail="key_binding must be 'service' or 'agent'")
    pub = normalize_agent_public_key(agent_public_key) if agent_public_key else None
    if binding_mode == "agent" and not pub:
        raise HTTPException(status_code=400, detail="key_binding=agent requires agent_public_key")
    # 铸造时就指明了收件 agent（agent_binding 在钱包签名消息里）—— 这把钥匙
    # 不该在激活前被任何人拿去花。以前它和托管钥匙一样「认 key 不认人」，
    # 铸造到激活之间的窗口期里，抄到 key 的人就能直接用。现在锁死：
    # 钥匙先落到 agent_pending，激活（用户输匹配码）之后才变 agent。
    if binding_mode == "service" and (agent_binding or "").strip():
        binding_mode = PENDING_KEY_BINDING
    key_id = secrets.token_hex(16)
    secret = secrets.token_hex(32)
    token = f"KRM_RT_{key_id}_{secret}"
    sh = hash_runtime_secret(key_id=key_id, secret=secret)
    row = RuntimeKeyModel(
        key_id=key_id,
        secret_hash=sh,
        wallet_address=wallet_address.strip(),
        karma_identity_id=karma_identity_id.strip(),
        profile_id=(profile_id or "").strip() or None,
        permissions=perms,
        single_limit=single_limit,
        daily_limit=daily_limit,
        expire_at=expire_at,
        agent_name=agent_name.strip() or "agent",
        agent_binding=(agent_binding or "").strip() or None,
        key_binding=binding_mode,
        agent_public_key=pub,
        nonce_required=is_nonce_required(perms),
        status="active",
    )
    db.add(row)
    await db.flush()
    return token, row


async def _load_activatable_row(db: AsyncSession, key_id: str) -> RuntimeKeyModel:
    row = await db.get(RuntimeKeyModel, key_id)
    if not row or row.status != "active":
        raise HTTPException(status_code=401, detail="invalid or revoked runtime key")
    if _utcnow() > _as_utc(row.expire_at) + timedelta(seconds=30):
        raise HTTPException(status_code=401, detail="runtime key expired")
    return row


def pending_activation_block(
    *, key_binding: str | None, agent_public_key: str | None
) -> str | None:
    """未激活的 agent 专用钥匙：该拒就回一串给调用方看的理由，不该拒回 None。

    没有时间维度：这把钥匙只要没激活就一律不能用，直到主人输了码（变成 agent）
    或者干脆吊销。时间只作用在**匹配码**上（BIND_CODE_TTL_SECONDS = 3 分钟）：
    码过期就是这次申请作废，agent 重新申请一次即可，钥匙本身不受影响。
    这是「未激活不能用」的唯一判定口径，网关和测试都走这里，避免两处漂移。
    """
    if (key_binding or "service").strip().lower() != PENDING_KEY_BINDING:
        return None
    if (agent_public_key or "").strip():
        return None
    return (
        "runtime key is not activated yet: the agent must POST /runtime/bind-key "
        "and the owner must enter the 8-character activation code in Console "
        "(valid for %d minutes) before this key can be used" % (BIND_CODE_TTL_SECONDS // 60)
    )


def _clear_pending_binding(row: RuntimeKeyModel) -> None:
    row.pending_agent_public_key = None
    row.pending_code_hash = None
    row.pending_expires_at = None
    row.pending_attempts = 0
    row.pending_requested_at = None


def pending_binding_view(row: RuntimeKeyModel) -> dict | None:
    """待确认的接入请求（给操作台展示、给 agent 轮询）。没有就返回 None。"""
    pub = (row.pending_agent_public_key or "").strip()
    if not pub:
        return None
    expires = _as_utc(row.pending_expires_at) if row.pending_expires_at else None
    return {
        "key_id": row.key_id,
        "agent_id": row.agent_binding,
        "agent_public_key": pub,
        "agent_fingerprint": agent_binding_fingerprint(pub),
        "expires_at": expires.isoformat() if expires else None,
        "expired": bool(expires and _utcnow() > expires),
        "attempts_left": max(0, BIND_CODE_MAX_ATTEMPTS - int(row.pending_attempts or 0)),
    }


async def request_key_binding(
    *,
    db: AsyncSession,
    key_id: str,
    agent_id: str,
    agent_public_key: str,
) -> tuple[RuntimeKeyModel, str, str]:
    """agent 申请接入：先拿到匹配码，绑定**还没生效**。

    返回 (row, activation_code, status)。status 为 active 表示这把 key 早就绑在
    同一把公钥上了（幂等重放，不发新码）；否则是 pending_activation。
    只有用户在操作台输入这个码（``confirm_key_binding``）之后，绑定才真正落地 ——
    所以「偷到 key 的人抢先把自己的公钥绑上」这条路走不通：他没有用户手里的码。
    """
    row = await _load_activatable_row(db, key_id)
    declared = (agent_id or "").strip()
    if not declared:
        raise HTTPException(status_code=400, detail="agent_id is required")
    bound = (row.agent_binding or "").strip()
    if bound and bound != declared:
        raise HTTPException(status_code=403, detail="runtime key was minted for a different agent")
    pub = normalize_agent_public_key(agent_public_key)
    current = (row.agent_public_key or "").strip()
    if current and current != pub:
        raise HTTPException(
            status_code=409,
            detail="runtime key is already bound to another agent public key; revoke and mint a new key",
        )
    if current and current == pub:
        _clear_pending_binding(row)
        await db.flush()
        return row, "", "active"
    code = new_activation_code()
    row.pending_agent_public_key = pub
    row.pending_code_hash = hash_activation_code(key_id=row.key_id, code=code)
    row.pending_expires_at = _utcnow() + timedelta(seconds=BIND_CODE_TTL_SECONDS)
    row.pending_attempts = 0
    row.pending_requested_at = _utcnow()
    await db.flush()
    return row, code, "pending_activation"


async def confirm_key_binding(*, db: AsyncSession, key_id: str, code: str) -> RuntimeKeyModel:
    """用户在操作台输入匹配码 —— 到这一步绑定才生效。"""
    row = await _load_activatable_row(db, key_id)
    pub = (row.pending_agent_public_key or "").strip()
    if not pub:
        raise HTTPException(status_code=409, detail="no pending bind request for this runtime key")
    expires = _as_utc(row.pending_expires_at) if row.pending_expires_at else _utcnow()
    if _utcnow() > expires:
        _clear_pending_binding(row)
        await db.flush()
        raise HTTPException(
            status_code=410,
            detail="the activation code expired — ask the agent to request a new one",
        )
    # 扣一次试错机会必须是原子的：“读出来 +1 再写回”会被并发的请求读到同一个旧值，
    # 8 个并发错码实测只扣掉 3 次机会，5 次上限形同虚设。
    # 这里用带条件的 UPDATE 原子扣次数：更新 0 行 = 机会已经用光。
    consumed = await db.execute(
        update(RuntimeKeyModel)
        .where(
            RuntimeKeyModel.key_id == key_id,
            func.coalesce(RuntimeKeyModel.pending_attempts, 0) < BIND_CODE_MAX_ATTEMPTS,
            RuntimeKeyModel.pending_code_hash.is_not(None),
        )
        .values(pending_attempts=func.coalesce(RuntimeKeyModel.pending_attempts, 0) + 1)
        # 不让 ORM 去同步这行：它会把会话里的对象置成 expired，
        # 后面序列化再读就会撞到异步懒加载。
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        _clear_pending_binding(row)
        await db.flush()
        raise HTTPException(
            status_code=429,
            detail="too many wrong activation codes — ask the agent to request a new one",
        )
    given = hash_activation_code(key_id=row.key_id, code=code)
    if not hmac.compare_digest(given, row.pending_code_hash or ""):
        # 次数已经在上面那条 UPDATE 里叠上了，不能再在 ORM 里加一次。
        raise HTTPException(status_code=403, detail="activation code does not match")
    row.agent_public_key = pub
    row.key_binding = "agent"
    row.nonce_required = is_nonce_required(list(row.permissions or []))
    _clear_pending_binding(row)
    await db.flush()
    return row


async def reject_key_binding(*, db: AsyncSession, key_id: str) -> RuntimeKeyModel:
    """用户拒绝这次接入：清掉待确认状态，key 保持原样。"""
    row = await _load_activatable_row(db, key_id)
    if not (row.pending_agent_public_key or "").strip():
        raise HTTPException(status_code=409, detail="no pending bind request for this runtime key")
    _clear_pending_binding(row)
    await db.flush()
    return row


async def unbind_key_binding(*, db: AsyncSession, key_id: str) -> RuntimeKeyModel:
    """主人在操作台一键取消绑定：把 agent 公钥摘掉，钥匙回到「未激活」。

    为什么不退回托管（service）：那样等于把钥匙变回不记名令牌 —— 谁抄到谁花，
    而用户点这个按钮的意思正是「别再让那个 agent 代表我花钱」。摘掉公钥之后
    这把钥匙谁都花不了，要用就重新走一次激活（agent 再申请一次、主人再输码）。
    """
    row = await _load_activatable_row(db, key_id)
    if not (row.agent_public_key or "").strip():
        raise HTTPException(status_code=409, detail="this runtime key has no bound agent")
    row.agent_public_key = None
    row.key_binding = PENDING_KEY_BINDING
    row.nonce_required = False
    _clear_pending_binding(row)
    await db.flush()
    return row


async def revoke_runtime_key(
    *,
    db: AsyncSession,
    key_id: str,
) -> RuntimeKeyModel | None:
    row = await db.get(RuntimeKeyModel, key_id)
    if not row:
        return None
    if row.status == "active":
        row.status = "revoked"
        row.revoked_at = datetime.utcnow()
        await db.flush()
    return row


async def list_bound_runtime_keys(
    *, db: AsyncSession, karma_identity_id: str
) -> list[RuntimeKeyModel]:
    """这把身份下「已经绑了 agent 公钥」的钥匙 —— 设置页据此给一键取消绑定。"""
    rows = await list_runtime_keys_for_identity(db=db, karma_identity_id=karma_identity_id)
    return [r for r in rows if (r.agent_public_key or "").strip()]


async def list_runtime_keys_for_identity(
    *,
    db: AsyncSession,
    karma_identity_id: str,
) -> list[RuntimeKeyModel]:
    res = await db.execute(
        select(RuntimeKeyModel)
        .where(RuntimeKeyModel.karma_identity_id == karma_identity_id)
        .order_by(RuntimeKeyModel.created_at.desc())
    )
    return list(res.scalars().all())
