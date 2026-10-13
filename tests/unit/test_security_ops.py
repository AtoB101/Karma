from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

import pytest

import services.security_monitoring as security_monitoring
from config.settings import settings
from httptest import post_minimal_contract
from services.security_monitoring import (
    SecurityMonitoringEventType,
    build_security_ops_alert_report,
    clear_security_events,
    record_security_event,
)
from services.runtime_safety import get_runtime_safety_mode_state, set_runtime_safety_mode


def test_build_security_ops_alert_report_detects_spikes():
    clear_security_events()
    try:
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        for _ in range(10):
            record_security_event(
                SecurityMonitoringEventType.VERIFY_REQUEST,
                metadata={"path": "/v1/verify", "actor_id": "agent-v", "route_group": "verification"},
            )
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata={"path": "/v1/verify", "actor_id": "agent-v", "route_group": "verification"},
            )

        report = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=3,
            rate_limit_threshold=3,
            private_runtime_error_threshold=3,
            private_runtime_error_rate_threshold=0.3,
            private_runtime_min_requests=5,
            dimension_limit=3,
            alert_cooldown_minutes=0,
        )
        alert_types = {item.alert_type.value for item in report.alerts}
        assert "auth_failure_spike" in alert_types
        assert "rate_limit_spike" in alert_types
        assert "private_runtime_error_rate" in alert_types
        assert report.summary.private_runtime_error_rate == pytest.approx(0.4)
        assert report.summary.failed_auth_by_path[0].key == "/v1/auth/token"
        assert report.summary.failed_auth_by_actor[0].key == "anonymous"
        assert report.summary.failed_auth_by_route_group[0].key == "auth"
        assert report.summary.private_runtime_error_by_path[0].key == "/v1/verify"
        assert report.summary.private_runtime_error_by_route_group[0].key == "verification"
        assert report.baseline.sample_count == 0
        assert report.escalation.level.value == "page"
        assert report.recommended_actions
    finally:
        clear_security_events()


def test_security_ops_alert_suppression_cooldown():
    clear_security_events()
    try:
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        first = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=1,
            alert_cooldown_minutes=10,
        )
        second = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=1,
            alert_cooldown_minutes=10,
        )
        assert any(item.alert_type.value == "auth_failure_spike" for item in first.alerts)
        assert second.suppressed_alert_count >= 1
        assert second.escalation.level.value in {"watch", "none"}
    finally:
        clear_security_events()


def test_security_ops_threshold_overrides_support_endpoint_and_group():
    clear_security_events()
    try:
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        report = build_security_ops_alert_report(
            window_minutes=15,
            failed_auth_threshold=100,
            failed_auth_threshold_overrides="/v1/auth/token=2,group:auth=2",
            alert_cooldown_minutes=0,
        )
        scoped = [item for item in report.alerts if item.alert_type.value == "auth_failure_spike"]
        assert scoped
        assert any(item.metadata.get("scope_type") == "path" for item in scoped)
        assert any(item.metadata.get("scope_type") == "route_group" for item in scoped)
    finally:
        clear_security_events()


def test_security_ops_baseline_drift_alert_detected():
    clear_security_events()
    try:
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        warmup = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=9999,
            baseline_min_sample_count=1,
            baseline_drift_multiplier=1.5,
            baseline_capture_interval_minutes=0,
            alert_cooldown_minutes=0,
        )
        assert warmup.baseline.sample_count == 0

        for _ in range(8):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        drifted = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=9999,
            baseline_min_sample_count=1,
            baseline_drift_multiplier=1.5,
            baseline_capture_interval_minutes=0,
            alert_cooldown_minutes=0,
        )
        assert drifted.baseline.sample_count >= 1
        assert any(item.alert_type.value == "auth_failure_baseline_drift" for item in drifted.alerts)
    finally:
        clear_security_events()


