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


def test_local_checks_ignores_non_snapshot_dirs(tmp_path):
    """deploy 脚本会往备份目录里放 web-<ts> 的网站备份，它不是数据库快照。"""
    (tmp_path / "web-20261001-185618").mkdir()
    checks = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert [c["key"] for c in checks] == ["karma_local|backup_missing"]

    _snapshot(tmp_path, "20261001-180000", 5000, manifest="verify_status=ok\n")
    checks2 = poller.local_checks(str(tmp_path), 26, str(tmp_path), 90)
    assert checks2 == [], "真正的时间戳快照应该被认出来，web-* 目录应该被忽略"


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
    assert str(env_file) in source
    # 客户端发的是 karma_<actor>_<secret>，不是配置里的 actor:secret。
    # 2026-10-01 用错格式时服务端回的是 401「Authentication required」——
    # 看起来像钥匙错，其实是格式错。
    assert key == "karma_ops-admin_bbb"
    assert key.startswith("karma_")
    assert key.split("_", 2)[0] == "karma"
    assert key.split("_", 2)[1] == "ops-admin"

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
    sent, failed = poller.deliver(
        {"KARMA_ALERT_WEBHOOK_URL": fake_http + "/hook"},
        "[Karma] test", "body text",
        {"kind": "security_alerts", "text": "body text"}, dry_run=False,
    )

    assert sent == ["webhook"]
    assert failed == []
    request = _Recorder.requests[0]
    assert request["path"] == "/hook"
    assert request["headers"]["content-type"] == "application/json"
    assert json.loads(request["body"].decode())["kind"] == "security_alerts"
    assert "body text" in capsys.readouterr().out, "出口发出去之后本地日志也要留一份"


def test_deliver_falls_back_to_stdout_when_no_egress_configured(capsys):
    sent, failed = poller.deliver({}, "[Karma] test", "only stdout", {}, dry_run=False)
    assert sent == ["log"]
    assert failed == []
    assert "only stdout" in capsys.readouterr().out


def test_deliver_dry_run_does_not_send(fake_http, capsys):
    sent, failed = poller.deliver({"KARMA_ALERT_WEBHOOK_URL": fake_http + "/hook"},
                                  "s", "text", {}, dry_run=True)
    assert sent == ["webhook"]
    assert failed == []
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


# --------------------------------------------------------------------------
# 出口的失败语义
#
# 这一段是 2026-10-01 补的。起因：要把告警出口接到 Telegram 上，先回头审了一遍
# 「出口发不出去的时候会发生什么」，发现四件事 —— 每一件都会让「告警能到达人」
# 这句话在最需要它的那一刻失效。
# --------------------------------------------------------------------------
DEAD_WEBHOOK = "http://127.0.0.1:9/hook"  # 9 = discard，本机不会有东西在听


def test_a_failing_egress_still_leaves_the_alert_in_the_local_log(capsys):
    """出口发不出去时，cron 日志里必须还有这条告警的原文。

    以前的顺序是「先发、后 print」，任何一个出口抛异常，最后那行 print 就永远
    执行不到：出口坏掉的那一刻，恰好也是日志里什么都没有的那一刻。
    """
    sent, failed = poller.deliver({"KARMA_ALERT_WEBHOOK_URL": DEAD_WEBHOOK},
                                  "[Karma] 1 security alert(s)", "ALERT-原文-不能丢", {},
                                  dry_run=False)

    assert sent == []
    assert len(failed) == 1 and failed[0].startswith("webhook (")
    assert "ALERT-原文-不能丢" in capsys.readouterr().out


