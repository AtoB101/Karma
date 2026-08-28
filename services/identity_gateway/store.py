"""Karma Identity store for MiniApp MVP (内存 + JSON 落盘，重启不丢认证绑定).

支持子身份体系：主账号认证后可生成子身份绑独立钱包地址，
所有消费由主身份承担。Bot 同步时只需回溯子→主即可读取 payment_policy。
"""
from __future__ import annotations

import secrets
import time
from dataclasses import asdict, dataclass, field
from threading import RLock

from services import persist_json
from services.identity_gateway import state_machine


# 三类身份：自然人 / 企业商家 / Agent 主体
IDENTITY_CLASS_USER = "user"
IDENTITY_CLASS_BUSINESS = "business"
IDENTITY_CLASS_AGENT = "agent"
IDENTITY_CLASSES = {IDENTITY_CLASS_USER, IDENTITY_CLASS_BUSINESS, IDENTITY_CLASS_AGENT}

# 凭证类型白名单（可扩展；值本身不落库，仅落验证结果 —— 最小披露）
CREDENTIAL_TYPES = {
    "email", "phone", "wallet", "domain", "business_reg", "telegram", "twofa",
}

# 身份验证等级（由已验证凭证推导，不直接写）
VERIFICATION_UNVERIFIED = "unverified"
VERIFICATION_BASIC = "basic"
VERIFICATION_ENHANCED = "enhanced"


@dataclass
class KarmaIdentity:
    identity_id: str
    wallet: str
    status: str = "active"
    created_at: int = 0
    telegram_user_id: int | None = None
    telegram_username: str | None = None
    business_id: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    payment_policy: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # 子身份体系
    parent_identity_id: str | None = None       # None = 主身份
    sub_identity_ids: list[str] = field(default_factory=list)

    # 邀请与积分
    invite_code: str = ""
    referred_by: str | None = None              # 邀请人 invite_code
    karma_points: float = 0.0

    # 2FA 快速绑定（Bot 端同步认证用）
    twofa_code: str = ""

    # ── 身份底座 v2：三类身份 + 凭证链 ──
    identity_class: str = IDENTITY_CLASS_USER
    verification_status: str = VERIFICATION_UNVERIFIED
    credentials: list[dict] = field(default_factory=list)   # 凭证记录（不含明文）


_LOCK = RLock()   # 可重入：bind_by_2fa 持锁时内部再调用 issue/verify
_BY_ID: dict[str, KarmaIdentity] = {}
_BY_WALLET: dict[str, str] = {}
_BY_TG: dict[int, str] = {}
_BY_INVITE: dict[str, str] = {}


def _new_id() -> str:
    return "kid_" + secrets.token_hex(12)


def _new_invite_code() -> str:
    """8 位邀请码，大写字母+数字。"""
    import string
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _persist() -> None:
    persist_json.save("identities", {"identities": [asdict(i) for i in _BY_ID.values()]})


def _load() -> None:
    for d in persist_json.load("identities").get("identities", []):
        try:
            ident = KarmaIdentity(**d)
        except TypeError:
            continue
        _BY_ID[ident.identity_id] = ident
        _BY_WALLET[ident.wallet] = ident.identity_id
        if ident.telegram_user_id is not None:
            _BY_TG[int(ident.telegram_user_id)] = ident.identity_id
        if ident.invite_code:
            _BY_INVITE[ident.invite_code] = ident.identity_id


_load()


def _reindex_tg(ident: KarmaIdentity) -> None:
    if ident.telegram_user_id is not None:
        _BY_TG[int(ident.telegram_user_id)] = ident.identity_id


def _reindex_wallet(ident: KarmaIdentity) -> None:
    _BY_WALLET[ident.wallet] = ident.identity_id


def _reindex_invite(ident: KarmaIdentity) -> None:
    if ident.invite_code:
        _BY_INVITE[ident.invite_code] = ident.identity_id


