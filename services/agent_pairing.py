"""Agent self-service pairing (device-code style handshake).

A foreign agent asks to be connected, the wallet owner approves it in the
console, and the agent picks its credentials up by polling with the code it was
handed. Nobody copies a secret between two windows by hand.

Four codes live in a pairing record and they are **not** interchangeable:

``pairing_code``  held by the agent only; proves the poller is the same process
                  that opened the request. Returned once, at request time, and
                  persisted only as a SHA-256 hash.
``user_code``     short and human-typed (``K4QP-3M2X``) so the owner can match
                  the request on screen. Alone it grants nothing.
``handoff_code``  issued in the console by the owner and read off the screen
                  (``7P2K-9RVX``, 3 minutes). It travels owner -> agent — the
                  one direction a chat transcript *can* carry — which is
                  exactly why it must never be sufficient on its own: without
                  the agent's ``pairing_code`` it redeems nothing, and without
                  it the ``pairing_code`` redeems nothing either.
``delivery``      minted credentials, held server-side until the agent claims
                  them and wiped on claim — the one-shot rule the rest of the
                  platform already follows for bootstrap keys.

The two short codes are the two halves of one handshake, and they run in
opposite directions: at activation the agent shows *its* code to the owner, at
pairing the owner hands *theirs* to the agent. Neither half is a secret, so
nothing that ends up in a chat transcript or a screen recording is worth
stealing — the credentials themselves only ever move server -> agent.

Escrow of the pending payload is deliberate: Karma already custodies the
agent's Ed25519 signer server-side (``services/agent_key_store.py``), so a
short-lived, single-claim secret store is not a new class of custody.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

_STORE_PATH = Path(__file__).resolve().parents[1] / ".karma_data" / "agent_pairing.json"

#: How long the owner has to approve before the code dies on its own.
DEFAULT_TTL_SECONDS = 900
#: Console polls while waiting for approval.
POLL_INTERVAL_SECONDS = 3
#: One IP can have this many requests open at once (unauthenticated endpoint).
MAX_PENDING_PER_IP = 10
#: Hard cap on the store; oldest finished records are dropped first.
MAX_RECORDS = 500
#: No I/L/O/0/1: the owner may be reading this off a screen and typing it.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_USER_CODE_LEN = 8
#: 交接码：主人在操作台看到、亲手交给 agent 的那串码。和激活码一样 3 分钟。
HANDOFF_TTL_SECONDS = 180
#: 连猜错这么多次就把这次配对就地作废（8 位码 × 31 字符表，本来就猜不动）。
HANDOFF_MAX_ATTEMPTS = 5
_DEFAULT_BASE_URL = "https://karma-network.ai"

_LOCK = threading.Lock()
_LOADED = False
_RECORDS: dict[str, dict[str, Any]] = {}


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def client_bucket(ip: str) -> str:
    """Short digest of a client address — the per-IP cap does not need the raw IP."""
    raw = (ip or "").strip()
    return _sha256_hex(raw)[:32] if raw else ""


def normalize_requested_vertical(raw: str | None) -> str:
    """Map a vertical alias ("food") onto the catalog industry_id ("food_delivery").

    The console has to match the agent's request against its industry dropdown and
    render that industry's hard requirements, so the record stores the resolved
    industry_id. Aliases live in ``services/agent_one_click.py`` — the same table
    ``/v1/agents/owner-connect`` resolves against, so there is one answer, not two.
    An unknown value is kept as-is: the owner can still pick the industry by hand.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        from services.agent_one_click import VERTICAL_ALIASES
    except Exception:  # noqa: BLE001 - pairing must not fail on an import
        return value
    alias = VERTICAL_ALIASES.get(value.lower())
    if alias and alias.get("industry_id"):
        return str(alias["industry_id"])
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _RECORDS.update(
                        {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}
                    )
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(_RECORDS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(tmp, 0o600)
    except Exception:  # noqa: BLE001
        pass
    tmp.replace(_STORE_PATH)


def reset_pairings() -> None:
    """Test hook: forget every pairing, in memory and on disk."""
    global _LOADED
    with _LOCK:
        _RECORDS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def normalize_user_code(value: str) -> str:
    """``k4qp-3m2x`` / ``K4QP 3M2X`` / ``K4QP3M2X`` all mean the same code."""
    raw = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(raw) != _USER_CODE_LEN:
        return ""
    if any(ch not in _CODE_ALPHABET for ch in raw):
        return ""
    return raw[:4] + "-" + raw[4:]


def _user_code_key(user_code: str) -> str:
    return normalize_user_code(user_code).replace("-", "")


def _new_user_code() -> str:
    while True:
        body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_USER_CODE_LEN))
        code = body[:4] + "-" + body[4:]
        if _user_code_key(code) not in {_user_code_key(r.get("user_code", "")) for r in _RECORDS.values()}:
            return code