def test_one_dead_egress_does_not_block_the_other(monkeypatch):
    """多出口的意义就是冗余：webhook 挂了不该让 Telegram 也收不到。"""
    delivered = []
    monkeypatch.setattr(poller, "send_telegram",
                        lambda token, chat_id, text, timeout: delivered.append((token, chat_id)))

    sent, failed = poller.deliver({
        "KARMA_ALERT_WEBHOOK_URL": DEAD_WEBHOOK,
        "KARMA_ALERT_TELEGRAM_BOT_TOKEN": "123456:AA" + "x" * 30,
        "KARMA_ALERT_TELEGRAM_CHAT_ID": "-1001234567890",
    }, "[Karma] test", "text", {}, dry_run=False)

    assert sent == ["telegram"], "webhook 死了，telegram 仍然要发"
    assert len(failed) == 1 and failed[0].startswith("webhook (")
    assert delivered == [("123456:AA" + "x" * 30, "-1001234567890")]


def test_telegram_failure_never_writes_the_bot_token_to_logs_or_state(monkeypatch, capsys):
    """Telegram 的 token 就在请求 URL 的路径里，而 urllib 会把整条 URL 放进异常。

    这条异常要进 stderr（→ /var/log/karma-alerts.log）和状态文件的 last_egress_error，
    两个地方都会跟着备份、日志采集一起走。一次网络抖动不该等于一次密钥泄露。

    （这里的 token 是故意写成不像真 token 的样子的：仓库是公开的，不该在源码里放一个
    能骗过扫描器的 Telegram token 字面量。真正的兜底不是形状正则，见下一个用例。）
    """
    token = "seeded-by-ops-env-not-a-real-token"
    url = "https://api.telegram.org/bot%s/sendMessage" % token

    def boom(*_args, **_kwargs):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(poller, "http_post_json", boom)
    sent, failed = poller.deliver({
        "KARMA_ALERT_TELEGRAM_BOT_TOKEN": token,
        "KARMA_ALERT_TELEGRAM_CHAT_ID": "-1001234567890",
    }, "[Karma] test", "text", {}, dry_run=False)

    assert sent == [] and len(failed) == 1
    captured = capsys.readouterr()
    for blob in (failed[0], captured.out, captured.err):
        assert token not in blob, "token 不能出现在任何会被写进日志的地方"
    assert "401" in failed[0], "抹掉密钥，但不能把失败原因也一起抹掉"


def test_redact_catches_a_token_that_is_not_in_the_ops_file():
    """兜底那一道：token 是从**环境变量**给的时候，ops_env 里没有它，抹不掉。

    所以还需要一条按形状认的规则（bot<数字>:<长串>）。前缀故意用 4 位数字 ——
    真的 Telegram token 是 8-10 位，用 4 位既能测到规则，又不会在公开仓库里留下
    一个能骗过密钥扫描器的字面量。
    """
    token = "9001:AAFakeTokenForTestsOnly_0123456789abcd"
    text = "HTTP Error 401: Unauthorized at https://api.telegram.org/bot%s/sendMessage" % token

    scrubbed = poller.redact(text, {})

    assert "9001:" not in scrubbed
    assert "AAFakeTokenForTestsOnly" not in scrubbed
    assert "bot<redacted>" in scrubbed
    assert "HTTP Error 401" in scrubbed


def test_redact_survives_the_obvious_next_change_of_printing_the_whole_exception():
    """实测：现在 str(exc) 里没有 token，但 HTTPError.url 里有。

    也就是说「为了排查方便把异常打全一点」这一步（%r，或者把 exc.url 打出来）会立刻
    把 token 写进 cron 日志。这个用例锁的就是那一步 —— 别让一次调试习惯变成一次泄露。
    """
    token = "9001:AAFakeTokenForTestsOnly_0123456789abcd"
    exc = urllib.error.HTTPError(
        "https://api.telegram.org/bot%s/sendMessage" % token, 401, "Unauthorized", None, None)

    assert token not in str(exc), "前提变了：str(exc) 现在带 token 了，注释要跟着改"
    for blob in (repr(exc), "%s" % exc.url, "url=%r" % exc):
        assert token not in poller.redact(blob, {})


def test_redact_scrubs_config_secrets_echoed_in_errors(monkeypatch):
    ops_env = {"KARMA_ALERT_SMTP_PASSWORD": "hunter2-not-in-logs"}
    text = poller.redact("login failed: password=hunter2-not-in-logs", ops_env)
    assert "hunter2-not-in-logs" not in text
    assert "login failed" in text