def test_security_ops_detects_settlement_transition_denied_rate_alert():
    clear_security_events()
    try:
        for _ in range(8):
            record_security_event(
                SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata={
                    "path": "/v1/settlement/task-x/submit",
                    "actor_id": "worker-risk",
                    "guard_stage": "route",
                    "transition_allowed": False,
                },
            )
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata={
                    "path": "/v1/settlement/task-x/submit",
                    "actor_id": "worker-risk",
                    "guard_stage": "route",
                    "transition_allowed": True,
                },
            )
        report = build_security_ops_alert_report(
            window_minutes=30,
            settlement_transition_denied_threshold=3,
            settlement_transition_denied_rate_threshold=0.5,
            settlement_transition_min_requests=5,
            settlement_transition_denied_threshold_overrides="/v1/settlement/task-x/submit=2",
            alert_cooldown_minutes=0,
        )
        assert report.summary.settlement_transition_total_count == 10
        assert report.summary.settlement_transition_denied_count == 8
        assert report.summary.settlement_transition_denied_rate == pytest.approx(0.8)
        assert any(item.alert_type.value == "settlement_transition_denied_spike" for item in report.alerts)
        assert any(item.alert_type.value == "settlement_transition_denied_rate" for item in report.alerts)
    finally:
        clear_security_events()


@pytest.mark.asyncio
async def test_security_ops_alerts_endpoint_returns_report(client, monkeypatch):
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        "ops-alert-reader:ops-alert-reader-secret-abcdef",
    )
    # /v1/security/ops/alerts 收紧为运维白名单：这个用例就是在扮演运维岗。
    monkeypatch.setattr(settings, "admin_actor_ids", "ops-alert-reader")
    hdr = {"X-Karma-Api-Key": "karma_ops-alert-reader_ops-alert-reader-secret-abcdef"}
    clear_security_events()
    try:
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
                metadata={"path": "/v1/verify", "actor_id": "agent-r", "route_group": "verification"},
            )
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.VERIFY_REQUEST,
                metadata={"path": "/v1/verify", "actor_id": "agent-r", "route_group": "verification"},
            )
        for _ in range(2):
            record_security_event(
                SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata={"path": "/v1/verify", "actor_id": "agent-r", "route_group": "verification"},
            )

        response = await client.get(
            "/v1/security/ops/alerts"
            "?window_minutes=30"
            "&failed_auth_threshold=1"
            "&rate_limit_threshold=1"
            "&private_runtime_error_threshold=1"
            "&private_runtime_error_rate_threshold=0.2"
            "&private_runtime_min_requests=2"
            "&dimension_limit=5"
            "&alert_cooldown_minutes=0",
            headers=hdr,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["failed_auth_count"] == 2
        assert payload["summary"]["rate_limited_count"] == 2
        assert payload["summary"]["private_runtime_error_count"] == 2
        assert payload["summary"]["verify_request_count"] == 4
        assert payload["summary"]["settlement_transition_total_count"] == 0
        assert payload["summary"]["settlement_transition_denied_count"] == 0
        assert payload["summary"]["failed_auth_by_path"][0]["key"] == "/v1/auth/token"
        assert payload["summary"]["rate_limited_by_actor"][0]["key"] == "agent-r"
        assert payload["summary"]["rate_limited_by_route_group"][0]["key"] == "verification"
        assert payload["suppressed_alert_count"] == 0
        assert "baseline" in payload
        assert payload["escalation"]["level"] in {"watch", "page"}
        assert isinstance(payload["recommended_actions"], list)
        alert_types = {item["alert_type"] for item in payload["alerts"]}
        assert "auth_failure_spike" in alert_types
        assert "rate_limit_spike" in alert_types
        assert "private_runtime_error_rate" in alert_types
    finally:
        clear_security_events()


@pytest.mark.asyncio
async def test_security_ops_endpoint_auto_brakes_on_transition_critical(client, monkeypatch):
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        "ops-alert-reader:ops-alert-reader-secret-abcdef",
    )
    # /v1/security/ops/alerts 收紧为运维白名单：这个用例就是在扮演运维岗。
    monkeypatch.setattr(settings, "admin_actor_ids", "ops-alert-reader")
    hdr = {"X-Karma-Api-Key": "karma_ops-alert-reader_ops-alert-reader-secret-abcdef"}
    clear_security_events()
    set_runtime_safety_mode(enabled=False, reason="test reset", actor_id="test")
    try:
        task_id = "task-transition-abuse-001"
        # 同 test_admin_controls：用本用例自己的买方，别去借共享库里别人用过的
        # ``buyer-001``（那行的 available_credits 可能已经被别的用例花光）。
        buyer = "buyer-sec-ops-001"
        await client.post(f"/v1/capacity/{buyer}/lock", json={"amount": 10.0})
        await post_minimal_contract(
            client,
            task_id=task_id,
            client_agent_id=buyer,
            escrow_amount=10.0,
            expected_step_count=1,
        )
        created = await client.post(
            "/v1/settlement/create",
            json={
                "task_id": task_id,
                "client_agent_id": buyer,
                "escrow_amount": 10.0,
                "currency": "USD",
            },
        )
        assert created.status_code == 201
        denied = await client.post(f"/v1/settlement/{task_id}/submit", json={})
        assert denied.status_code == 409

        report = await client.get(
            "/v1/security/ops/alerts"
            "?window_minutes=30"
            "&settlement_transition_denied_threshold=1"
            "&settlement_transition_denied_rate_threshold=0.4"
            "&settlement_transition_min_requests=2"
            "&alert_cooldown_minutes=0"
            "&auto_brake_on_transition_critical=true"
            "&auto_brake_actor_id=sec-auto",
            headers=hdr,
        )
        assert report.status_code == 200
        alert_types = {item["alert_type"] for item in report.json()["alerts"]}
        assert "settlement_transition_denied_rate" in alert_types
        state = get_runtime_safety_mode_state()
        assert state.enabled is True
        assert state.triggered_by == "sec-auto"
    finally:
        set_runtime_safety_mode(enabled=False, reason="test cleanup", actor_id="test")
        clear_security_events()