def normalize_handoff_code(value: str) -> str:
    """``7p2k-9rvx`` / ``7P2K 9RVX`` / ``7P2K9RVX`` 都是同一串码。"""
    raw = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(raw) != _USER_CODE_LEN:
        return ""
    if any(ch not in _CODE_ALPHABET for ch in raw):
        return ""
    return raw[:4] + "-" + raw[4:]


def _handoff_key(value: str) -> str:
    return normalize_handoff_code(value).replace("-", "")


def _new_handoff_code() -> str:
    return normalize_handoff_code(
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_USER_CODE_LEN))
    )


def _issue_handoff_unlocked(row: dict[str, Any]) -> str:
    """签发（或重签）交接码：明文只交给调用方一次，落库只存 SHA-256。"""
    code = _new_handoff_code()
    now = _utcnow()
    row["handoff_code_sha256"] = _sha256_hex(_handoff_key(code))
    row["handoff_issued_at"] = _iso(now)
    row["handoff_expires_at"] = _iso(now + timedelta(seconds=HANDOFF_TTL_SECONDS))
    row["handoff_used_at"] = None
    row["handoff_failures"] = 0
    return code


def _handoff_state(row: dict[str, Any]) -> str:
    """``none`` / ``active`` / ``expired`` / ``used`` —— 只回状态，永不回码。"""
    if row.get("handoff_used_at"):
        return "used"
    if not str(row.get("handoff_code_sha256") or ""):
        return "none"
    exp = _parse_iso(str(row.get("handoff_expires_at") or ""))
    if exp is None or _utcnow() > exp:
        return "expired"
    return "active"


def _verify_handoff(row: dict[str, Any], handoff_code: str | None) -> bool:
    given = _handoff_key(handoff_code or "")
    expected = str(row.get("handoff_code_sha256") or "")
    if not given or not expected:
        return False
    return hmac.compare_digest(_sha256_hex(given), expected)


def _public_base_url() -> str:
    try:
        from config.settings import settings

        base = (getattr(settings, "public_runtime_base_url", "") or "").strip()
    except Exception:  # noqa: BLE001
        base = ""
    return (base or _DEFAULT_BASE_URL).rstrip("/")


def _public_key_fingerprint(public_key: str | None) -> str:
    key = (public_key or "").strip()
    if not key:
        return ""
    return _sha256_hex(key)[:16]


def _pending_for_ip(ip: str) -> int:
    return sum(
        1
        for row in _RECORDS.values()
        if row.get("status") == "pending" and str(row.get("request_ip") or "") == ip
    )


def _purge_expired_unlocked() -> int:
    """Mark timed-out requests expired and drop any credentials they still hold."""
    now = _utcnow()
    touched = 0
    for row in _RECORDS.values():
        if row.get("status") not in {"pending", "approved"}:
            continue
        exp = _parse_iso(str(row.get("expires_at") or ""))
        if exp is None or now <= exp:
            continue
        row["status"] = "expired"
        row["delivery"] = {}
        touched += 1
    if len(_RECORDS) > MAX_RECORDS:
        for key, _ in sorted(
            _RECORDS.items(), key=lambda kv: str(kv[1].get("created_at") or "")
        )[: len(_RECORDS) - MAX_RECORDS]:
            _RECORDS.pop(key, None)
        touched += 1
    if touched:
        _persist_unlocked()
    return touched