def get_or_create_by_wallet(wallet: str, **meta) -> KarmaIdentity:
    w = wallet.lower()
    with _LOCK:
        existing = _BY_WALLET.get(w)
        if existing and existing in _BY_ID:
            return _BY_ID[existing]
        identity_id = _new_id()
        ident = KarmaIdentity(
            identity_id=identity_id,
            wallet=w,
            created_at=int(time.time()),
            metadata=dict(meta),
            invite_code=_new_invite_code(),
            payment_policy={
                "mode": "manual_confirm",
                "single_limit_usdc": "500",
                "daily_limit_usdc": "2000",
                "allowed_categories": [],
                "allowed_agents": [],
                "emergency_revoke": False,
            },
        )
        _BY_ID[identity_id] = ident
        _reindex_wallet(ident)
        _reindex_invite(ident)
        _persist()
        return ident


def get_by_id(identity_id: str) -> KarmaIdentity | None:
    with _LOCK:
        return _BY_ID.get(identity_id)


def get_by_wallet(wallet: str) -> KarmaIdentity | None:
    with _LOCK:
        iid = _BY_WALLET.get(wallet.lower())
        return _BY_ID.get(iid) if iid else None


def get_by_telegram(telegram_user_id: int) -> KarmaIdentity | None:
    with _LOCK:
        iid = _BY_TG.get(int(telegram_user_id))
        return _BY_ID.get(iid) if iid else None


def get_by_invite_code(code: str) -> KarmaIdentity | None:
    with _LOCK:
        iid = _BY_INVITE.get(code.strip().upper())
        return _BY_ID.get(iid) if iid else None


def resolve_main_identity(identity_id: str) -> KarmaIdentity | None:
    """从子身份回溯到主身份；主身份返回自身。"""
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            return None
        if ident.parent_identity_id:
            return _BY_ID.get(ident.parent_identity_id) or ident
        return ident


def resolve_effective_identity(telegram_user_id: int) -> KarmaIdentity | None:
    """TG 用户 → 绑定的身份（可能是子身份）→ 回溯到主身份。

    Bot 后端用此函数读取 payment_policy、额度、积分——
    子身份在 Bot 端的交互全部走主身份状态机。
    """
    with _LOCK:
        iid = _BY_TG.get(int(telegram_user_id))
        if not iid:
            return None
        ident = _BY_ID.get(iid)
        if not ident:
            return None
        if ident.parent_identity_id:
            main = _BY_ID.get(ident.parent_identity_id)
            return main or ident
        return ident


def create_sub_identity(parent_identity_id: str, wallet: str) -> KarmaIdentity:
    """主身份生成子身份，绑定独立钱包地址；消费由主身份承担。"""
    w = wallet.lower()
    with _LOCK:
        parent = _BY_ID.get(parent_identity_id)
        if not parent:
            raise KeyError("parent identity not found")
        if parent.parent_identity_id:
            raise ValueError("sub-identity cannot create sub-identities")
        if len(parent.sub_identity_ids) >= 2:
            raise ValueError("max 2 sub-identities allowed")
        if w in _BY_WALLET:
            raise ValueError("wallet already bound to another identity")
        identity_id = _new_id()
        ident = KarmaIdentity(
            identity_id=identity_id,
            wallet=w,
            created_at=int(time.time()),
            parent_identity_id=parent_identity_id,
            invite_code=_new_invite_code(),
            referred_by=parent.invite_code or None,
            payment_policy=dict(parent.payment_policy),  # 继承主身份额度策略
            metadata={"role": "sub", "parent": parent_identity_id},
        )
        _BY_ID[identity_id] = ident
        _reindex_wallet(ident)
        _reindex_invite(ident)
        parent.sub_identity_ids.append(identity_id)
        _persist()
        return ident


def bind_telegram(identity_id: str, *, telegram_user_id: int, username: str | None = None) -> KarmaIdentity:
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        # one TG → one identity
        prev = _BY_TG.get(int(telegram_user_id))
        if prev and prev != identity_id:
            raise ValueError("telegram already bound to another identity")
        ident.telegram_user_id = int(telegram_user_id)
        ident.telegram_username = username
        _reindex_tg(ident)
        _persist()
        return ident


