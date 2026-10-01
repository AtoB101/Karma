from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "security_alert_poller.py"


def _load():
    spec = importlib.util.spec_from_file_location("karma_ops_alert_poller", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


poller = _load()


def _alert(alert_type: str, severity: str, scope: str | None = None, message: str = "m") -> dict:
    meta = {"scope_key": scope} if scope else {}
    return {
        "alert_id": os.urandom(8).hex(),  # 每次请求都是新的 uuid，不该被当成身份
        "alert_type": alert_type,
        "severity": severity,
        "message": message,
        "metadata": meta,
    }


# --------------------------------------------------------------------------
# 归一化 / 差分
# --------------------------------------------------------------------------
def test_alert_key_ignores_volatile_alert_id():
    first = poller.alert_key(_alert("auth_failure_spike", "high", "/v1/auth/token"))
    second = poller.alert_key(_alert("auth_failure_spike", "high", "/v1/auth/token"))
    assert first == second == "auth_failure_spike|/v1/auth/token"


def test_normalize_alerts_keeps_highest_severity_for_same_key():
    report = {
        "alerts": [
            _alert("rate_limit_spike", "medium", "/v1/verify", "low one"),
            _alert("rate_limit_spike", "critical", "/v1/verify", "worse one"),
        ]
    }
    normalized = poller.normalize_alerts(report)
    assert list(normalized) == ["rate_limit_spike|/v1/verify"]
    assert normalized["rate_limit_spike|/v1/verify"]["severity"] == "critical"
    assert normalized["rate_limit_spike|/v1/verify"]["message"] == "worse one"


def test_compute_diff_reports_only_new_and_resolved():
    now = 1_000_000.0
    prev = {"a|": {"severity": "high", "message": "a", "notified_at": now - 60}}
    current = {
        "a|": {"severity": "high", "message": "a"},
        "b|": {"severity": "high", "message": "b"},
    }
    born, resolved = poller.compute_diff(prev, current, now, repeat_seconds=3600)
    assert [item["key"] for item in born] == ["b|"]
    assert born[0]["reason"] == "new"
    assert resolved == []

    born2, resolved2 = poller.compute_diff(prev, {}, now, repeat_seconds=3600)
    assert born2 == []
    assert [item["key"] for item in resolved2] == ["a|"]
    assert resolved2[0]["reason"] == "resolved"


def test_compute_diff_repeats_still_active_alert_after_interval():
    now = 1_000_000.0
    prev = {"a|": {"severity": "high", "message": "a", "notified_at": now - 60}}
    current = {"a|": {"severity": "high", "message": "a"}}

    quiet, _ = poller.compute_diff(prev, current, now, repeat_seconds=3600)
    assert quiet == [], "持续中的告警在冷却期内不该重复刷屏"

    loud, _ = poller.compute_diff(prev, current, now, repeat_seconds=30)
    assert [item["reason"] for item in loud] == ["still-active"]


def test_merge_seen_preserves_first_seen_and_notified_stamp():
    now = 1_000_000.0
    prev = {"a|": {"severity": "high", "message": "a",
                   "first_seen_at": now - 500, "notified_at": now - 400}}
    current = {"a|": {"severity": "high", "message": "a"}}
    merged = poller.merge_seen(prev, current, born=[], now=now)
    assert merged["a|"]["first_seen_at"] == now - 500
    assert merged["a|"]["notified_at"] == now - 400

    born = [{"key": "a|", "severity": "high", "message": "a",
             "reason": "still-active", "notify_at": now}]
    merged2 = poller.merge_seen(prev, current, born=born, now=now)
    assert merged2["a|"]["notified_at"] == now


# --------------------------------------------------------------------------
# 本机检查
# --------------------------------------------------------------------------
def _snapshot(root: Path, name: str, dump_bytes: int, manifest: str = "") -> Path:
    snap = root / name
    snap.mkdir(parents=True, exist_ok=True)
    with open(snap / "karma-db.sql.gz", "wb") as fh:
        fh.write(b"x" * dump_bytes)
    if manifest:
        (snap / "manifest.txt").write_text(manifest, encoding="utf-8")
    return snap


def test_local_checks_flags_missing_backup(tmp_path):
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert any(c["key"] == "karma_local|backup_missing" for c in checks)


def test_local_checks_flags_empty_dump(tmp_path):
    _snapshot(tmp_path, "20260101-000000", 10)
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert any(c["key"] == "karma_local|backup_empty" for c in checks)


def test_local_checks_flags_stale_snapshot(tmp_path):
    snap = _snapshot(tmp_path, "20260101-000000", 5000)
    old = time.time() - 30 * 3600
    os.utime(snap, (old, old))
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    stale = [c for c in checks if c["key"] == "karma_local|backup_stale"]
    assert stale and "30" in stale[0]["message"]


def test_local_checks_passes_fresh_snapshot_and_reads_manifest(tmp_path):
    _snapshot(tmp_path, "20260101-000000", 5000, manifest="verify_status=ok\noffsite_status=ok\n")
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert checks == []


def test_local_checks_flags_failed_restore_drill(tmp_path):
    _snapshot(tmp_path, "20260101-000000", 5000,
              manifest="verify_status=failed\noffsite_status=ok\n")
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert any(c["key"] == "karma_local|backup_verify_failed" for c in checks)


def test_local_checks_flags_failed_offsite(tmp_path):
    _snapshot(tmp_path, "20260101-000000", 5000,
              manifest="verify_status=ok\noffsite_status=failed\n")
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert any(c["key"] == "karma_local|backup_offsite_failed" for c in checks)


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
def test_load_ops_env_parses_quotes_and_comments(tmp_path):
    path = tmp_path / ".env.ops"
    path.write_text(
        "# comment\n"
        "KARMA_ALERT_WEBHOOK_URL=\"https://hooks.example.com/karma\"\n"
        "KARMA_BACKUP_OFFSITE=s3\n"
        "BROKEN LINE\n"
        "\n",
        encoding="utf-8",
    )
    parsed = poller.load_ops_env(str(path))
    assert parsed["KARMA_ALERT_WEBHOOK_URL"] == "https://hooks.example.com/karma"
    assert parsed["KARMA_BACKUP_OFFSITE"] == "s3"
    assert "BROKEN LINE" not in parsed


def test_load_ops_env_missing_file_is_empty():
    assert poller.load_ops_env("/nonexistent/karma/.env.ops") == {}


def test_cfg_prefers_environment_over_ops_file(monkeypatch):
    monkeypatch.setenv("KARMA_ALERT_WINDOW_MINUTES", "15")
    assert poller.cfg({"KARMA_ALERT_WINDOW_MINUTES": "99"}, "window_minutes") == "15"


def test_resolve_api_key_prefers_explicit_then_picks_ops_admin(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTH_API_KEYS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("AUTH_API_KEYS=ops-arbitrator:aaa,ops-admin:bbb,ops-governance:ccc\n",
                        encoding="utf-8")
    monkeypatch.setenv("KARMA_ENV_FILE", str(env_file))

    key, source = poller.resolve_api_key({})
    assert key == "bbb"
    assert str(env_file) in source

    key2, source2 = poller.resolve_api_key({"KARMA_ALERT_API_KEY": "explicit"})
    assert key2 == "explicit"
    assert source2 == "KARMA_ALERT_API_KEY"


def test_resolve_api_key_without_ops_admin_returns_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTH_API_KEYS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("AUTH_API_KEYS=someone-else:aaa\n", encoding="utf-8")
    monkeypatch.setenv("KARMA_ENV_FILE", str(env_file))
    key, _ = poller.resolve_api_key({})
    assert key == ""


def test_egress_targets_requires_complete_config(monkeypatch):
    assert poller.egress_targets({}) == []
    assert poller.egress_targets({"KARMA_ALERT_TELEGRAM_BOT_TOKEN": "t"}) == []
    assert poller.egress_targets({
        "KARMA_ALERT_TELEGRAM_BOT_TOKEN": "t",
        "KARMA_ALERT_TELEGRAM_CHAT_ID": "1",
    }) == ["telegram"]


# --------------------------------------------------------------------------
# 传输
# --------------------------------------------------------------------------
class _Recorder(BaseHTTPRequestHandler):
    requests: list = []

    def do_GET(self):  # noqa: N802
        type(self).requests.append({"method": "GET", "path": self.path,
                                    "headers": {k.lower(): v for k, v in self.headers.items()}})
        body = json.dumps({
            "window_minutes": 60,
            "summary": {"failed_auth_count": 7, "rate_limited_count": 2},
            "alerts": [
                {"alert_id": "x", "alert_type": "auth_failure_spike", "severity": "high",
                 "message": "spiked", "metadata": {"scope_key": "/v1/auth/token"}},
            ],
            "escalation": {"level": "page", "reason": "high severity"},
            "recommended_actions": ["rotate the key"],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).requests.append({"method": "POST", "path": self.path,
                                    "headers": {k.lower(): v for k, v in self.headers.items()},
                                    "body": raw})
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture()
def fake_http():
    _Recorder.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fetch_report_sends_api_key_and_query(fake_http):
    report = poller.fetch_report(fake_http, "secret-key", 60, 30, 10)

    assert report["alerts"][0]["alert_type"] == "auth_failure_spike"
    sent = _Recorder.requests[0]
    assert sent["headers"]["x-karma-api-key"] == "secret-key"
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(sent["path"]).query)
    assert query == {"window_minutes": ["60"], "alert_cooldown_minutes": ["30"]}


def test_deliver_posts_webhook_payload(fake_http, capsys):
    sent = poller.deliver(
        {"KARMA_ALERT_WEBHOOK_URL": fake_http + "/hook"},
        "[Karma] test", "body text",
        {"kind": "security_alerts", "text": "body text"}, dry_run=False,
    )

    assert sent == ["webhook"]
    request = _Recorder.requests[0]
    assert request["path"] == "/hook"
    assert request["headers"]["content-type"] == "application/json"
    assert json.loads(request["body"].decode())["kind"] == "security_alerts"
    assert "body text" in capsys.readouterr().out, "出口发出去之后本地日志也要留一份"


def test_deliver_falls_back_to_stdout_when_no_egress_configured(capsys):
    sent = poller.deliver({}, "[Karma] test", "only stdout", {}, dry_run=False)
    assert sent == ["log"]
    assert "only stdout" in capsys.readouterr().out


def test_deliver_dry_run_does_not_send(fake_http, capsys):
    sent = poller.deliver({"KARMA_ALERT_WEBHOOK_URL": fake_http + "/hook"},
                          "s", "text", {}, dry_run=True)
    assert sent == ["webhook"]
    assert _Recorder.requests == []
    assert "would send to: webhook" in capsys.readouterr().out


def test_render_text_contains_severity_summary_and_actions():
    report = {
        "escalation": {"level": "page", "reason": "high severity"},
        "summary": {"failed_auth_count": 7, "rate_limited_count": 2,
                    "private_runtime_error_count": 0},
        "window_minutes": 60,
        "recommended_actions": ["rotate the key"],
    }
    text = poller.render_text(
        "[Karma] 1 security alert(s)",
        [{"key": "auth_failure_spike|/v1/auth/token", "severity": "high",
          "message": "spiked", "alert_type": "auth_failure_spike"}],
        [], report,
    )
    assert "[HIGH] spiked" in text
    assert "escalation: page" in text
    assert "failed_auth=7" in text
    assert "rotate the key" in text


def test_state_round_trip(tmp_path):
    path = str(tmp_path / "state" / "security-alerts.json")
    poller.save_state(path, {"last_ok_ts": 12.5, "seen": {"a|": {"severity": "high"}}})
    assert poller.load_state(path)["seen"]["a|"]["severity"] == "high"
    assert poller.load_state(str(tmp_path / "nope.json")) == {}


def test_save_state_is_atomic_and_leaves_no_tmp(tmp_path):
    path = str(tmp_path / "security-alerts.json")
    poller.save_state(path, {"a": 1})
    assert json.loads(Path(path).read_text(encoding="utf-8")) == {"a": 1}
    assert not (tmp_path / "security-alerts.json.tmp").exists()