def _env_snippet(row: dict[str, Any]) -> dict[str, str]:
    delivery = dict(row.get("delivery") or {})
    env = {
        "KARMA_AGENT_ID": str(row.get("agent_id") or ""),
        "KARMA_RUNTIME_URL": _public_base_url(),
    }
    if delivery.get("api_key"):
        env["KARMA_API_KEY"] = str(delivery["api_key"])
    if delivery.get("runtime_key"):
        env["KARMA_RUNTIME_KEY"] = str(delivery["runtime_key"])
    return env


def _public_view(row: dict[str, Any]) -> dict[str, Any]:
    """What the console may see: never a pairing code, never a credential."""
    delivery = dict(row.get("delivery") or {})
    return {
        "pairing_id": row.get("pairing_id"),
        "user_code": row.get("user_code"),
        "status": row.get("status"),
        "agent_name": row.get("agent_name"),
        "platform": row.get("platform"),
        "public_key_fingerprint": row.get("public_key_fingerprint") or "",
        "endpoint_url": row.get("endpoint_url") or "",
        "self_description": row.get("self_description") or "",
        "requested_side": row.get("requested_side"),
        "requested_vertical": row.get("requested_vertical"),
        "requested_industry_id": row.get("requested_industry_id") or "",
        "requested_answers": dict(row.get("requested_answers") or {}),
        "created_at": row.get("created_at"),
        "expires_at": row.get("expires_at"),
        "approved_at": row.get("approved_at"),
        "claimed_at": row.get("claimed_at"),
        "agent_id": row.get("agent_id"),
        "owner_identity_id": row.get("owner_identity_id"),
        "has_api_key": bool(delivery.get("api_key")),
        "has_runtime_key": bool(delivery.get("runtime_key")),
        "runtime_key_id": delivery.get("runtime_key_id") or "",
        # 交接码只回状态：明文只在「签发交接码」那一条响应里出现一次。
        "handoff_state": _handoff_state(row),
        "handoff_expires_at": row.get("handoff_expires_at"),
        "deny_reason": row.get("deny_reason") or "",
    }