def bind_by_2fa(telegram_user_id: int, identity_id: str, twofa_code: str, *, username: str | None = None) -> KarmaIdentity:
    """Bot 端快速同步认证：主身份ID + 2FA 安全码 → 绑定 TG。

    允许换绑（测试/多身份场景）：先解除该 TG 之前的绑定。
    """
    with _LOCK:
        ident = _BY_ID.get(identity_id.strip())
        if not ident:
            raise KeyError("身份ID不存在")
        if not ident.twofa_code:
            raise ValueError("2FA 安全码已焚毁，请重新获取")
        # 常量时间比较，防时序侧信道
        if not secrets.compare_digest(ident.twofa_code, twofa_code.strip()):
            raise ValueError("2FA 安全码错误")
        # 解除该 TG 之前的绑定（换绑）
        prev_iid = _BY_TG.get(int(telegram_user_id))
        if prev_iid and prev_iid != ident.identity_id:
            prev = _BY_ID.get(prev_iid)
            if prev:
                prev.telegram_user_id = None
                prev.telegram_username = None
        ident.telegram_user_id = int(telegram_user_id)
        ident.telegram_username = username
        # 一次性安全码：认证成功立即焚毁明文
        ident.twofa_code = ""
        _reindex_tg(ident)
        # 认证事件进入状态机：自动签发并验证 telegram 凭证
        state_machine.record_event(
            "identity", ident.identity_id, "telegram_bind",
            from_state="unbound", to_state="telegram_bound",
            actor=f"tg:{telegram_user_id}", reason="2fa bind success",
        )
        for c in ident.credentials:
            if c["type"] == "telegram" and c["status"] in (
                state_machine.CREDENTIAL_STATE_PENDING,
                state_machine.CREDENTIAL_STATE_VERIFIED,
            ):
                _mutate_credential_locked(
                    ident, c, "revoke",
                    actor=f"tg:{telegram_user_id}", reason="re-bind replaces old telegram credential",
                )
                break
        issue_credential(
            ident.identity_id, "telegram",
            actor=f"tg:{telegram_user_id}", auto_verify=True,
        )
        _persist()
        return ident


def seed_identity(
    identity_id: str,
    wallet: str,
    *,
    twofa_code: str,
    payment_policy: dict | None = None,
    karma_points: float = 0.0,
) -> KarmaIdentity:
    """种子/测试身份：指定 ID 与 2FA 码（幂等：已存在则更新 2FA）。"""
    w = wallet.lower()
    with _LOCK:
        existing = _BY_ID.get(identity_id)
        if existing:
            existing.twofa_code = twofa_code
            _persist()
            return existing
        ident = KarmaIdentity(
            identity_id=identity_id,
            wallet=w,
            created_at=int(time.time()),
            invite_code=_new_invite_code(),
            twofa_code=twofa_code,
            karma_points=karma_points,
            payment_policy=payment_policy or {
                "mode": "manual_confirm",
                "single_limit_usdc": "500",
                "daily_limit_usdc": "2000",
                "allowed_categories": [],
                "allowed_agents": [],
                "emergency_revoke": False,
            },
        )
        _BY_ID[identity_id] = ident
        _reindex_wallet(ident)
        _reindex_invite(ident)
        _persist()
        return ident


def update_policy(identity_id: str, policy: dict) -> KarmaIdentity:
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        # Never allow infinite approve semantics
        if policy.get("infinite_approve") is True:
            raise ValueError("infinite USDC approve is forbidden")
        merged = {**ident.payment_policy, **policy}
        merged["infinite_approve"] = False
        ident.payment_policy = merged
        _persist()
        return ident


def add_karma_points(identity_id: str, points: float) -> KarmaIdentity | None:
    """增加积分（结算奖励、邀请奖励等）。子身份积分计入主身份。"""
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            return None
        target = ident
        if ident.parent_identity_id:
            target = _BY_ID.get(ident.parent_identity_id) or ident
        target.karma_points = round(target.karma_points + points, 2)
        _persist()
        return target


def get_sub_identities(parent_identity_id: str) -> list[KarmaIdentity]:
    with _LOCK:
        parent = _BY_ID.get(parent_identity_id)
        if not parent:
            return []
        return [_BY_ID[sid] for sid in parent.sub_identity_ids if sid in _BY_ID]


def get_referral_chain(identity_id: str) -> list[KarmaIdentity]:
    """获取通过我的邀请码注册的下级用户。"""
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident or not ident.invite_code:
            return []
        return [
            i for i in _BY_ID.values()
            if i.referred_by == ident.invite_code and i.identity_id != identity_id
        ]