def _selftest_env(tmp_path, lines, state_path=None):
    """写一份临时的 .env.ops。

    默认把状态文件钉在 tmp_path 里：不钉的话自检会去写生产路径
    /opt/karma/state/security-alerts.json —— 单测不该有这种副作用。
    """
    lines = list(lines)
    if not any(l.startswith("KARMA_ALERT_STATE_PATH=") for l in lines):
        lines.append("KARMA_ALERT_STATE_PATH="
                     + str(state_path or (tmp_path / "state" / "security-alerts.json")))
    path = tmp_path / ".env.ops"
    path.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    return str(path)


def test_selftest_exit_code_is_nonzero_when_the_egress_is_not_configured(monkeypatch, tmp_path, capsys):
    """没配出口时 --test 说「成功」，等于把自检变成一个空头支票。"""
    monkeypatch.setenv("KARMA_OPS_ENV", _selftest_env(tmp_path, []))
    assert poller.main(["--test"]) == 5
    assert "nothing was actually sent" in capsys.readouterr().err


def test_selftest_exit_code_is_nonzero_when_the_egress_is_unreachable(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KARMA_OPS_ENV",
                       _selftest_env(tmp_path, ["KARMA_ALERT_WEBHOOK_URL=" + DEAD_WEBHOOK]))
    assert poller.main(["--test"]) == 5
    assert "selftest could not reach" in capsys.readouterr().err


def test_selftest_exit_code_is_zero_when_the_egress_accepts_it(monkeypatch, tmp_path, fake_http):
    monkeypatch.setenv("KARMA_OPS_ENV",
                       _selftest_env(tmp_path, ["KARMA_ALERT_WEBHOOK_URL=" + fake_http + "/hook"]))
    assert poller.main(["--test"]) == 0
    assert _Recorder.requests[-1]["path"] == "/hook"


def test_selftest_records_the_result_so_the_gate_has_something_to_judge(
        monkeypatch, tmp_path, fake_http):
    """健康的服务器上真实告警可能几个月都不出现。

    自检的结果如果不落进状态文件，G4 就永远没有东西可判 —— 配置填对了也只能一直
    挂着 HUMAN。所以自检要落状态，同时把来源标出来（src=selftest）。
    """
    state_path = tmp_path / "state" / "security-alerts.json"
    monkeypatch.setenv("KARMA_OPS_ENV", _selftest_env(
        tmp_path, ["KARMA_ALERT_WEBHOOK_URL=" + fake_http + "/hook"], state_path))

    assert poller.main(["--test"]) == 0

    state = poller.load_state(str(state_path))
    assert state["last_egress_ok_ts"] > 0
    assert state["last_egress_src"] == "selftest", "自检不能冒充真实告警送达"
    assert state["last_egress_error"] is None


def test_failed_selftest_records_the_failure(monkeypatch, tmp_path):
    state_path = tmp_path / "state" / "security-alerts.json"
    monkeypatch.setenv("KARMA_OPS_ENV", _selftest_env(
        tmp_path, ["KARMA_ALERT_WEBHOOK_URL=" + DEAD_WEBHOOK], state_path))

    assert poller.main(["--test"]) == 5

    state = poller.load_state(str(state_path))
    assert state["last_egress_error"].startswith("webhook (")
    assert state.get("last_egress_ok_ts") is None


def test_selftest_without_egress_does_not_erase_an_earlier_real_failure(monkeypatch, tmp_path):
    """什么都没验到的自检，不许把上一次真实发送失败这件事抹掉。"""
    state_path = tmp_path / "state" / "security-alerts.json"
    poller.save_state(str(state_path), {"last_egress_error": "webhook (URLError: down)",
                                        "last_egress_error_ts": 1.0, "seen": {}})
    monkeypatch.setenv("KARMA_OPS_ENV", _selftest_env(tmp_path, [], state_path))

    assert poller.main(["--test"]) == 5
    assert poller.load_state(str(state_path))["last_egress_error"] == "webhook (URLError: down)"


