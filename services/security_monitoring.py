"""
Karma Security Monitoring
Rolling event tracker for security operations alerting.

The event ring lives in this process; the alert report only ever looks at the last
`window_minutes` (15 by default). A process-memory-only ring therefore loses the
whole detection window on every container recreate -- and deploys recreate the
container. So the ring is *also* appended to a local journal on the durable state
mount, and ``_list_recent_events`` merges memory with the journal.

Journaling is strictly best-effort: if the path is unwritable (or the disk is
full) the module degrades to exactly the old in-memory behaviour and never raises
into a request path.
"""
from __future__ import annotations

import json
import os
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from core.schemas import (
    SecurityOpsAlert,
    SecurityOpsAlertReport,
    SecurityOpsBaselineReference,
    SecurityOpsDimensionCount,
    SecurityOpsEscalationDecision,
    SecurityOpsEscalationLevel,
    SecurityOpsAlertSeverity,
    SecurityOpsAlertType,
    SecurityOpsSummary,
)

_MAX_EVENTS = 10_000
_EVENTS: deque["SecurityMonitoringEvent"] = deque(maxlen=_MAX_EVENTS)
_LOCK = Lock()
_LAST_ALERT_EMITTED_AT: dict[str, datetime] = {}
_MAX_BASELINE_SNAPSHOTS = 2_000
_BASELINE_SNAPSHOTS: deque["SecurityBaselineSnapshot"] = deque(maxlen=_MAX_BASELINE_SNAPSHOTS)
_LAST_BASELINE_CAPTURE_AT: datetime | None = None

# --- Durable journal -------------------------------------------------------
# The event ring above is process memory: a container recreate (i.e. every
# deploy) empties it, which silently resets the 15-minute detection window and
# can hide a burst that straddles the restart. Append every event to a journal
# on the same durable bind mount persist_json.py already uses, and merge it back
# in on read. Best effort by construction: an unwritable path degrades to the
# old memory-only behaviour instead of failing a request.
_JOURNAL_FILENAME = "security_events.jsonl"
_JOURNAL_MAX_BYTES = 4 * 1024 * 1024
_JOURNAL_RETAIN_MINUTES = 60
_JOURNAL_MAX_CONSECUTIVE_ERRORS = 5
_JOURNAL_LOCK = Lock()
_JOURNAL: dict[str, Any] = {"fd": None, "path": None, "size": 0, "errors": 0, "broken": False}


def _journal_path() -> Path | None:
    """Where the journal lives. ``KARMA_SECURITY_EVENT_JOURNAL`` wins; otherwise
    the durable data dir persist_json.py uses (``KARMA_MVP_DATA_DIR`` or
    ``<repo>/mvp_data``), which docker-compose bind-mounts read-write."""
    raw = os.getenv("KARMA_SECURITY_EVENT_JOURNAL")
    if raw:
        return Path(raw)
    base = os.getenv("KARMA_MVP_DATA_DIR")
    root = Path(base) if base else (Path(__file__).resolve().parent.parent / "mvp_data")
    return root / _JOURNAL_FILENAME


def _journal_encode(event: "SecurityMonitoringEvent") -> str:
    payload = {
        "id": event.event_id,
        "type": event.event_type.value,
        "at": event.created_at.isoformat(),
        "meta": event.metadata,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"


def _journal_decode(line: str) -> "SecurityMonitoringEvent | None":
    try:
        raw = json.loads(line)
        return SecurityMonitoringEvent(
            event_type=SecurityMonitoringEventType(raw["type"]),
            created_at=datetime.fromisoformat(raw["at"]),
            metadata=dict(raw.get("meta") or {}),
            event_id=str(raw.get("id") or ""),
        )
    except Exception:
        return None


def _journal_close_locked() -> None:
    fd = _JOURNAL.get("fd")
    _JOURNAL["fd"] = None
    if fd is not None:
        try:
            fd.close()
        except Exception:
            pass


def _journal_rewrite_locked(path: Path) -> None:
    """Trim the journal to the retain window, then let the caller reopen it."""
    cutoff = datetime.utcnow() - timedelta(minutes=_JOURNAL_RETAIN_MINUTES)
    kept: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                event = _journal_decode(line)
                if event is not None and event.created_at >= cutoff:
                    kept.append(line if line.endswith("\n") else line + "\n")
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(kept))
        os.replace(tmp, path)
    except Exception:
        return
    _JOURNAL["size"] = sum(len(item.encode("utf-8")) for item in kept)


def _journal_open_locked() -> "Any | None":
    path = _journal_path()
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _JOURNAL_MAX_BYTES:
            _journal_rewrite_locked(path)
        fd = open(path, "a", encoding="utf-8", newline="\n")
    except Exception:
        _JOURNAL["errors"] += 1
        if _JOURNAL["errors"] >= _JOURNAL_MAX_CONSECUTIVE_ERRORS:
            _JOURNAL["broken"] = True
        return None
    _JOURNAL["fd"] = fd
    _JOURNAL["path"] = str(path)
    try:
        _JOURNAL["size"] = path.stat().st_size
    except OSError:
        _JOURNAL["size"] = 0
    _JOURNAL["errors"] = 0
    return fd


def _journal_append(event: "SecurityMonitoringEvent") -> None:
    with _JOURNAL_LOCK:
        if _JOURNAL["broken"]:
            return
        fd = _JOURNAL["fd"] or _journal_open_locked()
        if fd is None:
            return
        try:
            line = _journal_encode(event)
            fd.write(line)
            fd.flush()
        except Exception:
            _journal_close_locked()
            _JOURNAL["errors"] += 1
            if _JOURNAL["errors"] >= _JOURNAL_MAX_CONSECUTIVE_ERRORS:
                _JOURNAL["broken"] = True
            return
        _JOURNAL["size"] += len(line.encode("utf-8"))
        if _JOURNAL["size"] > _JOURNAL_MAX_BYTES:
            path = _journal_path()
            _journal_close_locked()
            if path is not None:
                _journal_rewrite_locked(path)


def _journal_read_recent(window_minutes: int) -> "list[SecurityMonitoringEvent]":
    path = _journal_path()
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    events: list[SecurityMonitoringEvent] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        event = _journal_decode(line)
        if event is not None and event.created_at >= cutoff:
            events.append(event)
    return events