def _recompute_verification_status_locked(ident: KarmaIdentity) -> None:
    """由已验证凭证推导身份验证等级：

    - basic:    ≥1 个 verified 凭证
    - enhanced: ≥3 个不同类型 verified 凭证且含 wallet
    """
    verified_types = {
        c["type"] for c in ident.credentials
        if c.get("status") == state_machine.CREDENTIAL_STATE_VERIFIED
    }
    if len(verified_types) >= 3 and "wallet" in verified_types:
        ident.verification_status = VERIFICATION_ENHANCED
    elif verified_types:
        ident.verification_status = VERIFICATION_BASIC
    else:
        ident.verification_status = VERIFICATION_UNVERIFIED


def _find_credential_locked(ident: KarmaIdentity, credential_id: str) -> dict | None:
    for c in ident.credentials:
        if c.get("credential_id") == credential_id:
            return c
    return None


def issue_credential(
    identity_id: str,
    cred_type: str,
    *,
    issuer: str = "karma",
    ttl_seconds: int = 0,
    actor: str = "system",
    auto_verify: bool = False,
) -> dict:
    """签发凭证（pending）。原始材料不落库 —— 只有验证结果。"""
    if cred_type not in CREDENTIAL_TYPES:
        raise ValueError(f"unsupported credential type: {cred_type}")
    if ttl_seconds < 0 or ttl_seconds > 10 * 365 * 86400:
        raise ValueError("ttl_seconds out of range")
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        # 同类型凭证不允许并存 pending/verified（先吊销旧的再发新的）
        existing = [
            c for c in ident.credentials
            if c["type"] == cred_type
            and c["status"] in (
                state_machine.CREDENTIAL_STATE_PENDING,
                state_machine.CREDENTIAL_STATE_VERIFIED,
            )
        ]
        if existing:
            raise ValueError(f"credential of type {cred_type} already exists and is active")
        credential_id = "cred_" + secrets.token_hex(8)
        now = int(time.time())
        cred = {
            "credential_id": credential_id,
            "type": cred_type,
            "status": state_machine.CREDENTIAL_STATE_PENDING,
            "issuer": issuer[:64],
            "issued_at": now,
            "verified_at": None,
            "expires_at": now + ttl_seconds if ttl_seconds > 0 else None,
        }
        entry = state_machine.transition(
            "credential", credential_id, "", "issue",
            actor=actor, reason=f"issue {cred_type} for {identity_id}",
            extra={"identity_id": identity_id, "type": cred_type},
        )
        cred["status"] = entry["to_state"]
        ident.credentials.append(cred)
        _recompute_verification_status_locked(ident)
        _persist()
        if auto_verify:
            return _mutate_credential_locked(ident, cred, "verify", actor=actor, reason="verification passed")
        return cred


def _mutate_credential_locked(
    ident: KarmaIdentity, cred: dict, action: str, *, actor: str, reason: str,
) -> dict:
    """经状态机执行凭证迁移（调用方必须已持有 _LOCK）。"""
    entry = state_machine.transition(
        "credential", cred["credential_id"], cred["status"], action,
        actor=actor, reason=reason,
        extra={"identity_id": ident.identity_id, "type": cred["type"]},
    )
    cred["status"] = entry["to_state"]
    if action == "verify":
        cred["verified_at"] = int(time.time())
    _recompute_verification_status_locked(ident)
    _persist()
    return cred


def _mutate_credential(
    identity_id: str,
    credential_id: str,
    action: str,
    *,
    actor: str = "system",
    reason: str = "",
) -> dict:
    """经状态机执行凭证迁移（verify/reject/revoke/reissue/reverify/expire）。"""
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        cred = _find_credential_locked(ident, credential_id)
        if not cred:
            raise KeyError("credential not found")
        return _mutate_credential_locked(ident, cred, action, actor=actor, reason=reason)


def verify_credential(identity_id: str, credential_id: str, *, actor: str = "system") -> dict:
    return _mutate_credential(identity_id, credential_id, "verify", actor=actor, reason="verification passed")