@pytest.mark.asyncio
async def test_auto_brake_is_not_re_armed_on_evidence_older_than_the_manual_override(client, monkeypatch):
    """人工清闸之后，窗口里那批**旧**拒绝不许再把闸自动拉回去（自锁回归测试）。

    线上形状：拒绝尖峰 -> 闸落下 -> 人看清、清闸 -> 60 分钟窗口里那批旧拒绝还在 ->
    下一轮轮询用同一批证据把闸拉回去（02:43 清、02:45 跳回）。规则是只认比人工清闸
    **更晚发生**的拒绝；这是迟滞，不是取消刹车 —— 清闸之后新出现的拒绝照样能拉回去。
    """
    monkeypatch.setattr(
        settings,
        "auth_api_keys",
        "ops-alert-reader:ops-alert-reader-secret-abcdef",
    )
    monkeypatch.setattr(settings, "admin_actor_ids", "ops-alert-reader")
    hdr = {"X-Karma-Api-Key": "karma_ops-alert-reader_ops-alert-reader-secret-abcdef"}
    clear_security_events()
    set_runtime_safety_mode(enabled=False, reason="test reset", actor_id="test")
    query = (
        "/v1/security/ops/alerts"
        "?window_minutes=30"
        "&settlement_transition_denied_threshold=1"
        "&settlement_transition_denied_rate_threshold=0.4"
        "&settlement_transition_min_requests=2"
        "&alert_cooldown_minutes=0"
        "&auto_brake_on_transition_critical=true"
    )
    try:
        stale = datetime.utcnow() - timedelta(minutes=20)
        for _ in range(6):
            _transition_event(
                allowed=False, guard_stage="route", task_id="task-stale",
                actor_id="attacker", at=stale,
            )
        for _ in range(4):
            _transition_event(allowed=True, guard_stage="store", task_id="task-stale", at=stale)
        # 人看过这批拒绝，把闸放回去。
        set_runtime_safety_mode(enabled=False, reason="reviewed", actor_id="ops-admin")

        first = await client.get(query, headers=hdr)
        assert first.status_code == 200
        payload = first.json()
        assert "settlement_transition_denied_rate" in {item["alert_type"] for item in payload["alerts"]}
        assert get_runtime_safety_mode_state().enabled is False
        assert any("Auto-brake suppressed" in item for item in payload["recommended_actions"])

        # 清闸之后**新发生**的拒绝仍然能把闸拉回去。
        fresh = datetime.utcnow() + timedelta(seconds=1)
        for _ in range(6):
            _transition_event(
                allowed=False, guard_stage="route", task_id="task-fresh",
                actor_id="attacker", at=fresh,
            )
        second = await client.get(query, headers=hdr)
        assert second.status_code == 200
        assert get_runtime_safety_mode_state().enabled is True
    finally:
        set_runtime_safety_mode(enabled=False, reason="test cleanup", actor_id="test")
        clear_security_events()