class SecurityMonitoringEventType(str, Enum):
    FAILED_AUTH = "failed_auth"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    VERIFY_REQUEST = "verify_request"
    PRIVATE_RUNTIME_ERROR = "private_runtime_error"
    SETTLEMENT_TRANSITION_AUDIT = "settlement_transition_audit"
    # 高敏感操作审计（红队报告 KARMA-RT-2026-08-27-001）
    # 仲裁员 resolve 争议 / 管理员切换安全模式与运营暂停——一旦发生即应可追溯、可告警。
    ARBITRATOR_ACTION = "arbitrator_action"
    ADMIN_CONTROL_ACTION = "admin_control_action"
    # 认证撤销（2026-10-08 审计 O4）：企业 / 个体户认证一旦 verified 就是终态，撤销是唯一出口
    # —— 谁发起、谁确认、因为什么，必须可追溯、可告警。
    VERIFICATION_REVOKED = "verification_revoked"
    # 操作钱包换人代表（2026-10-08 审计 G6）：改代表权必须本人刷脸，动作本身要可追溯、可告警。
    IDENTITY_WALLET_REBIND = "identity_wallet_rebind"
    # 治理岗的发放 / 收回（2026-10-08 审计 G5）：谁能复核别人的材料、谁能裁争议，
    # 是平台最敏感的授权之一，发放与收回都必须可追溯、可告警。
    GOVERNANCE_ROLE_GRANTED = "governance_role_granted"
    GOVERNANCE_ROLE_REVOKED = "governance_role_revoked"
    # 自成交硬禁（2026-10-14）：买方和卖方是同一把钱包 / 同一个主身份时，任何资金
    # 动作都不许往下走。这既是刷量信号也是链上注定 revert 的形状，被拒的每一次
    # 都要能追溯、能告警 —— 谁在试、试了多少次，是判断「有人在刷」的唯一来源。
    SELF_DEAL_REFUSED = "self_deal_refused"


@dataclass
class SecurityMonitoringEvent:
    event_type: SecurityMonitoringEventType
    created_at: datetime
    metadata: dict[str, Any]
    # Stable id so the in-memory ring and the journal can be merged without
    # double counting the same event (the ring is the same events, just cached).
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# 拒绝归类（2026-10-13）
# ---------------------------------------------------------------------------
# 一次结算迁移「被拒」有两种完全不同的成因。混在同一个指标里，刹车会按**重试次数**
# 自己把自己点着：
#
# * ``state_machine``（guard_stage=route/pipeline）—— 业务状态机本来就禁止这一步。
#   这是「有人在非法穿越状态机」的真信号，也是拒绝率告警该看的唯一一类。
# * ``chain_gate``（guard_stage=chain）—— 迁移本身合法，链上那一步没成（RPC 抖动、
#   托管合约状态不对……），业务状态已退回、交易可重试。autosettle 每一轮都会重试
#   这些单子，所以它天然是「一次故障 -> 一大串事件」。
# * ``store_conflict``（guard_stage=store）—— 落库时的乐观锁冲突。
#
# 线上证据（2026-10-13 02:43）：19 张卡在 ``auto_confirmed`` 的结算单在同一秒被
# autosettle 各拒一次，全部 guard_stage=chain；按事件数算 = 19/90 = 21% >= 20%，
# CRITICAL 告警成立 -> 自动刹车；人工清闸后窗口里那批旧事件仍在，下一轮轮询又把
# 刹车拉回去。链上腿失败的钱一分没动，不该冒充「状态机被非法穿越」。
DENIAL_CLASS_STATE_MACHINE = "state_machine"
DENIAL_CLASS_CHAIN_GATE = "chain_gate"
DENIAL_CLASS_STORE_CONFLICT = "store_conflict"

_STATE_MACHINE_GUARD_STAGES = frozenset({"route", "pipeline"})


def denial_class_for_guard_stage(guard_stage: str | None) -> str:
    """把一次拒绝的 ``guard_stage`` 归类成上面三种（写事件的一侧用它盖章）。"""
    stage = (guard_stage or "").strip().lower()
    if stage in _STATE_MACHINE_GUARD_STAGES:
        return DENIAL_CLASS_STATE_MACHINE
    if stage == "chain":
        return DENIAL_CLASS_CHAIN_GATE
    return DENIAL_CLASS_STORE_CONFLICT


def _transition_denied(event: "SecurityMonitoringEvent") -> bool:
    return not bool(event.metadata.get("transition_allowed", True))


def _denial_class_of(event: "SecurityMonitoringEvent") -> str:
    """老事件（升级前写的）没有 ``denial_class``，按 guard_stage 现推。"""
    explicit = event.metadata.get("denial_class")
    if explicit:
        return str(explicit)
    return denial_class_for_guard_stage(event.metadata.get("guard_stage"))


@dataclass
class SecurityBaselineSnapshot:
    captured_at: datetime
    failed_auth_count: int
    rate_limited_count: int
    private_runtime_error_rate: float
    verify_request_count: int