def create_request(
    *,
    agent_name: str,
    platform: str = "custom",
    public_key: str | None = None,
    endpoint_url: str | None = None,
    self_description: str | None = None,
    requested_side: str | None = None,
    requested_vertical: str | None = None,
    requested_answers: dict[str, Any] | None = None,
    request_ip: str = "",
) -> dict[str, Any]:
    """Open a pairing request. The pairing code is returned exactly once."""
    name = (agent_name or "").strip()
    if not name:
        raise HTTPException(400, "agent_name is required")

    pairing_id = secrets.token_hex(16)
    pairing_code = secrets.token_urlsafe(32)
    now = _utcnow()
    expires = now + timedelta(seconds=DEFAULT_TTL_SECONDS)

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        ip = (request_ip or "").strip()
        if ip and _pending_for_ip(ip) >= MAX_PENDING_PER_IP:
            raise HTTPException(
                429, "too many open pairing requests from this address — approve or wait them out"
            )
        user_code = _new_user_code()
        _RECORDS[pairing_id] = {
            "pairing_id": pairing_id,
            "user_code": user_code,
            "pairing_code_sha256": _sha256_hex(pairing_code),
            "status": "pending",
            "created_at": _iso(now),
            "expires_at": _iso(expires),
            "agent_name": name,
            "platform": (platform or "").strip()[:64] or "custom",
            "public_key": (public_key or "").strip()[:512],
            "public_key_fingerprint": _public_key_fingerprint(public_key),
            "endpoint_url": (endpoint_url or "").strip()[:2048],
            "self_description": (self_description or "").strip()[:2000],
            "requested_side": (requested_side or "").strip()[:16] or None,
            "requested_vertical": (requested_vertical or "").strip()[:64] or None,
            "requested_industry_id": normalize_requested_vertical(requested_vertical)[:64] or None,
            # The agent knows its own hard metrics better than the owner does, so
            # it declares them here and the owner only approves or rejects; the
            # P1 gate still validates them against the industry contract.
            "requested_answers": dict(requested_answers or {}),
            "request_ip": ip,
            "owner_identity_id": None,
            "agent_id": None,
            "approved_at": None,
            "claimed_at": None,
            "handoff_code_sha256": "",
            "handoff_issued_at": None,
            "handoff_expires_at": None,
            "handoff_used_at": None,
            "handoff_failures": 0,
            "deny_reason": "",
            "delivery": {},
        }
        _persist_unlocked()

    return {
        "schema_version": "karma-agent-pairing-v1",
        "pairing_id": pairing_id,
        "pairing_code": pairing_code,
        "user_code": user_code,
        "verification_uri": f"{_public_base_url()}/console/?pair={user_code}",
        "expires_at": _iso(expires),
        "expires_in_seconds": DEFAULT_TTL_SECONDS,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "claim_endpoint": "/v1/agent-pairing/claim",
        "claim_requires": ["pairing_code", "handoff_code"],
        "instructions_zh": (
            "① 把 user_code 告诉你的主人，请他在 Karma 操作台 · Agent 接入 · 配对 里批准；"
            "② 请他在操作台点「签发交接码」，把那串码输入给你；"
            "③ 用 pairing_code + handoff_code 轮询 claim 端点领取凭据"
            "（只发一次，拿到就存好）。两个码缺一不可。"
        ),
        "instructions_en": (
            "1) Show the user_code to your owner and ask them to approve it in the Karma "
            "console (Agents · Pairing). 2) Ask them to issue a handoff code there and give "
            "it to you. 3) Poll the claim endpoint with pairing_code + handoff_code. Both "
            "codes are required; credentials are delivered exactly once."
        ),
    }


def _find_by_user_code(user_code: str) -> dict[str, Any] | None:
    key = _user_code_key(user_code)
    if not key:
        return None
    for row in _RECORDS.values():
        if _user_code_key(str(row.get("user_code") or "")) == key:
            return row
    return None


def _find_by_pairing_code(pairing_code: str) -> dict[str, Any] | None:
    token = (pairing_code or "").strip()
    if not token:
        return None
    digest = _sha256_hex(token)
    for row in _RECORDS.values():
        expected = str(row.get("pairing_code_sha256") or "")
        if expected and hmac.compare_digest(digest, expected):
            return row
    return None