@pytest.mark.asyncio
async def test_security_ops_middleware_tracks_failed_auth(client):
    original_env = settings.app_env
    original_keys = settings.auth_api_keys
    original_enforce = settings.auth_enforce_protected_routes
    original_admins = settings.admin_actor_ids
    clear_security_events()
    try:
        settings.app_env = "test"
        settings.auth_api_keys = "agent-security:secret-value-123"
        settings.auth_enforce_protected_routes = True
        settings.admin_actor_ids = "agent-security"

        unauthorized = await client.post("/v1/capacity/id-security/lock", json={"amount": 10})
        assert unauthorized.status_code == 401

        report = await client.get(
            "/v1/security/ops/alerts?window_minutes=15&failed_auth_threshold=1",
            headers={"X-Karma-Api-Key": "karma_agent-security_secret-value-123"},
        )
        assert report.status_code == 200
        body = report.json()
        assert body["summary"]["failed_auth_count"] >= 1
        assert any(item["alert_type"] == "auth_failure_spike" for item in body["alerts"])
    finally:
        settings.app_env = original_env
        settings.auth_api_keys = original_keys
        settings.auth_enforce_protected_routes = original_enforce
        settings.admin_actor_ids = original_admins
        clear_security_events()


def test_security_ops_tracks_privileged_actions_and_alerts():
    """红队报告 KARMA-RT-2026-08-27-001 §5：
    仲裁员 resolve 与管理员控制操作必须进入安全监控，突增触发告警。"""
    clear_security_events()
    try:
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.ARBITRATOR_ACTION,
                metadata={
                    "path": "/v1/disputes/resolve",
                    "actor_id": "arb-1",
                    "route_group": "arbitration",
                    "dispute_id": f"dispute-{_}",
                    "outcome": "refund",
                },
            )
        for _ in range(3):
            record_security_event(
                SecurityMonitoringEventType.ADMIN_CONTROL_ACTION,
                metadata={
                    "path": "/v1/admin/controls/safety-mode",
                    "actor_id": "admin-1",
                    "route_group": "admin",
                    "action": "safety-mode",
                    "enabled": True,
                },
            )

        report = build_security_ops_alert_report(
            window_minutes=30,
            privileged_action_threshold=3,
            alert_cooldown_minutes=0,
        )
        assert report.summary.arbitrator_action_count == 3
        assert report.summary.admin_control_action_count == 3
        assert report.summary.privileged_action_by_actor
        assert any(
            item.alert_type.value == "privileged_action_spike" for item in report.alerts
        ), "privileged action spike alert expected"
        assert any(
            "privileged" in action for action in report.recommended_actions
        ), "recommended action for privileged spike expected"
    finally:
        clear_security_events()

def test_security_events_survive_a_container_recreate(monkeypatch, tmp_path):
    """容器重建（每次发布都会做）会把进程内存清零，事件必须在磁盘日志里活下来。

    2026-10-02 实测缺口：18:12:50Z 打尖峰 → 18:15:17Z 发布重建容器 → 18:20:00Z
    轮询看到空报表，什么都没投。检测窗口就这么被发布清掉了。
    """
    monkeypatch.setenv("KARMA_SECURITY_EVENT_JOURNAL", str(tmp_path / "events.jsonl"))
    clear_security_events()
    try:
        for _ in range(4):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/auth/token", "actor_id": "anonymous", "route_group": "auth"},
            )
        assert len(security_monitoring._list_recent_events(30)) == 4

        # 模拟容器重建：进程内存清零，磁盘上的日志还在
        monkeypatch.setattr(security_monitoring, "_EVENTS", deque(maxlen=10_000))

        events = security_monitoring._list_recent_events(30)
        assert len(events) == 4, "重建后事件必须还在，而且不能重复计数"
        report = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=3,
            alert_cooldown_minutes=0,
        )
        assert "auth_failure_spike" in {item.alert_type.value for item in report.alerts}
    finally:
        clear_security_events()


def _transition_event(*, allowed, guard_stage, task_id="task-x", path="/v1/settlement/task-x/submit",
                      actor_id="worker-risk", at=None):
    record_security_event(
        SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
        metadata={
            "task_id": task_id,
            "path": path,
            "actor_id": actor_id,
            "guard_stage": guard_stage,
            "transition_allowed": allowed,
        },
        created_at=at,
    )