def test_dry_run_selftest_writes_no_state(monkeypatch, tmp_path):
    state_path = tmp_path / "state" / "security-alerts.json"
    monkeypatch.setenv("KARMA_OPS_ENV", _selftest_env(
        tmp_path, ["KARMA_ALERT_WEBHOOK_URL=" + DEAD_WEBHOOK], state_path))

    assert poller.main(["--test", "--dry-run"]) == 0
    assert poller.load_state(str(state_path)) == {}


def test_a_successful_alert_emit_clears_an_earlier_egress_failure():
    state = {"last_egress_error": "webhook (URLError: down)", "last_egress_error_ts": 1.0}
    poller.record_egress_result(state, ["telegram"], [], 99.0, "alerts")

    assert state["last_egress_error"] is None
    assert state["last_egress_error_ts"] is None
    assert state["last_egress_ok_ts"] == 99.0
    assert state["last_egress_src"] == "alerts"


def test_selftest_and_real_alert_keep_separate_sticky_timestamps():
    """B3「真告警送达过」和 G5「自检送达过」是两个结论，谁都不许顶掉谁。

    状态里的 last_egress_* 只记最近一次：真告警一来，自检那条就没了 ——
    于是「系统更健康」反而会让 G5 变红。所以两条证据分开存。
    """
    state = {}
    poller.record_egress_result(state, ["telegram"], [], 100.0, "selftest")
    assert state["last_selftest_ok_ts"] == 100.0
    assert state.get("last_alert_ok_ts") is None

    poller.record_egress_result(state, ["telegram"], [], 200.0, "alerts")
    assert state["last_alert_ok_ts"] == 200.0
    assert state["last_selftest_ok_ts"] == 100.0, "真告警不得把自检记录顶掉"
    assert state["last_egress_src"] == "alerts"


def test_sticky_timestamps_are_not_written_when_nothing_was_actually_sent():
    """["log"] 不是发送。粘性时间戳也不能被它写进去。"""
    state = {}
    poller.record_egress_result(state, ["log"], [], 5.0, "selftest")
    poller.record_egress_result(state, ["log"], [], 6.0, "alerts")
    assert state.get("last_selftest_ok_ts") is None
    assert state.get("last_alert_ok_ts") is None
    assert state.get("last_egress_ok_ts") is None


def test_record_egress_result_does_not_call_stdout_a_delivery():
    """什么都没配的时候 deliver() 返回 ["log"] —— 那不是「发出去了」。"""
    state = {}
    poller.record_egress_result(state, ["log"], [], 5.0, "alerts")
    assert state.get("last_egress_ok_ts") is None


def test_selftest_refreshes_the_configured_egress_list(monkeypatch, tmp_path, fake_http):
    """自检也要把 egress 刷成「当前配了什么」。

    生产上踩到的：刚配好 Telegram 就跑 --test，发送明明成功了（状态里 ok_ts 有值），
    但 egress 还是上一次的 ['log'] —— 闸门 G4 报「no alert egress configured」。
    原因：G4 读的是 egress，而 --test 只写了健康字段。自检本该是「配完了，验一下」的
    那一刻，状态文件反而在这一刻最不一致，说不过去。
    """
    state_path = tmp_path / "state" / "security-alerts.json"
    poller.save_state(str(state_path), {
        "last_run_ts": time.time(), "last_ok_ts": time.time(),
        "egress": ["log"], "active": [], "seen": {}})
    monkeypatch.setenv("KARMA_OPS_ENV", _selftest_env(
        tmp_path, ["KARMA_ALERT_WEBHOOK_URL=" + fake_http + "/hook"], state_path))

    assert poller.main(["--test"]) == 0

    state = poller.load_state(str(state_path))
    assert state["egress"] == ["webhook"], "自检之后 egress 还是旧值，闸门会误判「没配出口」"
    assert state["last_egress_ok_ts"] > 0