def lookup_by_user_code(user_code: str) -> dict[str, Any]:
    """Owner-side view of a request, for the approval screen."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found — check it with the agent and retry")
        return _public_view(row)


def approve(
    *,
    user_code: str,
    owner_identity_id: str,
    agent_id: str,
    api_key: str | None = None,
    agent_public_key: str | None = None,
) -> dict[str, Any]:
    """Bind an approved pairing to the agent created for it."""
    owner = (owner_identity_id or "").strip()
    aid = (agent_id or "").strip()
    if not owner or not aid:
        raise HTTPException(400, "owner_identity_id and agent_id are required")

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found — check it with the agent and retry")
        status = str(row.get("status") or "")
        if status != "pending":
            # Approving twice must not mint a second agent for the same request.
            raise HTTPException(409, f"pairing is already {status}")
        row["status"] = "approved"
        row["owner_identity_id"] = owner
        row["agent_id"] = aid
        row["approved_at"] = _iso(_utcnow())
        delivery: dict[str, Any] = dict(row.get("delivery") or {})
        if api_key:
            delivery["api_key"] = api_key
        if agent_public_key:
            delivery["agent_public_key"] = agent_public_key
        row["delivery"] = delivery
        _persist_unlocked()
        # Never hand the console the payload: the whole point is that the agent
        # collects it. The owner screen only gets "is it there yet".
        return _public_view(row)


def issue_handoff(*, user_code: str, owner_identity_id: str) -> dict[str, Any]:
    """主人的「签发交接码」—— 交给 agent 的第二把锁，3 分钟、只显示这一次。

    重签就是重签：旧码当场作废。主人可以先把 Runtime Key 挂好、再签发，
    顺序不会被 agent 抢跑。
    """
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found — check it with the agent and retry")
        status = str(row.get("status") or "")
        if status != "approved":
            raise HTTPException(409, f"pairing is {status} — approve it first")
        if (owner_identity_id or "").strip() != str(row.get("owner_identity_id") or ""):
            raise HTTPException(403, "this pairing belongs to another identity")
        code = _issue_handoff_unlocked(row)
        _persist_unlocked()
        view = _public_view(row)
        # 明文只在这一条响应里出现一次：操作台要把它显示给主人。
        view["handoff_code"] = code
        return view


def deny(*, user_code: str, owner_identity_id: str, reason: str = "") -> dict[str, Any]:
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found")
        if str(row.get("status") or "") != "pending":
            raise HTTPException(409, f"pairing is already {row.get('status')}")
        row["status"] = "denied"
        row["owner_identity_id"] = (owner_identity_id or "").strip() or None
        row["deny_reason"] = (reason or "").strip()[:200]
        row["delivery"] = {}
        _persist_unlocked()
        return _public_view(row)


def attach_runtime_key(
    *,
    user_code: str,
    owner_identity_id: str,
    runtime_key: str,
    runtime_key_id: str,
) -> dict[str, Any]:
    """Park an already-minted runtime key in this pairing's one-shot delivery."""
    token = (runtime_key or "").strip()
    if not token:
        raise HTTPException(400, "runtime_key is required")

    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_user_code(user_code)
        if row is None:
            raise HTTPException(404, "pairing code not found")
        status = str(row.get("status") or "")
        if status == "pending":
            raise HTTPException(409, "approve the pairing before attaching a runtime key")
        if status != "approved":
            raise HTTPException(409, f"pairing is already {status}")
        if (owner_identity_id or "").strip() != str(row.get("owner_identity_id") or ""):
            raise HTTPException(403, "this pairing belongs to another identity")
        delivery = dict(row.get("delivery") or {})
        delivery["runtime_key"] = token
        delivery["runtime_key_id"] = (runtime_key_id or "").strip()
        row["delivery"] = delivery
        _persist_unlocked()
        return _public_view(row)


