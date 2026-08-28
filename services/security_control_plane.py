"""Off-chain Security Control Plane — detect, classify, alert, freeze (not a funds mover)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal

from services.security_monitoring import SecurityMonitoringEventType, record_security_event

FreezeScope = Literal["global", "agent", "bill", "binding"]

_LOCK = Lock()
_INCIDENTS: list["SecurityIncident"] = []
_FREEZE: dict[str, Any] = {
    "global_until": None,
    "reason": None,
    "actor_id": None,
    "updated_at": None,
}


@dataclass
class SecurityIncident:
    incident_id: str
    created_at: datetime
    severity: str
    classification: str
    actor_id: str
    freeze_scope: FreezeScope | None
    freeze_requested: bool
    on_chain_submitted: bool
    detail: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_freeze_state() -> dict[str, Any]:
    with _LOCK:
        return dict(_FREEZE)


def list_incidents(limit: int = 50) -> list[SecurityIncident]:
    with _LOCK:
        return list(_INCIDENTS[-limit:])


def classify_and_maybe_freeze(
    *,
    classification: str,
    severity: str,
    actor_id: str,
    reason: str,
    freeze_scope: FreezeScope | None = "global",
    duration_seconds: int = 3600,
    submit_on_chain: bool = False,
) -> SecurityIncident:
    """CRITICAL → freeze request. On-chain submit is optional (needs freezeOperator key)."""
    freeze_requested = severity.lower() == "critical" and freeze_scope is not None
    on_chain = False
    incident = SecurityIncident(
        incident_id=f"inc-{int(_now().timestamp())}-{len(_INCIDENTS)+1}",
        created_at=_now(),
        severity=severity.upper(),
        classification=classification,
        actor_id=actor_id,
        freeze_scope=freeze_scope if freeze_requested else None,
        freeze_requested=freeze_requested,
        on_chain_submitted=False,
        detail={"reason": reason, "duration_seconds": duration_seconds},
    )
    if freeze_requested:
        until = _now().timestamp() + duration_seconds
        with _LOCK:
            _FREEZE.update(
                {
                    "global_until": until if freeze_scope == "global" else _FREEZE.get("global_until"),
                    "reason": reason,
                    "actor_id": actor_id,
                    "updated_at": _now().isoformat(),
                    "scope": freeze_scope,
                    "duration_seconds": duration_seconds,
                }
            )
        record_security_event(
            SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
            metadata={
                "action": "emergency_freeze",
                "scope": freeze_scope,
                "actor_id": actor_id,
                "reason": reason,
            },
        )
        from services.runtime_safety import set_runtime_operational_pauses

        set_runtime_operational_pauses(
            pause_new_lock=True,
            pause_new_authorization=True,
            pause_new_task=True,
            pause_new_settlement=True,
            reason=f"control-plane freeze: {reason}",
            actor_id=actor_id,
        )
        if submit_on_chain:
            try:
                from services.chain.settlement_adapter import OnChainSettlementAdapter

                adapter = OnChainSettlementAdapter()
                adapter.emergency_freeze_global(duration_seconds, reason)
                on_chain = True
            except Exception as exc:  # pragma: no cover — chain optional in unit tests
                incident.detail["on_chain_error"] = str(exc)
    incident.on_chain_submitted = on_chain
    with _LOCK:
        _INCIDENTS.append(incident)
    return incident


def clear_control_plane_state() -> None:
    global _INCIDENTS
    with _LOCK:
        _INCIDENTS = []
        _FREEZE.update(
            {
                "global_until": None,
                "reason": None,
                "actor_id": None,
                "updated_at": None,
                "scope": None,
            }
        )
    from services.runtime_safety import set_runtime_operational_pauses

    set_runtime_operational_pauses(
        pause_new_lock=False,
        pause_new_authorization=False,
        pause_new_task=False,
        pause_new_settlement=False,
        reason="control-plane state cleared",
        actor_id="system",
    )


def funds_overview() -> dict[str, Any]:
    from services.security_monitoring import build_security_ops_alert_report

    report = build_security_ops_alert_report(window_minutes=60, alert_cooldown_minutes=0)
    freeze = current_freeze_state()
    critical = [a for a in report.alerts if a.severity.value == "critical"]
    high = [a for a in report.alerts if a.severity.value == "high"]
    return {
        "total_locked_funds": "see /v1/capacity and on-chain totalLocked",
        "pending_verification": None,
        "pending_settlement": None,
        "pending_dispute": None,
        "settled": None,
        "refunded": None,
        "frozen_funds": freeze,
        "critical_alerts": len(critical),
        "high_risk_events": len(high),
        "failed_settlement": report.summary.settlement_transition_denied_count,
        "invalid_state_transition": report.summary.settlement_transition_denied_count,
        "unauthorized_attempts": report.summary.failed_auth_count,
        "abnormal_payout": 0,
        "active_incidents": [
            {
                "incident_id": i.incident_id,
                "severity": i.severity,
                "classification": i.classification,
                "freeze_requested": i.freeze_requested,
                "on_chain_submitted": i.on_chain_submitted,
                "created_at": i.created_at.isoformat(),
                "detail": i.detail,
            }
            for i in list_incidents()
        ],
        "alerts": [
            {
                "type": a.alert_type.value,
                "severity": a.severity.value,
                "title": a.message,
            }
            for a in report.alerts
        ],
        "recommended_actions": report.recommended_actions,
        "generated_at": _now().isoformat(),
    }