def test_chain_gate_rejects_do_not_feed_the_state_machine_denied_rate():
    """链上腿失败不许冒充「状态机拒绝」（2026-10-13 线上自锁的根因）。

    线上样本：19 张卡在 ``auto_confirmed`` 的结算单被 autosettle 在同一秒各拒一次，
    ``guard_stage=chain``。升级前的算法把它们算进拒绝率 —— 19/88 = 21.6% >= 20%，
    CRITICAL 成立 -> 自动刹车；人工清闸后窗口里那批事件还在，下一轮轮询又拉回去。
    这里把当时的形状原样摆出来：拒绝率必须归零，链上腿失败另走一条 HIGH 告警。
    """
    clear_security_events()
    try:
        for index in range(19):
            _transition_event(
                allowed=False,
                guard_stage="chain",
                task_id=f"task-stuck-{index}",
                path="/internal/auto-confirm",
                actor_id="system:auto-confirm",
            )
        for _ in range(69):
            _transition_event(allowed=True, guard_stage="store")

        report = build_security_ops_alert_report(window_minutes=60, alert_cooldown_minutes=0)

        assert report.summary.settlement_transition_total_count == 88
        # 状态机拒绝 = 0：链上腿失败一分钱没动，不算「有人在非法穿越状态机」。
        assert report.summary.settlement_transition_denied_count == 0
        assert report.summary.settlement_transition_denied_rate == 0.0
        # 但它没有被藏起来 —— 单独一条告警，按**单子**去重（19 张卡，不是 19 次重试）。
        assert report.summary.settlement_transition_chain_gate_denied_count == 19
        assert {item.key: item.count for item in report.summary.settlement_transition_denied_by_class} == {
            "chain_gate": 19
        }
        alert_types = {item.alert_type.value for item in report.alerts}
        assert "settlement_transition_chain_gate_spike" in alert_types
        assert "settlement_transition_denied_rate" not in alert_types
        assert "settlement_transition_denied_spike" not in alert_types
    finally:
        clear_security_events()


def test_chain_gate_alert_counts_settlements_not_retries():
    """同一张卡被 autosettle 重试 20 次是一条故障，不是 20 条 —— 告警按 task 去重。"""
    clear_security_events()
    try:
        for _ in range(20):
            _transition_event(allowed=False, guard_stage="chain", task_id="task-stuck-1",
                              path="/internal/auto-confirm", actor_id="system:auto-confirm")
        report = build_security_ops_alert_report(
            window_minutes=60,
            settlement_transition_denied_threshold=1,
            alert_cooldown_minutes=0,
        )
        assert report.summary.settlement_transition_chain_gate_denied_count == 1
        chain_alerts = [
            item
            for item in report.alerts
            if item.alert_type.value == "settlement_transition_chain_gate_spike"
        ]
        assert len(chain_alerts) == 1
        assert chain_alerts[0].metadata["settlement_transition_chain_gate_event_count"] == 20
        assert chain_alerts[0].severity.value == "high"
    finally:
        clear_security_events()


def test_state_machine_denials_still_drive_the_denied_rate_alert():
    """真信号不许被上面的分离削弱：route/pipeline 拒绝照旧算拒绝率、照旧 CRITICAL。"""
    clear_security_events()
    try:
        for _ in range(8):
            _transition_event(allowed=False, guard_stage="route")
        for _ in range(2):
            _transition_event(allowed=True, guard_stage="store")
        report = build_security_ops_alert_report(
            window_minutes=30,
            settlement_transition_denied_threshold=3,
            settlement_transition_denied_rate_threshold=0.5,
            settlement_transition_min_requests=5,
            alert_cooldown_minutes=0,
        )
        assert report.summary.settlement_transition_denied_count == 8
        assert report.summary.settlement_transition_denied_rate == pytest.approx(0.8)
        critical = [
            item
            for item in report.alerts
            if item.alert_type.value == "settlement_transition_denied_rate"
        ]
        assert len(critical) == 1
        assert critical[0].severity.value == "critical"
        # 迟滞判断要用它：这批证据里最新一次状态机拒绝发生在什么时候。
        assert critical[0].metadata["latest_denied_at"]
        assert critical[0].metadata["denial_class"] == "state_machine"
    finally:
        clear_security_events()


def test_legacy_events_without_denial_class_fall_back_to_guard_stage():
    """升级前写的事件没有 denial_class，按 guard_stage 现推 —— 历史窗口不能读错。"""
    clear_security_events()
    try:
        for _ in range(6):
            record_security_event(
                SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata={
                    "task_id": "old-task",
                    "path": "/v1/settlement/old/submit",
                    "actor_id": "attacker",
                    "guard_stage": "pipeline",
                    "transition_allowed": False,
                },
            )
        for _ in range(6):
            record_security_event(
                SecurityMonitoringEventType.SETTLEMENT_TRANSITION_AUDIT,
                metadata={
                    "task_id": "old-stuck",
                    "path": "/internal/auto-confirm",
                    "actor_id": "system:auto-confirm",
                    "guard_stage": "chain",
                    "transition_allowed": False,
                },
            )
        report = build_security_ops_alert_report(window_minutes=30, alert_cooldown_minutes=0)
        assert report.summary.settlement_transition_denied_count == 6
        assert report.summary.settlement_transition_denied_by_guard_stage[0].key == "pipeline"
        assert report.summary.settlement_transition_chain_gate_denied_count == 1
    finally:
        clear_security_events()