def claim(*, pairing_code: str, handoff_code: str | None = None) -> dict[str, Any]:
    """Agent side. Two factors, then credentials — handed over once and then gone."""
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        row = _find_by_pairing_code(pairing_code)
        if row is None:
            raise HTTPException(404, "unknown pairing_code")
        status = str(row.get("status") or "")
        if status == "pending":
            return {
                "status": "pending",
                "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                "expires_at": row.get("expires_at"),
                "message_zh": "主人还没批准。请把这个 user_code 给他，并稍后重试。",
                "message_en": "Not approved yet. Give your owner the user_code and retry.",
            }
        if status != "approved":
            return {
                "status": status,
                "message_zh": "这次配对没有可交付的凭据。",
                "message_en": "This pairing has nothing left to deliver.",
            }

        # ── 第二把锁：主人屏幕上的交接码 ──────────────────────────────────
        # pairing_code 只在申请时返回过一次（磁盘上只有哈希）。就算它被偷，
        # 光靠它也**领不走任何东西**：还得有主人在操作台亲口交给你的那串码。
        # 反过来，交接码即使出现在聊天记录里也没用 —— 单独一串换不到凭据。
        state = _handoff_state(row)
        if state in {"none", "expired"}:
            return {
                "status": "awaiting_handoff",
                "handoff_state": state,
                "handoff_expires_at": row.get("handoff_expires_at"),
                "expires_at": row.get("expires_at"),
                "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                "message_zh": (
                    "交接码过期了，请主人在操作台重新签发。"
                    if state == "expired"
                    else "主人还没签发交接码。请让他在操作台点「签发交接码」，"
                    "再把那串码输入给你。"
                ),
                "message_en": (
                    "The handoff code expired — ask your owner to reissue it in the console."
                    if state == "expired"
                    else "Your owner has not issued a handoff code yet. Ask them to issue "
                    "one in the console and hand it to you."
                ),
            }
        if not str(handoff_code or "").strip():
            return {
                "status": "awaiting_handoff",
                "handoff_state": state,
                "handoff_expires_at": row.get("handoff_expires_at"),
                "expires_at": row.get("expires_at"),
                "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                "message_zh": "把主人在操作台看到的交接码用 handoff_code 参数传进来。",
                "message_en": "Pass the handoff code your owner read to you as handoff_code.",
            }
        if not _verify_handoff(row, handoff_code):
            row["handoff_failures"] = int(row.get("handoff_failures") or 0) + 1
            if row["handoff_failures"] >= HANDOFF_MAX_ATTEMPTS:
                # 连着猜错：就地作废这次配对，凭据一并销毁。
                row["status"] = "expired"
                row["delivery"] = {}
                row["handoff_code_sha256"] = ""
                _persist_unlocked()
                raise HTTPException(
                    403, "too many wrong handoff codes — pairing expired, start over"
                )
            _persist_unlocked()
            raise HTTPException(403, "handoff code mismatch")

        delivery = dict(row.get("delivery") or {})
        env = _env_snippet(row)
        row["status"] = "claimed"
        row["claimed_at"] = _iso(_utcnow())
        # One shot: the plaintext and the handoff code both die here.
        row["delivery"] = {}
        row["handoff_code_sha256"] = ""
        row["handoff_used_at"] = row["claimed_at"]
        _persist_unlocked()

    return {
        "schema_version": "karma-agent-pairing-claim-v1",
        "status": "approved",
        "agent_id": row.get("agent_id"),
        "owner_identity_id": row.get("owner_identity_id"),
        "handoff": {"required": True, "consumed": True},
        "credentials": {
            "api_key": delivery.get("api_key"),
            "agent_public_key": delivery.get("agent_public_key"),
            "runtime_key": delivery.get("runtime_key"),
            "runtime_key_id": delivery.get("runtime_key_id") or None,
            "store_now": True,
        },
        "env_snippet": env,
        "runtime_key_binding": {
            "runtime_key_id": delivery.get("runtime_key_id") or None,
            "granted": bool(delivery.get("runtime_key")),
            # 接入是两阶段的：agent 先申请拿到匹配码，主人输入并签名确认后才生效。
            "step_1": "POST /runtime/bind-key with X-Karma-Runtime-Key to request activation",
            "step_2": "show the returned activation_code to your owner",
            "step_3": "owner enters it in the Karma console — only then is the binding live",
            "note": "before the owner confirms, the key stays service-bound; request signing is refused",
        },
        "next_steps": [
            "export KARMA_AGENT_ID / KARMA_API_KEY (and KARMA_RUNTIME_KEY when granted)",
            "GET /v1/agents/mine with X-Karma-Api-Key to confirm the identity resolves",
            "GET /runtime/policy with X-Karma-Runtime-Key to read the granted limits",
            "POST /runtime/bind-key, then hand the activation code to your owner",
        ],
        "note_zh": "凭据只在这一次返回，服务端已不再保留明文；丢失就要重新配对。",
    }


def list_for_owner(owner_identity_id: str) -> list[dict[str, Any]]:
    owner = (owner_identity_id or "").strip()
    _ensure_loaded()
    with _LOCK:
        _purge_expired_unlocked()
        rows = [
            row for row in _RECORDS.values() if str(row.get("owner_identity_id") or "") == owner
        ]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return [_public_view(r) for r in rows]
