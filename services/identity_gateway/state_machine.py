"""Karma 身份信任状态机引擎 v1 —— 商业级状态迁移治理 + 异常播报 + 根因回溯。

设计原则（对应交付要求）：
1. 每一步都有状态机：所有身份/凭证状态迁移必须经过本引擎校验，
   非法迁移直接拒绝，不产生半状态。
2. 任何异常都播报：非法迁移 / 环境异常 / 台账篡改 / 持久化失败
   → broadcast_alert() 写入持久化告警流 + 结构化日志，可经
   GET /v1/trust/alerts 实时查询。
3. 风险预警与问题报告：告警分级（info / warn / critical），
   附根因回溯链（该实体最近 N 条台账事件）。
4. 回溯问题根源：信任台账为追加式 hash 链（entry_hash =
   sha256(prev_hash + entry_canonical)），任何历史篡改可被
   verify_ledger_integrity() 检出并播报。

凭证状态机：
    pending ──verify──▶ verified ──expire──▶ expired ──reverify──▶ pending
       │                    │
       ├──reject──▶ failed  └──revoke──▶ revoked（终态）
       │                │
       └──revoke──┐     └──reissue──▶ pending
                   ▼
                revoked
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from threading import Lock
from typing import Any

import structlog

from services import persist_json

logger = structlog.get_logger("karma.trust")

# 台账 hash 链 HMAC 密钥：从环境读取，缺失时使用固定值（dev 兼容；
# 生产必须设置 KARMA_TRUST_LEDGER_KEY）。持有写权限者无法仅凭重算伪造全链。
_LEDGER_HMAC_KEY = (
    os.getenv("KARMA_TRUST_LEDGER_KEY")
    or os.getenv("APP_SECRET_KEY")
    or "karma-trust-ledger-dev-key-change-in-prod"
).encode("utf-8")

# ── 状态定义 ────────────────────────────────────────────────

CREDENTIAL_STATE_PENDING = "pending"
CREDENTIAL_STATE_VERIFIED = "verified"
CREDENTIAL_STATE_FAILED = "failed"
CREDENTIAL_STATE_EXPIRED = "expired"
CREDENTIAL_STATE_REVOKED = "revoked"
CREDENTIAL_TERMINAL_STATES = {CREDENTIAL_STATE_REVOKED}

# (from_state, action) -> to_state；"" 表示「未签发」初始态
CREDENTIAL_TRANSITIONS: dict[tuple[str, str], str] = {
    ("", "issue"): CREDENTIAL_STATE_PENDING,
    (CREDENTIAL_STATE_PENDING, "verify"): CREDENTIAL_STATE_VERIFIED,
    (CREDENTIAL_STATE_PENDING, "reject"): CREDENTIAL_STATE_FAILED,
    (CREDENTIAL_STATE_PENDING, "revoke"): CREDENTIAL_STATE_REVOKED,
    (CREDENTIAL_STATE_FAILED, "reissue"): CREDENTIAL_STATE_PENDING,
    (CREDENTIAL_STATE_EXPIRED, "reverify"): CREDENTIAL_STATE_PENDING,
    (CREDENTIAL_STATE_VERIFIED, "expire"): CREDENTIAL_STATE_EXPIRED,
    (CREDENTIAL_STATE_VERIFIED, "revoke"): CREDENTIAL_STATE_REVOKED,
}

ALERT_SEVERITY_INFO = "info"
ALERT_SEVERITY_WARN = "warn"
ALERT_SEVERITY_CRITICAL = "critical"

ALERT_CATEGORY_ILLEGAL_TRANSITION = "illegal_transition"
ALERT_CATEGORY_ENVIRONMENT = "environment"
ALERT_CATEGORY_TAMPER = "ledger_tamper"
ALERT_CATEGORY_PERSISTENCE = "persistence"

_LEDGER_MAX = 100_000        # 追加式台账上限（超出后截断头部并播报）
_ALERTS_MAX = 10_000
_ROOT_CAUSE_DEPTH = 8        # 根因回溯链长度

_LOCK = Lock()
_LEDGER: list[dict] = []
_ALERTS: list[dict] = []


class IllegalTransitionError(ValueError):
    """非法状态迁移 —— 已播报风险预警后抛出。"""


def _load() -> None:
    global _LEDGER, _ALERTS
    _LEDGER = list(persist_json.load("trust_ledger").get("entries", []))
    _ALERTS = list(persist_json.load("trust_alerts").get("alerts", []))


_load()


# ── 信任台账（hash 链） ─────────────────────────────────────

def _entry_hash(prev_hash: str, entry: dict) -> str:
    canonical = json.dumps(
        {k: v for k, v in entry.items() if k != "entry_hash"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    # HMAC：无密钥者无法构造合法 hash，杜绝「整体重算伪造全链」
    return hmac.new(_LEDGER_HMAC_KEY, f"{prev_hash}|{canonical}".encode("utf-8"), hashlib.sha256).hexdigest()


def _append_ledger_locked(
    entity_type: str,
    entity_id: str,
    event: str,
    from_state: str,
    to_state: str,
    *,
    actor: str = "system",
    reason: str = "",
    extra: dict | None = None,
) -> dict:
    prev_hash = _LEDGER[-1]["entry_hash"] if _LEDGER else "GENESIS"
    entry = {
        "entry_id": "tle_" + secrets.token_hex(8),
        "ts": int(time.time()),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event": event,
        "from_state": from_state,
        "to_state": to_state,
        "actor": actor[:64],
        "reason": str(reason)[:256],
        "extra": extra or {},
    }
    entry["entry_hash"] = _entry_hash(prev_hash, entry)
    _LEDGER.append(entry)
    if len(_LEDGER) > _LEDGER_MAX:
        _broadcast_alert_locked(
            ALERT_SEVERITY_WARN,
            ALERT_CATEGORY_ENVIRONMENT,
            entity_type="ledger",
            entity_id="trust_ledger",
            summary=f"ledger truncated at {_LEDGER_MAX} entries",
            detail={"dropped": len(_LEDGER) - _LEDGER_MAX},
        )
        del _LEDGER[: len(_LEDGER) - _LEDGER_MAX]
        # 截断后 rebase：重算剩余条目的链 hash，保证校验不误报篡改
        prev = "GENESIS"
        for e in _LEDGER:
            e["entry_hash"] = _entry_hash(prev, e)
            prev = e["entry_hash"]
    try:
        persist_json.save("trust_ledger", {"entries": _LEDGER})
    except Exception:
        _broadcast_alert_locked(
            ALERT_SEVERITY_CRITICAL,
            ALERT_CATEGORY_PERSISTENCE,
            entity_type="ledger",
            entity_id="trust_ledger",
            summary="trust ledger persist failed",
        )
    return entry


def record_event(
    entity_type: str,
    entity_id: str,
    event: str,
    *,
    from_state: str = "",
    to_state: str = "",
    actor: str = "system",
    reason: str = "",
    extra: dict | None = None,
) -> dict:
    """记录一条普通事件（如 card_presented 审计）到台账。"""
    with _LOCK:
        return _append_ledger_locked(
            entity_type, entity_id, event, from_state, to_state,
            actor=actor, reason=reason, extra=extra,
        )


# ── 异常播报 ────────────────────────────────────────────────

def _broadcast_alert_locked(
    severity: str,
    category: str,
    *,
    entity_type: str,
    entity_id: str,
    summary: str,
    detail: dict | None = None,
    root_cause: list[dict] | None = None,
) -> dict:
    if root_cause is None:
        root_cause = _recent_entity_events_locked(entity_id, _ROOT_CAUSE_DEPTH)
    alert = {
        "alert_id": "tal_" + secrets.token_hex(8),
        "ts": int(time.time()),
        "severity": severity,
        "category": category,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "summary": str(summary)[:200],
        "detail": detail or {},
        "root_cause": root_cause,      # 根因回溯链：该实体最近 N 条台账事件
    }
    _ALERTS.append(alert)
    if len(_ALERTS) > _ALERTS_MAX:
        del _ALERTS[: len(_ALERTS) - _ALERTS_MAX]
    try:
        persist_json.save("trust_alerts", {"alerts": _ALERTS})
    except Exception:
        logger.error("trust_alert_persist_failed", alert_id=alert["alert_id"])
    log_fn = (
        logger.info if severity == ALERT_SEVERITY_INFO
        else logger.warning if severity == ALERT_SEVERITY_WARN
        else logger.error
    )
    log_fn(
        "trust_alert_broadcast",
        alert_id=alert["alert_id"],
        severity=severity,
        category=category,
        entity_id=entity_id,
        summary=alert["summary"],
    )
    return alert


def broadcast_alert(
    severity: str,
    category: str,
    *,
    entity_type: str,
    entity_id: str,
    summary: str,
    detail: dict | None = None,
) -> dict:
    """对外播报入口（线程安全）。"""
    with _LOCK:
        return _broadcast_alert_locked(
            severity, category,
            entity_type=entity_type, entity_id=entity_id,
            summary=summary, detail=detail,
        )


def get_alerts(severity: str | None = None, limit: int = 100) -> list[dict]:
    with _LOCK:
        alerts = [a for a in _ALERTS if severity is None or a["severity"] == severity]
        return list(reversed(alerts[-limit:]))


# ── 状态迁移（核心） ────────────────────────────────────────

def transition(
    entity_type: str,
    entity_id: str,
    from_state: str,
    action: str,
    *,
    actor: str = "system",
    reason: str = "",
    extra: dict | None = None,
) -> dict:
    """凭证状态迁移唯一入口。

    合法 → 落台账并返回新状态；非法 → 播报 warn 预警（含根因链）
    并抛 IllegalTransitionError，状态不变。
    """
    key = (from_state, action)
    to_state = CREDENTIAL_TRANSITIONS.get(key)
    if to_state is None:
        with _LOCK:
            _broadcast_alert_locked(
                ALERT_SEVERITY_WARN,
                ALERT_CATEGORY_ILLEGAL_TRANSITION,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=f"illegal transition blocked: {from_state} --{action}--> ?",
                detail={"from_state": from_state, "action": action, "actor": actor[:64]},
            )
        raise IllegalTransitionError(
            f"illegal transition: {from_state} --{action}--> is not allowed"
        )
    with _LOCK:
        return _append_ledger_locked(
            entity_type, entity_id, f"credential_{action}",
            from_state, to_state, actor=actor, reason=reason, extra=extra,
        )


# ── 台账完整性与环境健康 ───────────────────────────────────

def verify_ledger_integrity() -> dict:
    """全链校验 hash 链；发现篡改立即播报 critical。"""
    with _LOCK:
        prev = "GENESIS"
        for i, entry in enumerate(_LEDGER):
            expected = _entry_hash(prev, entry)
            if entry.get("entry_hash") != expected:
                detail = {"index": i, "entry_id": entry.get("entry_id")}
                _broadcast_alert_locked(
                    ALERT_SEVERITY_CRITICAL,
                    ALERT_CATEGORY_TAMPER,
                    entity_type="ledger",
                    entity_id="trust_ledger",
                    summary=f"ledger chain broken at index {i}",
                    detail=detail,
                )
                return {"ok": False, "broken_at": i, **detail}
            prev = entry["entry_hash"]
        return {"ok": True, "entries": len(_LEDGER)}


def health_report() -> dict:
    """环境健康自检：持久化可写 / 台账完整 / 告警流可读 / 时钟 sane。"""
    checks: dict[str, Any] = {}

    try:
        persist_json.save("trust_health_probe", {"ts": int(time.time())})
        persist_json.delete("trust_health_probe")
        checks["persist_writable"] = True
    except Exception:
        checks["persist_writable"] = False
        broadcast_alert(
            ALERT_SEVERITY_CRITICAL, ALERT_CATEGORY_ENVIRONMENT,
            entity_type="environment", entity_id="persist",
            summary="persist storage not writable",
        )

    integrity = verify_ledger_integrity()
    checks["ledger_integrity"] = integrity["ok"]
    checks["ledger_entries"] = integrity.get("entries", len(_LEDGER))
    checks["alerts_count"] = len(_ALERTS)

    now = int(time.time())
    last_ts = _LEDGER[-1]["ts"] if _LEDGER else now
    checks["clock_sane"] = last_ts <= now + 300
    if not checks["clock_sane"]:
        broadcast_alert(
            ALERT_SEVERITY_WARN, ALERT_CATEGORY_ENVIRONMENT,
            entity_type="environment", entity_id="clock",
            summary="ledger timestamp is in the future",
            detail={"last_ts": last_ts, "now": now},
        )

    checks["ok"] = (
        checks["persist_writable"]
        and checks["ledger_integrity"]
        and checks["clock_sane"]
    )
    if not checks["ok"]:
        broadcast_alert(
            ALERT_SEVERITY_CRITICAL, ALERT_CATEGORY_ENVIRONMENT,
            entity_type="environment", entity_id="runtime",
            summary="trust environment health check FAILED",
            detail=checks,
        )
    return checks


def get_ledger(entity_id: str | None = None, limit: int = 100) -> list[dict]:
    with _LOCK:
        entries = [e for e in _LEDGER if entity_id is None or e["entity_id"] == entity_id]
        return list(reversed(entries[-limit:]))


def _recent_entity_events_locked(entity_id: str, limit: int) -> list[dict]:
    return [
        {
            "ts": e["ts"], "event": e["event"],
            "from_state": e["from_state"], "to_state": e["to_state"],
            "actor": e["actor"], "reason": e["reason"],
        }
        for e in _LEDGER if e["entity_id"] == entity_id
    ][-limit:]


def reset_for_tests() -> None:
    with _LOCK:
        _LEDGER.clear()
        _ALERTS.clear()
        persist_json.delete("trust_ledger")
        persist_json.delete("trust_alerts")