def test_unwritable_event_journal_degrades_to_memory_only(monkeypatch, tmp_path):
    """日志写不进去（只读挂载 / 磁盘满 / 路径不对）时该退回纯内存，
    而不是把异常带进请求路径。"""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KARMA_SECURITY_EVENT_JOURNAL", str(blocker / "events.jsonl"))
    clear_security_events()
    try:
        record_security_event(
            SecurityMonitoringEventType.FAILED_AUTH,
            metadata={"path": "/v1/auth/token", "route_group": "auth"},
        )
        assert len(security_monitoring._list_recent_events(15)) == 1
        report = build_security_ops_alert_report(window_minutes=15, alert_cooldown_minutes=0)
        assert report.summary.failed_auth_count == 1
    finally:
        clear_security_events()


# ---------------------------------------------------------------------------
# 失败来源（client_ip）：一个来源 vs 很多来源 ——「过期会话轮询」和「分布式撞密钥」
# 的分水岭。2026-10-13 线上实测：单来源轮询一小时能刷 ~250 条匿名 401。
# ---------------------------------------------------------------------------
def test_auth_failure_spike_reports_single_source_and_self_heal_hint():
    clear_security_events()
    try:
        for _ in range(6):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={
                    "path": "/v1/capacity/kid_x",
                    "actor_id": "anonymous",
                    "route_group": "capacity",
                    "client_ip": "198.51.100.7",
                },
            )
        report = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=3,
            dimension_limit=5,
            alert_cooldown_minutes=0,
        )
        global_spikes = [
            alert
            for alert in report.alerts
            if alert.alert_type.value == "auth_failure_spike"
            and "distinct_source_count" in alert.metadata
        ]
        assert global_spikes, "expected the global auth_failure_spike alert"
        assert global_spikes[0].metadata["distinct_source_count"] == 1
        assert global_spikes[0].metadata["top_sources"] == ["198.51.100.7"]
        assert report.summary.failed_auth_by_source[0].key == "198.51.100.7"
        # 单来源 → 先提示「查是不是过期会话在轮询」，不是「轮换密钥」
        assert any("expired" in action.lower() for action in report.recommended_actions)
        assert not any("rotate" in action.lower() for action in report.recommended_actions)
    finally:
        clear_security_events()


def test_auth_failure_spike_many_sources_recommends_key_rotation():
    clear_security_events()
    try:
        for index in range(6):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={
                    "path": "/v1/auth/token",
                    "actor_id": "anonymous",
                    "route_group": "auth",
                    "client_ip": f"203.0.113.{index}",
                },
            )
        report = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=3,
            dimension_limit=5,
            alert_cooldown_minutes=0,
        )
        global_spikes = [
            alert
            for alert in report.alerts
            if alert.alert_type.value == "auth_failure_spike"
            and "distinct_source_count" in alert.metadata
        ]
        assert global_spikes, "expected the global auth_failure_spike alert"
        assert global_spikes[0].metadata["distinct_source_count"] == 6
        assert any("rotate" in action.lower() for action in report.recommended_actions)
    finally:
        clear_security_events()


def test_auth_failure_without_client_ip_is_not_counted_as_a_source():
    # 升级前写下的老事件没有 client_ip：不能把它当成「第 N+1 个来源」，
    # 否则单来源轮询会被误报成分布式攻击。
    clear_security_events()
    try:
        for _ in range(6):
            record_security_event(
                SecurityMonitoringEventType.FAILED_AUTH,
                metadata={"path": "/v1/capacity/kid_x", "actor_id": "anonymous", "route_group": "capacity"},
            )
        report = build_security_ops_alert_report(
            window_minutes=30,
            failed_auth_threshold=3,
            dimension_limit=5,
            alert_cooldown_minutes=0,
        )
        global_spikes = [
            alert
            for alert in report.alerts
            if alert.alert_type.value == "auth_failure_spike"
            and "distinct_source_count" in alert.metadata
        ]
        assert global_spikes
        assert global_spikes[0].metadata["distinct_source_count"] == 0
        assert global_spikes[0].metadata["top_sources"] == []
    finally:
        clear_security_events()