def reject_credential(identity_id: str, credential_id: str, *, actor: str = "system", reason: str = "") -> dict:
    return _mutate_credential(identity_id, credential_id, "reject", actor=actor, reason=reason or "verification failed")


def revoke_credential(identity_id: str, credential_id: str, *, actor: str = "system", reason: str = "") -> dict:
    if not reason.strip():
        raise ValueError("revoke requires an explicit reason (audit trail)")
    return _mutate_credential(identity_id, credential_id, "revoke", actor=actor, reason=reason)


def expire_stale_credentials(identity_id: str) -> int:
    """把已到期的 verified 凭证推进 expired（幂等，可定时任务调用）。"""
    now = int(time.time())
    expired = 0
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            return 0
        for cred in ident.credentials:
            if (
                cred["status"] == state_machine.CREDENTIAL_STATE_VERIFIED
                and cred.get("expires_at") and cred["expires_at"] <= now
            ):
                entry = state_machine.transition(
                    "credential", cred["credential_id"], cred["status"], "expire",
                    actor="system", reason="ttl reached",
                    extra={"identity_id": identity_id, "type": cred["type"]},
                )
                cred["status"] = entry["to_state"]
                expired += 1
        if expired:
            _recompute_verification_status_locked(ident)
            _persist()
    return expired


def identity_card(identity_id: str, *, audience: str = "agent", scope: str = "basic") -> dict:
    """Karma Identity Card 聚合视图 —— 最小披露。

    只返回验证结果，绝不返回：2FA 明文、完整钱包地址、
    凭证原始材料。scope=basic 仅返回状态摘要；scope=full
    额外返回凭证列表（仍为脱敏摘要）。
    """
    ident = resolve_main_identity(identity_id)
    if not ident:
        raise KeyError("identity not found")
    if scope not in ("basic", "full"):
        raise ValueError("scope must be basic or full")
    # 到期检查先行（保证 Card 反映实时状态）
    expire_stale_credentials(ident.identity_id)

    card = {
        "card_version": "1",
        "identity_id": ident.identity_id,
        "identity_class": ident.identity_class,
        "status": ident.status,
        "verification_status": ident.verification_status,
        "verification_level": {
            "basic": ident.verification_status in (VERIFICATION_BASIC, VERIFICATION_ENHANCED),
            "enhanced": ident.verification_status == VERIFICATION_ENHANCED,
        },
        "telegram_bound": ident.telegram_user_id is not None,
        "wallet": _mask_wallet(ident.wallet),
        "risk_status": "normal" if ident.status == "active" else "restricted",
        "issued_at": int(time.time()),
    }
    if scope == "full":
        card["credentials"] = [
            {
                "credential_id": c["credential_id"],
                "type": c["type"],
                "status": c["status"],
                "verified_at": c.get("verified_at"),
                "expires_at": c.get("expires_at"),
            }
            for c in ident.credentials
        ]
        card["sub_identity_count"] = len(ident.sub_identity_ids)
    # 出示审计：谁在何时向谁出示了什么 scope
    state_machine.record_event(
        "identity", ident.identity_id, "card_presented",
        actor=audience[:64], reason=f"scope={scope}",
        extra={"scope": scope},
    )
    return card


def _mask_wallet(wallet: str) -> str:
    if len(wallet) <= 10:
        return wallet[:2] + "…"
    return f"{wallet[:6]}…{wallet[-4:]}"


def set_identity_class(identity_id: str, identity_class: str, *, actor: str = "system") -> KarmaIdentity:
    if identity_class not in IDENTITY_CLASSES:
        raise ValueError(f"invalid identity_class: {identity_class}")
    with _LOCK:
        ident = _BY_ID.get(identity_id)
        if not ident:
            raise KeyError("identity not found")
        if ident.identity_class != identity_class:
            state_machine.record_event(
                "identity", identity_id, "identity_class_changed",
                from_state=ident.identity_class, to_state=identity_class,
                actor=actor, reason="set_identity_class",
            )
            ident.identity_class = identity_class
            _persist()
        return ident


def reset_for_tests() -> None:
    with _LOCK:
        _BY_ID.clear()
        _BY_WALLET.clear()
        _BY_TG.clear()
        _BY_INVITE.clear()
        persist_json.delete("identities")
        state_machine.reset_for_tests()