def record_security_event(
    event_type: SecurityMonitoringEventType,
    *,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> None:
    event = SecurityMonitoringEvent(
        event_type=event_type,
        created_at=created_at or datetime.utcnow(),
        metadata=metadata or {},
    )
    with _LOCK:
        _EVENTS.append(event)
    _journal_append(event)


def clear_security_events() -> None:
    global _LAST_BASELINE_CAPTURE_AT
    with _LOCK:
        _EVENTS.clear()
        _LAST_ALERT_EMITTED_AT.clear()
        _BASELINE_SNAPSHOTS.clear()
        _LAST_BASELINE_CAPTURE_AT = None
    # Tests call this; production never does. Drop the journal too or the next
    # read would resurrect exactly what the caller asked to forget.
    with _JOURNAL_LOCK:
        _journal_close_locked()
        try:
            path = _journal_path()
            if path is not None and path.exists():
                path.unlink()
        except Exception:
            pass
        _JOURNAL["size"] = 0
        _JOURNAL["errors"] = 0
        _JOURNAL["broken"] = False


def _list_recent_events(window_minutes: int) -> list[SecurityMonitoringEvent]:
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    with _LOCK:
        events = [event for event in _EVENTS if event.created_at >= cutoff]
    persisted = _journal_read_recent(window_minutes)
    if not persisted:
        return events
    # The journal is what lets a burst survive the container recreate that every
    # deploy performs; the ring is the same events cached, hence the dedupe.
    merged = list(events)
    seen = {event.event_id for event in merged if event.event_id}
    for event in persisted:
        if event.event_id and event.event_id in seen:
            continue
        if event.event_id:
            seen.add(event.event_id)
        merged.append(event)
    merged.sort(key=lambda item: item.created_at)
    return merged


def _top_dimension_counts(
    *,
    events: list[SecurityMonitoringEvent],
    event_type: SecurityMonitoringEventType,
    metadata_key: str,
    limit: int,
    default_key: str,
) -> list[SecurityOpsDimensionCount]:
    stats: dict[str, SecurityOpsDimensionCount] = {}
    for event in events:
        if event.event_type != event_type:
            continue
        raw_value = event.metadata.get(metadata_key)
        key = str(raw_value).strip() if raw_value else default_key
        item = stats.get(key)
        if item is None:
            item = SecurityOpsDimensionCount(key=key, count=0, last_seen_at=event.created_at)
            stats[key] = item
        item.count += 1
        if item.last_seen_at is None or event.created_at > item.last_seen_at:
            item.last_seen_at = event.created_at
    return sorted(stats.values(), key=lambda item: (-item.count, item.key))[:limit]


def _dimension_counter(
    *,
    events: list[SecurityMonitoringEvent],
    event_type: SecurityMonitoringEventType,
    metadata_key: str,
    default_key: str,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in events:
        if event.event_type != event_type:
            continue
        raw_value = event.metadata.get(metadata_key)
        key = str(raw_value).strip() if raw_value else default_key
        counter[key] += 1
    return counter


def _dimension_counter_with_filter(
    *,
    events: list[SecurityMonitoringEvent],
    event_type: SecurityMonitoringEventType,
    metadata_key: str,
    default_key: str,
    predicate: Callable[[SecurityMonitoringEvent], bool] | None = None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in events:
        if event.event_type != event_type:
            continue
        if predicate is not None and not predicate(event):
            continue
        raw_value = event.metadata.get(metadata_key)
        key = str(raw_value).strip() if raw_value else default_key
        counter[key] += 1
    return counter


def _denial_class_dimension_counts(
    *,
    events: list[SecurityMonitoringEvent],
    limit: int,
) -> list[SecurityOpsDimensionCount]:
    """按 denial_class 统计被拒的结算迁移。

    不能直接用 ``_top_dimension_counts`` 读 ``metadata['denial_class']``：升级前写进
    窗口的老事件没有这个字段，会被一股脑算进默认桶。这里统一走 ``_denial_class_of``
    （没有字段就按 guard_stage 现推），新老事件口径一致。
    """
    stats: dict[str, SecurityOpsDimensionCount] = {}
    for event in events:
        if event.event_type != SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT:
            continue
        if not _transition_denied(event):
            continue
        key = _denial_class_of(event)
        item = stats.get(key)
        if item is None:
            item = SecurityOpsDimensionCount(key=key, count=0, last_seen_at=event.created_at)
            stats[key] = item
        item.count += 1
        if item.last_seen_at is None or event.created_at > item.last_seen_at:
            item.last_seen_at = event.created_at
    return sorted(stats.values(), key=lambda item: (-item.count, item.key))[:limit]


def _parse_threshold_overrides(raw: str | None, *, as_float: bool = False) -> dict[str, float]:
    if not raw:
        return {}
    parsed: dict[str, float] = {}
    for item in raw.split(","):
        entry = item.strip()
        if not entry or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            continue
        try:
            parsed[key] = float(value) if as_float else int(value)
        except ValueError:
            continue
    return parsed


def _scope_threshold(default_threshold: float, overrides: dict[str, float], scope_key: str) -> float:
    return float(overrides.get(scope_key.lower(), default_threshold))


def _should_emit_alert_now(alert_signature: str, *, cooldown_minutes: int) -> bool:
    if cooldown_minutes <= 0:
        return True
    now = datetime.utcnow()
    with _LOCK:
        last_emitted = _LAST_ALERT_EMITTED_AT.get(alert_signature)
        if last_emitted and now - last_emitted < timedelta(minutes=cooldown_minutes):
            return False
        _LAST_ALERT_EMITTED_AT[alert_signature] = now
    return True


def _list_baseline_snapshots(baseline_window_minutes: int) -> list[SecurityBaselineSnapshot]:
    cutoff = datetime.utcnow() - timedelta(minutes=baseline_window_minutes)
    with _LOCK:
        return [item for item in _BASELINE_SNAPSHOTS if item.captured_at >= cutoff]


def _compute_baseline_reference(
    *,
    baseline_window_minutes: int,
) -> SecurityOpsBaselineReference:
    snapshots = _list_baseline_snapshots(baseline_window_minutes)
    if not snapshots:
        return SecurityOpsBaselineReference(baseline_window_minutes=baseline_window_minutes)
    sample_count = len(snapshots)
    return SecurityOpsBaselineReference(
        sample_count=sample_count,
        baseline_window_minutes=baseline_window_minutes,
        failed_auth_avg=sum(item.failed_auth_count for item in snapshots) / sample_count,
        rate_limited_avg=sum(item.rate_limited_count for item in snapshots) / sample_count,
        private_runtime_error_rate_avg=sum(item.private_runtime_error_rate for item in snapshots) / sample_count,
    )


def _maybe_capture_baseline_snapshot(
    *,
    capture_interval_minutes: int,
    failed_auth_count: int,
    rate_limited_count: int,
    private_runtime_error_rate: float,
    verify_request_count: int,
) -> None:
    global _LAST_BASELINE_CAPTURE_AT
    now = datetime.utcnow()
    with _LOCK:
        if (
            capture_interval_minutes > 0
            and _LAST_BASELINE_CAPTURE_AT is not None
            and now - _LAST_BASELINE_CAPTURE_AT < timedelta(minutes=capture_interval_minutes)
        ):
            return
        _BASELINE_SNAPSHOTS.append(
            SecurityBaselineSnapshot(
                captured_at=now,
                failed_auth_count=failed_auth_count,
                rate_limited_count=rate_limited_count,
                private_runtime_error_rate=private_runtime_error_rate,
                verify_request_count=verify_request_count,
            )
        )
        _LAST_BASELINE_CAPTURE_AT = now


def _build_escalation_decision(
    *,
    active_alerts: list[SecurityOpsAlert],
    suppressed_alert_count: int,
) -> SecurityOpsEscalationDecision:
    if any(alert.severity == SecurityOpsAlertSeverity.CRITICAL for alert in active_alerts):
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.PAGE,
            reason="critical security alert triggered",
            trigger_alert_types=[alert.alert_type for alert in active_alerts],
        )
    if any(alert.severity == SecurityOpsAlertSeverity.HIGH for alert in active_alerts):
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.WATCH,
            reason="high-severity security alert requires active watch",
            trigger_alert_types=[alert.alert_type for alert in active_alerts],
        )
    if suppressed_alert_count > 0:
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.WATCH,
            reason="alerts are currently suppressed by cooldown; continue monitoring",
            trigger_alert_types=[],
        )
    if active_alerts:
        return SecurityOpsEscalationDecision(
            level=SecurityOpsEscalationLevel.WATCH,
            reason="security alert threshold exceeded",
            trigger_alert_types=[alert.alert_type for alert in active_alerts],
        )
    return SecurityOpsEscalationDecision()


def _build_recommended_actions(
    *,
    active_alerts: list[SecurityOpsAlert],
    escalation: SecurityOpsEscalationDecision,
) -> list[str]:
    actions: list[str] = []
    alert_types = {alert.alert_type for alert in active_alerts}
    if SecurityOpsAlertType.AUTH_FAILURE_SPIKE in alert_types:
        # 来源数是关键：一个来源刷一千次，多半只是有人开着过期会话的页面在轮询；
        # 很多来源才是「有人在撞」。别把两者说成同一句建议。
        source_counts = [
            int(alert.metadata["distinct_source_count"])
            for alert in active_alerts
            if alert.alert_type == SecurityOpsAlertType.AUTH_FAILURE_SPIKE
            and "distinct_source_count" in alert.metadata
        ]
        max_sources = max(source_counts) if source_counts else 0
        if max_sources == 1:
            actions.append(
                "Single source is retrying with a rejected credential — check whether an expired "
                "console/agent session is still polling (re-auth the session) before rotating keys."
            )
        elif max_sources >= 2:
            actions.append(
                "Rotate affected API keys and investigate top auth-failure actor/path/source dimensions."
            )
        else:
            # 来源数是 0 = 这批事件没有 client_ip（升级前写下的）。不能硬说是「一个」还是
            # 「一堆」—— 那正是这条告警要分清的两种性质，宁可老实说分不清，也别给错方向。
            actions.append(
                "Investigate top auth-failure actor/path dimensions; these events carry no source IP, "
                "so a single polling client and a distributed burst cannot be told apart."
            )
    if SecurityOpsAlertType.RATE_LIMIT_SPIKE in alert_types:
        actions.append("Apply stricter endpoint-level throttles and block abusive source identities.")
    if SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_RATE in alert_types:
        actions.append("Inspect private runtime health/dependencies and enable fallback routing if needed.")
    if SecurityOpsAlertType.AUTH_FAILURE_BASELINE_DRIFT in alert_types:
        actions.append("Investigate abnormal auth-failure drift against baseline and tighten auth controls.")
    if SecurityOpsAlertType.RATE_LIMIT_BASELINE_DRIFT in alert_types:
        actions.append("Review sudden 429 drift and apply endpoint-specific throttling overrides.")
    if SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_BASELINE_DRIFT in alert_types:
        actions.append("Investigate private runtime stability drift and trigger dependency failover checks.")
    if SecurityOpsAlertType.SETTLEMENT_TRANSITION_DENIED_SPIKE in alert_types:
        actions.append(
            "Review rejected settlement state-machine transitions by path/actor and investigate workflow misuse."
        )
    if SecurityOpsAlertType.SETTLEMENT_TRANSITION_DENIED_RATE in alert_types:
        actions.append("Enable emergency brake controls and investigate irreversibility guard violations immediately.")
    if SecurityOpsAlertType.SETTLEMENT_TRANSITION_CHAIN_GATE_SPIKE in alert_types:
        actions.append(
            "Investigate stuck settlements whose on-chain leg keeps failing (sepolia RPC / escrow binding / "
            "operator allowance); funds did not move and autosettle retries every tick."
        )
    if SecurityOpsAlertType.PRIVILEGED_ACTION_SPIKE in alert_types:
        actions.append(
            "Investigate arbitrator/admin-control action spike: rotate affected session credentials "
            "and review privileged actor audit trail immediately."
        )
    if escalation.level == SecurityOpsEscalationLevel.PAGE:
        actions.append("Page on-call security owner and open incident channel immediately.")
    return actions


def build_security_ops_alert_report(
    *,
    window_minutes: int = 15,
    failed_auth_threshold: int = 10,
    rate_limit_threshold: int = 30,
    private_runtime_error_threshold: int = 5,
    private_runtime_error_rate_threshold: float = 0.25,
    private_runtime_min_requests: int = 10,
    settlement_transition_denied_threshold: int = 5,
    settlement_transition_denied_rate_threshold: float = 0.2,
    settlement_transition_min_requests: int = 10,
    privileged_action_threshold: int = 5,
    dimension_limit: int = 5,
    alert_cooldown_minutes: int = 10,
    failed_auth_threshold_overrides: str | None = None,
    rate_limit_threshold_overrides: str | None = None,
    private_runtime_error_threshold_overrides: str | None = None,
    private_runtime_error_rate_threshold_overrides: str | None = None,
    settlement_transition_denied_threshold_overrides: str | None = None,
    baseline_window_minutes: int = 24 * 60,
    baseline_drift_multiplier: float = 2.5,
    baseline_min_sample_count: int = 3,
    baseline_capture_interval_minutes: int = 10,
    record_baseline_snapshot: bool = True,
) -> SecurityOpsAlertReport:
    events = _list_recent_events(window_minutes)
    counts = Counter(event.event_type.value for event in events)

    failed_auth_count = counts.get(SecurityMonitoringEventType.FAILED_AUTH.value, 0)
    rate_limited_count = counts.get(SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED.value, 0)
    verify_request_count = counts.get(SecurityMonitoringEventType.VERIFY_REQUEST.value, 0)
    private_runtime_error_count = counts.get(SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR.value, 0)
    settlement_transition_total_count = counts.get(SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT.value, 0)
    arbitrator_action_count = counts.get(SecurityMonitoringEventType.ARBITRATOR_ACTION.value, 0)
    admin_control_action_count = counts.get(SecurityMonitoringEventType.ADMIN_CONTROL_ACTION.value, 0)
    privileged_action_count = arbitrator_action_count + admin_control_action_count
    settlement_audits = [
        event
        for event in events
        if event.event_type == SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT
    ]
    state_machine_denials = [
        event
        for event in settlement_audits
        if _transition_denied(event) and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE
    ]
    chain_gate_denials = [
        event
        for event in settlement_audits
        if _transition_denied(event) and _denial_class_of(event) == DENIAL_CLASS_CHAIN_GATE
    ]
    settlement_transition_denied_count = len(state_machine_denials)
    # 分母 = 「真的走到状态机闸门前的迁移」：放行的 + 被状态机拒的。链上腿失败的那批
    # 不在这里 —— 它们的拒绝由 chain-gate 告警单独报，混进来只会把分母用重试刷大、
    # 把真攻击稀释掉。
    settlement_transition_guard_evaluations = (
        sum(1 for event in settlement_audits if not _transition_denied(event))
        + settlement_transition_denied_count
    )
    settlement_transition_denied_rate = (
        float(settlement_transition_denied_count) / float(settlement_transition_guard_evaluations)
        if settlement_transition_guard_evaluations > 0
        else 0.0
    )
    # 链上腿失败按「单子」去重：同一单被 autosettle 重试 20 次是一条故障，不是 20 条。
    settlement_transition_chain_gate_denied_count = len(
        {
            str(event.metadata.get("task_id") or event.metadata.get("settlement_id") or event.event_id)
            for event in chain_gate_denials
        }
    )
    # 自动刹车要判断「这批证据是不是比人工清闸还新」——没有时间戳就没法判，所以带上。
    latest_state_machine_denied_at = (
        max(event.created_at for event in state_machine_denials) if state_machine_denials else None
    )
    private_runtime_error_rate = (
        float(private_runtime_error_count) / float(verify_request_count)
        if verify_request_count > 0
        else 0.0
    )
    failed_auth_override_map = _parse_threshold_overrides(failed_auth_threshold_overrides, as_float=False)
    rate_limit_override_map = _parse_threshold_overrides(rate_limit_threshold_overrides, as_float=False)
    private_runtime_error_override_map = _parse_threshold_overrides(private_runtime_error_threshold_overrides, as_float=False)
    private_runtime_error_rate_override_map = _parse_threshold_overrides(
        private_runtime_error_rate_threshold_overrides,
        as_float=True,
    )
    settlement_transition_denied_override_map = _parse_threshold_overrides(
        settlement_transition_denied_threshold_overrides,
        as_float=False,
    )

    failed_auth_by_path_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.FAILED_AUTH,
        metadata_key="path",
        default_key="unknown",
    )
    failed_auth_by_group_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.FAILED_AUTH,
        metadata_key="route_group",
        default_key="other",
    )
    # 失败来源维度。升级前写下的老事件没有 client_ip，统一落到 "unknown"，不混进
    # 真实来源里数。它存在的唯一目的：让 AUTH_FAILURE_SPIKE 能一眼看出「一个来源
    # 在刷」还是「很多来源在撞」—— 前者多半是过期会话轮询，后者才像攻击
    # （2026-10-13 实测：单来源轮询一小时能刷 ~250 条匿名 401）。
    failed_auth_by_source_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.FAILED_AUTH,
        metadata_key="client_ip",
        default_key="unknown",
    )
    rate_limited_by_path_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
        metadata_key="path",
        default_key="unknown",
    )
    rate_limited_by_group_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
        metadata_key="route_group",
        default_key="other",
    )
    verify_by_path_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.VERIFY_REQUEST,
        metadata_key="path",
        default_key="unknown",
    )
    verify_by_group_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.VERIFY_REQUEST,
        metadata_key="route_group",
        default_key="other",
    )
    private_runtime_error_by_path_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
        metadata_key="path",
        default_key="unknown",
    )
    private_runtime_error_by_group_counter = _dimension_counter(
        events=events,
        event_type=SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
        metadata_key="route_group",
        default_key="other",
    )
    # 这几个维度服务的是「状态机拒绝」那两条告警，所以口径必须和它一致（只数
    # state_machine）。链上腿失败另有一条 by_path 维度，见下面 chain-gate 那段。
    settlement_transition_denied_by_path_counter = _dimension_counter_with_filter(
        events=events,
        event_type=SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
        metadata_key="path",
        default_key="unknown",
        predicate=lambda event: _transition_denied(event)
        and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE,
    )
    settlement_transition_denied_by_actor_counter = _dimension_counter_with_filter(
        events=events,
        event_type=SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
        metadata_key="actor_id",
        default_key="anonymous",
        predicate=lambda event: _transition_denied(event)
        and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE,
    )
    settlement_transition_denied_by_guard_stage_counter = _dimension_counter_with_filter(
        events=events,
        event_type=SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
        metadata_key="guard_stage",
        default_key="route",
        predicate=lambda event: _transition_denied(event)
        and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE,
    )

    baseline = _compute_baseline_reference(
        baseline_window_minutes=baseline_window_minutes,
    )

    candidate_alerts: list[SecurityOpsAlert] = []

    if failed_auth_count >= failed_auth_threshold:
        # 只算「认得的」来源；unknown 不算一个来源，否则会被当成「第 N+1 个来源」，
        # 把单来源轮询误报成分布式攻击。
        known_sources = sorted(
            ((key, count) for key, count in failed_auth_by_source_counter.items() if key != "unknown"),
            key=lambda item: (-item[1], item[0]),
        )
        distinct_source_count = len(known_sources)
        source_clause = f" from {distinct_source_count} source(s)" if known_sources else ""
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.HIGH,
                alert_type=SecurityOpsAlertType.AUTH_FAILURE_SPIKE,
                message=(
                    f"authentication failures spiked to {failed_auth_count} "
                    f"within {window_minutes}m{source_clause}"
                ),
                metadata={
                    "failed_auth_count": failed_auth_count,
                    "threshold": failed_auth_threshold,
                    "window_minutes": window_minutes,
                    "distinct_source_count": distinct_source_count,
                    "top_sources": [key for key, _ in known_sources[:dimension_limit]],
                },
            )
        )

    for path, count in failed_auth_by_path_counter.items():
        threshold = _scope_threshold(failed_auth_threshold, failed_auth_override_map, path)
        if count >= threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.HIGH,
                    alert_type=SecurityOpsAlertType.AUTH_FAILURE_SPIKE,
                    message=f"endpoint auth failures spiked on {path}: {count}",
                    metadata={
                        "scope_type": "path",
                        "scope_key": path,
                        "failed_auth_count": count,
                        "threshold": threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    for group, count in failed_auth_by_group_counter.items():
        scope_key = f"group:{group}"
        threshold = _scope_threshold(failed_auth_threshold, failed_auth_override_map, scope_key)
        if count >= threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.MEDIUM,
                    alert_type=SecurityOpsAlertType.AUTH_FAILURE_SPIKE,
                    message=f"route-group auth failures spiked on {group}: {count}",
                    metadata={
                        "scope_type": "route_group",
                        "scope_key": group,
                        "failed_auth_count": count,
                        "threshold": threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    if rate_limited_count >= rate_limit_threshold:
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.MEDIUM,
                alert_type=SecurityOpsAlertType.RATE_LIMIT_SPIKE,
                message=f"rate-limit denials spiked to {rate_limited_count} within {window_minutes}m",
                metadata={
                    "rate_limited_count": rate_limited_count,
                    "threshold": rate_limit_threshold,
                    "window_minutes": window_minutes,
                },
            )
        )

    for path, count in rate_limited_by_path_counter.items():
        threshold = _scope_threshold(rate_limit_threshold, rate_limit_override_map, path)
        if count >= threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.MEDIUM,
                    alert_type=SecurityOpsAlertType.RATE_LIMIT_SPIKE,
                    message=f"endpoint rate-limit denials spiked on {path}: {count}",
                    metadata={
                        "scope_type": "path",
                        "scope_key": path,
                        "rate_limited_count": count,
                        "threshold": threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    for group, count in rate_limited_by_group_counter.items():
        scope_key = f"group:{group}"
        threshold = _scope_threshold(rate_limit_threshold, rate_limit_override_map, scope_key)
        if count >= threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.MEDIUM,
                    alert_type=SecurityOpsAlertType.RATE_LIMIT_SPIKE,
                    message=f"route-group rate-limit denials spiked on {group}: {count}",
                    metadata={
                        "scope_type": "route_group",
                        "scope_key": group,
                        "rate_limited_count": count,
                        "threshold": threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    has_private_runtime_volume = verify_request_count >= private_runtime_min_requests
    if private_runtime_error_count >= private_runtime_error_threshold and has_private_runtime_volume:
        severity = (
            SecurityOpsAlertSeverity.CRITICAL
            if private_runtime_error_rate >= private_runtime_error_rate_threshold
            else SecurityOpsAlertSeverity.HIGH
        )
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=severity,
                alert_type=SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_RATE,
                message=(
                    "private runtime error rate exceeded threshold: "
                    f"{private_runtime_error_count}/{verify_request_count} "
                    f"({private_runtime_error_rate:.2%}) in {window_minutes}m"
                ),
                metadata={
                    "private_runtime_error_count": private_runtime_error_count,
                    "verify_request_count": verify_request_count,
                    "error_rate": round(private_runtime_error_rate, 4),
                    "count_threshold": private_runtime_error_threshold,
                    "error_rate_threshold": private_runtime_error_rate_threshold,
                    "min_requests": private_runtime_min_requests,
                    "window_minutes": window_minutes,
                },
            )
        )

    for path, count in private_runtime_error_by_path_counter.items():
        request_count = verify_by_path_counter.get(path, 0)
        if request_count < private_runtime_min_requests:
            continue
        error_rate = float(count) / float(request_count)
        count_threshold = _scope_threshold(
            private_runtime_error_threshold,
            private_runtime_error_override_map,
            path,
        )
        rate_threshold = _scope_threshold(
            private_runtime_error_rate_threshold,
            private_runtime_error_rate_override_map,
            path,
        )
        if count >= count_threshold:
            severity = (
                SecurityOpsAlertSeverity.CRITICAL
                if error_rate >= rate_threshold
                else SecurityOpsAlertSeverity.HIGH
            )
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=severity,
                    alert_type=SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_RATE,
                    message=f"endpoint private runtime errors spiked on {path}: {count}/{request_count} ({error_rate:.2%})",
                    metadata={
                        "scope_type": "path",
                        "scope_key": path,
                        "private_runtime_error_count": count,
                        "verify_request_count": request_count,
                        "error_rate": round(error_rate, 4),
                        "count_threshold": count_threshold,
                        "error_rate_threshold": rate_threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    for group, count in private_runtime_error_by_group_counter.items():
        request_count = verify_by_group_counter.get(group, 0)
        if request_count < private_runtime_min_requests:
            continue
        error_rate = float(count) / float(request_count)
        scope_key = f"group:{group}"
        count_threshold = _scope_threshold(
            private_runtime_error_threshold,
            private_runtime_error_override_map,
            scope_key,
        )
        rate_threshold = _scope_threshold(
            private_runtime_error_rate_threshold,
            private_runtime_error_rate_override_map,
            scope_key,
        )
        if count >= count_threshold:
            severity = (
                SecurityOpsAlertSeverity.CRITICAL
                if error_rate >= rate_threshold
                else SecurityOpsAlertSeverity.HIGH
            )
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=severity,
                    alert_type=SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_RATE,
                    message=f"route-group private runtime errors spiked on {group}: {count}/{request_count} ({error_rate:.2%})",
                    metadata={
                        "scope_type": "route_group",
                        "scope_key": group,
                        "private_runtime_error_count": count,
                        "verify_request_count": request_count,
                        "error_rate": round(error_rate, 4),
                        "count_threshold": count_threshold,
                        "error_rate_threshold": rate_threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    latest_state_machine_denied_iso = (
        latest_state_machine_denied_at.isoformat() if latest_state_machine_denied_at else None
    )

    if settlement_transition_denied_count >= settlement_transition_denied_threshold:
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.HIGH,
                alert_type=SecurityOpsAlertType.SETTLEMENT_TRANSITION_DENIED_SPIKE,
                message=(
                    "settlement state-machine guard rejects spiked to "
                    f"{settlement_transition_denied_count} within {window_minutes}m"
                ),
                metadata={
                    "settlement_transition_denied_count": settlement_transition_denied_count,
                    "settlement_transition_total_count": settlement_transition_total_count,
                    "settlement_transition_denied_rate": round(settlement_transition_denied_rate, 4),
                    "denial_class": DENIAL_CLASS_STATE_MACHINE,
                    "latest_denied_at": latest_state_machine_denied_iso,
                    "threshold": settlement_transition_denied_threshold,
                    "window_minutes": window_minutes,
                },
            )
        )

    # 链上腿失败是**另一类**信号：迁移合法、钱一分没动、autosettle 会一直重试。
    # 单独报（HIGH，够进 WATCH 通知），但**不接自动刹车** —— 刹车拦不住链上腿失败
    # 本身，反倒会把 autosettle 的放款重试和人工恢复一起掐死。
    if settlement_transition_chain_gate_denied_count >= settlement_transition_denied_threshold:
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.HIGH,
                alert_type=SecurityOpsAlertType.SETTLEMENT_TRANSITION_CHAIN_GATE_SPIKE,
                message=(
                    "settlement chain-gate failures on "
                    f"{settlement_transition_chain_gate_denied_count} settlement(s) "
                    f"({len(chain_gate_denials)} retries) within {window_minutes}m "
                    "— on-chain leg rejected; business status rolled back, funds did not move"
                ),
                metadata={
                    "settlement_transition_chain_gate_denied_count": settlement_transition_chain_gate_denied_count,
                    "settlement_transition_chain_gate_event_count": len(chain_gate_denials),
                    "threshold": settlement_transition_denied_threshold,
                    "window_minutes": window_minutes,
                },
            )
        )

    if (
        settlement_transition_total_count >= settlement_transition_min_requests
        and settlement_transition_denied_rate >= settlement_transition_denied_rate_threshold
    ):
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.CRITICAL,
                alert_type=SecurityOpsAlertType.SETTLEMENT_TRANSITION_DENIED_RATE,
                message=(
                    "settlement state-machine reject-rate exceeded threshold: "
                    f"{settlement_transition_denied_count}/{settlement_transition_guard_evaluations} "
                    f"({settlement_transition_denied_rate:.2%}) in {window_minutes}m"
                ),
                metadata={
                    "settlement_transition_denied_count": settlement_transition_denied_count,
                    "settlement_transition_total_count": settlement_transition_total_count,
                    "settlement_transition_guard_evaluations": settlement_transition_guard_evaluations,
                    "settlement_transition_denied_rate": round(settlement_transition_denied_rate, 4),
                    "denial_class": DENIAL_CLASS_STATE_MACHINE,
                    "latest_denied_at": latest_state_machine_denied_iso,
                    "threshold": settlement_transition_denied_rate_threshold,
                    "min_requests": settlement_transition_min_requests,
                    "window_minutes": window_minutes,
                },
            )
        )

    for path, count in settlement_transition_denied_by_path_counter.items():
        threshold = _scope_threshold(
            settlement_transition_denied_threshold,
            settlement_transition_denied_override_map,
            path,
        )
        if count >= threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.MEDIUM,
                    alert_type=SecurityOpsAlertType.SETTLEMENT_TRANSITION_DENIED_SPIKE,
                    message=f"endpoint settlement transition rejects spiked on {path}: {count}",
                    metadata={
                        "scope_type": "path",
                        "scope_key": path,
                        "settlement_transition_denied_count": count,
                        "threshold": threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    # 高敏感操作突增告警（红队报告 KARMA-RT-2026-08-27-001 §5）
    # 仲裁员 resolve / 管理员控制操作属于"能直接决定资金归属"的动作，
    # 窗口内突增可能预示凭据被盗后的批量滥用，须立即告警。
    if privileged_action_count >= privileged_action_threshold:
        candidate_alerts.append(
            SecurityOpsAlert(
                severity=SecurityOpsAlertSeverity.HIGH,
                alert_type=SecurityOpsAlertType.PRIVILEGED_ACTION_SPIKE,
                message=(
                    "privileged (arbitrator/admin-control) actions spiked to "
                    f"{privileged_action_count} within {window_minutes}m"
                ),
                metadata={
                    "privileged_action_count": privileged_action_count,
                    "arbitrator_action_count": arbitrator_action_count,
                    "admin_control_action_count": admin_control_action_count,
                    "threshold": privileged_action_threshold,
                    "window_minutes": window_minutes,
                },
            )
        )

    privileged_by_actor_counter: Counter[str] = Counter()
    for event in events:
        if event.event_type not in (
            SecurityMonitoringEventType.ARBITRATOR_ACTION,
            SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
        ):
            continue
        raw_actor = event.metadata.get("actor_id")
        key = str(raw_actor).strip() if raw_actor else "anonymous"
        privileged_by_actor_counter[key] += 1
    for actor, count in privileged_by_actor_counter.items():
        if count >= privileged_action_threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.MEDIUM,
                    alert_type=SecurityOpsAlertType.PRIVILEGED_ACTION_SPIKE,
                    message=f"privileged actions spiked for actor {actor}: {count}",
                    metadata={
                        "scope_type": "actor",
                        "scope_key": actor,
                        "privileged_action_count": count,
                        "threshold": privileged_action_threshold,
                        "window_minutes": window_minutes,
                    },
                )
            )

    if baseline.sample_count >= baseline_min_sample_count and baseline.failed_auth_avg > 0:
        drift_threshold = baseline.failed_auth_avg * baseline_drift_multiplier
        if failed_auth_count >= drift_threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.HIGH,
                    alert_type=SecurityOpsAlertType.AUTH_FAILURE_BASELINE_DRIFT,
                    message=(
                        f"auth failures drifted above baseline: current={failed_auth_count}, "
                        f"baseline_avg={baseline.failed_auth_avg:.2f}, multiplier={baseline_drift_multiplier:.2f}"
                    ),
                    metadata={
                        "current": failed_auth_count,
                        "baseline_avg": round(baseline.failed_auth_avg, 4),
                        "drift_multiplier": baseline_drift_multiplier,
                        "baseline_window_minutes": baseline_window_minutes,
                        "baseline_samples": baseline.sample_count,
                    },
                )
            )

    if baseline.sample_count >= baseline_min_sample_count and baseline.rate_limited_avg > 0:
        drift_threshold = baseline.rate_limited_avg * baseline_drift_multiplier
        if rate_limited_count >= drift_threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.MEDIUM,
                    alert_type=SecurityOpsAlertType.RATE_LIMIT_BASELINE_DRIFT,
                    message=(
                        f"rate-limit denials drifted above baseline: current={rate_limited_count}, "
                        f"baseline_avg={baseline.rate_limited_avg:.2f}, multiplier={baseline_drift_multiplier:.2f}"
                    ),
                    metadata={
                        "current": rate_limited_count,
                        "baseline_avg": round(baseline.rate_limited_avg, 4),
                        "drift_multiplier": baseline_drift_multiplier,
                        "baseline_window_minutes": baseline_window_minutes,
                        "baseline_samples": baseline.sample_count,
                    },
                )
            )

    if (
        baseline.sample_count >= baseline_min_sample_count
        and baseline.private_runtime_error_rate_avg > 0
        and verify_request_count >= private_runtime_min_requests
    ):
        drift_threshold = baseline.private_runtime_error_rate_avg * baseline_drift_multiplier
        if private_runtime_error_rate >= drift_threshold:
            candidate_alerts.append(
                SecurityOpsAlert(
                    severity=SecurityOpsAlertSeverity.HIGH,
                    alert_type=SecurityOpsAlertType.PRIVATE_RUNTIME_ERROR_BASELINE_DRIFT,
                    message=(
                        "private runtime error-rate drifted above baseline: "
                        f"current={private_runtime_error_rate:.2%}, "
                        f"baseline_avg={baseline.private_runtime_error_rate_avg:.2%}, "
                        f"multiplier={baseline_drift_multiplier:.2f}"
                    ),
                    metadata={
                        "current": round(private_runtime_error_rate, 6),
                        "baseline_avg": round(baseline.private_runtime_error_rate_avg, 6),
                        "drift_multiplier": baseline_drift_multiplier,
                        "baseline_window_minutes": baseline_window_minutes,
                        "baseline_samples": baseline.sample_count,
                    },
                )
            )

    alerts: list[SecurityOpsAlert] = []
    suppressed_alert_count = 0
    for alert in candidate_alerts:
        scope_type = str(alert.metadata.get("scope_type", "global"))
        scope_key = str(alert.metadata.get("scope_key", "global"))
        signature = f"{alert.alert_type.value}:{scope_type}:{scope_key}"
        if _should_emit_alert_now(signature, cooldown_minutes=alert_cooldown_minutes):
            alerts.append(alert)
        else:
            suppressed_alert_count += 1

    escalation = _build_escalation_decision(
        active_alerts=alerts,
        suppressed_alert_count=suppressed_alert_count,
    )
    recommended_actions = _build_recommended_actions(
        active_alerts=alerts,
        escalation=escalation,
    )

    if record_baseline_snapshot:
        _maybe_capture_baseline_snapshot(
            capture_interval_minutes=baseline_capture_interval_minutes,
            failed_auth_count=failed_auth_count,
            rate_limited_count=rate_limited_count,
            private_runtime_error_rate=private_runtime_error_rate,
            verify_request_count=verify_request_count,
        )

    return SecurityOpsAlertReport(
        window_minutes=window_minutes,
        summary=SecurityOpsSummary(
            failed_auth_count=failed_auth_count,
            rate_limited_count=rate_limited_count,
            private_runtime_error_count=private_runtime_error_count,
            verify_request_count=verify_request_count,
            private_runtime_error_rate=private_runtime_error_rate,
            failed_auth_by_path=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.FAILED_AUTH,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
            failed_auth_by_actor=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.FAILED_AUTH,
                metadata_key="actor_id",
                limit=dimension_limit,
                default_key="anonymous",
            ),
            failed_auth_by_route_group=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.FAILED_AUTH,
                metadata_key="route_group",
                limit=dimension_limit,
                default_key="other",
            ),
            failed_auth_by_source=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.FAILED_AUTH,
                metadata_key="client_ip",
                limit=dimension_limit,
                default_key="unknown",
            ),
            rate_limited_by_path=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
            rate_limited_by_actor=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata_key="actor_id",
                limit=dimension_limit,
                default_key="anonymous",
            ),
            rate_limited_by_route_group=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata_key="route_group",
                limit=dimension_limit,
                default_key="other",
            ),
            private_runtime_error_by_path=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
            private_runtime_error_by_route_group=_top_dimension_counts(
                events=events,
                event_type=SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata_key="route_group",
                limit=dimension_limit,
                default_key="other",
            ),
            settlement_transition_total_count=settlement_transition_total_count,
            settlement_transition_denied_count=settlement_transition_denied_count,
            settlement_transition_denied_rate=settlement_transition_denied_rate,
            settlement_transition_chain_gate_denied_count=settlement_transition_chain_gate_denied_count,
            settlement_transition_denied_by_class=_denial_class_dimension_counts(
                events=settlement_audits,
                limit=dimension_limit,
            ),
            settlement_transition_denied_by_path=_top_dimension_counts(
                events=[
                    event
                    for event in settlement_audits
                    if _transition_denied(event)
                    and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE
                ],
                event_type=SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata_key="path",
                limit=dimension_limit,
                default_key="unknown",
            ),
            settlement_transition_denied_by_actor=_top_dimension_counts(
                events=[
                    event
                    for event in settlement_audits
                    if _transition_denied(event)
                    and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE
                ],
                event_type=SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata_key="actor_id",
                limit=dimension_limit,
                default_key="anonymous",
            ),
            settlement_transition_denied_by_guard_stage=_top_dimension_counts(
                events=[
                    event
                    for event in settlement_audits
                    if _transition_denied(event)
                    and _denial_class_of(event) == DENIAL_CLASS_STATE_MACHINE
                ],
                event_type=SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata_key="guard_stage",
                limit=dimension_limit,
                default_key="route",
            ),
            arbitrator_action_count=arbitrator_action_count,
            admin_control_action_count=admin_control_action_count,
            privileged_action_by_actor=[
                SecurityOpsDimensionCount(
                    key=actor,
                    count=count,
                    last_seen_at=max(
                        (
                            event.created_at
                            for event in events
                            if event.event_type
                            in (
                                SecurityMonitoringEventType.ARBITRATOR_ACTION,
                                SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
                            )
                            and str(event.metadata.get("actor_id", "")).strip() == actor
                        ),
                        default=None,
                    ),
                )
                for actor, count in privileged_by_actor_counter.most_common(dimension_limit)
            ],
        ),
        alerts=alerts,
        suppressed_alert_count=suppressed_alert_count,
        baseline=baseline,
        escalation=escalation,
        recommended_actions=recommended_actions,
    )
