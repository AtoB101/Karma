#!/usr/bin/env python3
"""Karma 安全告警出口 —— 把「有人该知道的事」送出这台机器。

问题
----
应用有 /v1/security/ops/alerts（拉取式报表），服务器上也有宝塔的 cron，但**没有任何
东西去拉它**：没有 prometheus、没有 grafana、没有 node_exporter，容器 env 里也没有
任何 SMTP/webhook/Sentry 配置。告警生成了，然后烂在内存里。

这个脚本每 5 分钟跑一次，做三件事：
  1. 拉 /v1/security/ops/alerts（用 ops-admin 那把钥匙），把告警归一化成稳定 id，
     和上次的状态比 —— 只在**新出现**/**刚消失**的时候出声，不刷屏；
  2. 顺带做几条本机检查（备份是不是新鲜、恢复演练过没过、磁盘、日志）；
  3. 把要说的东西交给配置好的出口：webhook / Telegram / SMTP。都没配就写 stdout，
     也就是 cron 的日志 —— 那种情况下闸门 G4 会打印 HUMAN 等人签字。

纯标准库：生产服务器上没有 jq、没有 cast、没有 rclone，也不该为此再装东西。

用法:
  security_alert_poller.py                跑一轮（cron 用这个）
  security_alert_poller.py --test         发一条测试告警，验证出口真的通
  security_alert_poller.py --dry-run      只打印，不发
  security_alert_poller.py --json         结果打一行 JSON

退出码: 0 正常 / 2 配置错 / 3 拉取或出口失败 / 4 本轮有新告警。
（cron 会因此给你发信；4 是「有话说」，不是「脚本坏了」。）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re as _re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

# 快照目录名：YYYYmmdd-HHMMSS（scripts/ops/backup.sh 生成）
_SNAPSHOT_NAME = _re.compile(r"^\d{8}-\d{6}$")

DEFAULTS = {
    "base_url": "http://127.0.0.1:8000",
    "state_path": "/opt/karma/state/security-alerts.json",
    "window_minutes": 60,
    "cooldown_minutes": 30,
    "repeat_minutes": 360,
    "backup_root": "/opt/karma/backups",
    "backup_max_age_hours": 26,
    "disk_path": "/opt/karma",
    "disk_max_percent": 90,
    "timeout": 20,
}

SEVERITY_ORDER = {"info": 0, "medium": 1, "high": 2, "critical": 3}


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
def load_ops_env(path: str | None = None) -> dict[str, str]:
    """读一个 KEY=VALUE 文件（默认 /opt/karma/.env.ops），返回 dict。

    自己解析而不是 source：这个脚本是 python，不该往 shell 里 eval 一个文件。
    """
    path = path or os.environ.get("KARMA_OPS_ENV", "/opt/karma/.env.ops")
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                out[key.strip()] = value
    except OSError:
        return {}
    return out


def cfg(ops_env: dict[str, str], name: str, default=None):
    """环境变量优先，其次 .env.ops，最后默认值。"""
    env_name = "KARMA_ALERT_" + name.upper()
    if env_name in os.environ and os.environ[env_name] != "":
        return os.environ[env_name]
    if env_name in ops_env and ops_env[env_name] != "":
        return ops_env[env_name]
    return DEFAULTS.get(name, default)


def resolve_api_key(ops_env: dict[str, str]) -> tuple[str, str]:
    """返回 (X-Karma-Api-Key 头里该放的串, 来源说明)。

    两种格式不是一回事，别混：
      * AUTH_API_KEYS 配置里是 ``actor:secret``（服务端的映射表）；
      * 客户端发的是 ``karma_<actor>_<secret>``（api/middleware/auth.py 的
        ``_parse_api_key`` 按 ``karma_`` split("_", 2)）。
    2026-10-01 真踩过：拿 actor:secret 去发头直接 401。而且 401 看起来像「钥匙错了」，
    不像「格式错了」，所以这里把话说清楚。

    优先 KARMA_ALERT_API_KEY（已经是完整串）。没有就去 /opt/karma/.env 的
    AUTH_API_KEYS 里找 actor 叫 ops-admin 的那把 —— 告警报表属于平台管理员角色。
    """
    direct = cfg(ops_env, "api_key", "") or ""
    if direct:
        return direct, "KARMA_ALERT_API_KEY"

    keys_blob = os.environ.get("AUTH_API_KEYS", "")
    source = "environment AUTH_API_KEYS"
    if not keys_blob:
        env_file = os.environ.get("KARMA_ENV_FILE", "/opt/karma/.env")
        try:
            with open(env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith("AUTH_API_KEYS="):
                        keys_blob = line.split("=", 1)[1].strip().strip("\"'")
                        source = env_file + " AUTH_API_KEYS"
                        break
        except OSError:
            pass

    for entry in keys_blob.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        actor, _, secret = entry.partition(":")
        actor, secret = actor.strip(), secret.strip()
        if actor == "ops-admin" and secret:
            return "karma_%s_%s" % (actor, secret), source
    return "", ""


# --------------------------------------------------------------------------
# 归一化 / 差分（纯函数，单测直接打这些）
# --------------------------------------------------------------------------
def alert_key(alert: dict) -> str:
    meta = alert.get("metadata") or {}
    scope = meta.get("scope_key") or meta.get("scope_type") or ""
    return "%s|%s" % (alert.get("alert_type", "unknown"), scope)


def normalize_alerts(report: dict) -> dict[str, dict]:
    """把报表里的 alerts 变成 {稳定 key: 摘要}。alert_id 每次请求都是新的 uuid，
    拿它当身份等于每轮都当成新告警 —— 那是刷屏，不是告警。"""
    out: dict[str, dict] = {}
    for alert in report.get("alerts") or []:
        key = alert_key(alert)
        severity = str(alert.get("severity", "info"))
        entry = out.get(key)
        if entry is None or SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(entry["severity"], 0):
            out[key] = {
                "severity": severity,
                "message": alert.get("message", ""),
                "alert_type": alert.get("alert_type", "unknown"),
            }
    return out


def compute_diff(prev_seen: dict, current: dict, now: float,
                 repeat_seconds: float) -> tuple[list[dict], list[dict]]:
    """返回 (要报的新事件, 消解事件)。

    已经报过、且还在持续的告警，只有在超过 repeat_seconds 之后才再报一次 ——
    持续 6 小时的问题不该每 5 分钟喊一遍，但也不该安静到被人忘掉。
    """
    born, resolved = [], []
    for key, entry in sorted(current.items()):
        prev = prev_seen.get(key)
        if prev is None:
            born.append({"key": key, **entry, "reason": "new"})
        elif now - float(prev.get("notified_at", 0)) >= repeat_seconds:
            born.append({"key": key, **entry, "reason": "still-active"})
    for key, entry in sorted(prev_seen.items()):
        if key not in current:
            resolved.append({"key": key, **entry, "reason": "resolved"})
    return born, resolved


def merge_seen(prev_seen: dict, current: dict, born: list[dict], now: float) -> dict:
    new_seen: dict[str, dict] = {}
    notified = {item["key"]: item for item in born if item["reason"] != "resolved"}
    for key, entry in current.items():
        prev = prev_seen.get(key) or {}
        new_seen[key] = {
            **entry,
            "first_seen_at": prev.get("first_seen_at", now),
            "notified_at": notified[key]["notify_at"] if key in notified else prev.get("notified_at", 0),
        }
    return new_seen


# --------------------------------------------------------------------------
# 本机检查
# --------------------------------------------------------------------------
def local_checks(backup_root: str, max_age_hours: float, disk_path: str,
                 disk_max_percent: float) -> list[dict]:
    """备份/磁盘这类「不进应用报表但一样要命」的事。key 固定在 karma_local| 下，
    和应用的告警共用同一套差分逻辑。"""
    checks: list[dict] = []
    now = time.time()

    # 只认时间戳命名的快照。deploy 脚本会往同一个目录里放 ``web-<ts>`` 的网站备份，
    # 那里面没有 karma-db.sql.gz —— 2026-10-01 拿它当「备份是空的」报过一次假警。
    try:
        candidates = [
            os.path.join(backup_root, d)
            for d in os.listdir(backup_root)
            if _SNAPSHOT_NAME.match(d)
        ]
        snapshots = sorted(candidates, key=os.path.getmtime, reverse=True)
    except OSError:
        snapshots = []

    if not snapshots:
        checks.append({
            "key": "karma_local|backup_missing",
            "severity": "critical",
            "alert_type": "backup_missing",
            "message": "no snapshot under %s - there is no backup at all" % backup_root,
        })
    else:
        newest = snapshots[0]
        dump = os.path.join(newest, "karma-db.sql.gz")
        age_h = (now - os.path.getmtime(newest)) / 3600.0
        if not os.path.isfile(dump) or os.path.getsize(dump) < 1024:
            checks.append({
                "key": "karma_local|backup_empty",
                "severity": "critical",
                "alert_type": "backup_empty",
                "message": "newest snapshot %s has no usable karma-db.sql.gz" % newest,
            })
        elif age_h > max_age_hours:
            checks.append({
                "key": "karma_local|backup_stale",
                "severity": "high",
                "alert_type": "backup_stale",
                "message": "newest snapshot is %.1fh old (limit %.0fh) - backup schedule may be broken"
                           % (age_h, max_age_hours),
            })

        manifest = os.path.join(newest, "manifest.txt")
        verify_status = ""
        offsite_status = ""
        try:
            with open(manifest, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("verify_status="):
                        verify_status = line.split("=", 1)[1].strip()
                    elif line.startswith("offsite_status="):
                        offsite_status = line.split("=", 1)[1].strip()
        except OSError:
            pass
        if verify_status == "failed":
            checks.append({
                "key": "karma_local|backup_verify_failed",
                "severity": "critical",
                "alert_type": "backup_verify_failed",
                "message": "restore drill FAILED on %s - the backup may not be restorable" % newest,
            })
        if offsite_status == "failed":
            checks.append({
                "key": "karma_local|backup_offsite_failed",
                "severity": "high",
                "alert_type": "backup_offsite_failed",
                "message": "offsite copy FAILED for %s - only the on-disk copy exists" % newest,
            })

    # statvfs 是 POSIX 的；Windows 上没有这个函数，单测跑在 Windows 上时要能跳过
    if hasattr(os, "statvfs"):
        try:
            st = os.statvfs(disk_path)
            used_pct = 100.0 * (st.f_blocks - st.f_bfree) / float(st.f_blocks)
            if used_pct >= disk_max_percent:
                checks.append({
                    "key": "karma_local|disk_pressure",
                    "severity": "high",
                    "alert_type": "disk_pressure",
                    "message": "%s is %.0f%% full" % (disk_path, used_pct),
                })
        except OSError:
            pass

    return checks


# --------------------------------------------------------------------------
# 拉取
# --------------------------------------------------------------------------
def fetch_report(base_url: str, api_key: str, window_minutes: int,
                 cooldown_minutes: int, timeout: int) -> dict:
    query = urllib.parse.urlencode({
        "window_minutes": window_minutes,
        "alert_cooldown_minutes": cooldown_minutes,
    })
    url = "%s/v1/security/ops/alerts?%s" % (base_url.rstrip("/"), query)
    req = urllib.request.Request(url, headers={
        "X-Karma-Api-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "karma-alert-poller",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------
# 出口
# --------------------------------------------------------------------------
def render_text(subject: str, new_items: list[dict], resolved: list[dict],
                report: dict) -> str:
    lines = [subject]
    esc = (report.get("escalation") or {})
    if esc.get("level") and esc["level"] != "none":
        lines.append("escalation: %s (%s)" % (esc["level"], esc.get("reason", "")))
    lines.append("")
    for item in new_items:
        lines.append("[%s] %s  (%s)" % (item["severity"].upper(), item["message"], item["key"]))
    for item in resolved:
        lines.append("[cleared] %s" % item["key"])
    summary = report.get("summary") or {}
    if summary:
        lines.append("")
        lines.append("failed_auth=%s rate_limited=%s private_runtime_errors=%s window=%sm" % (
            summary.get("failed_auth_count", 0),
            summary.get("rate_limited_count", 0),
            summary.get("private_runtime_error_count", 0),
            report.get("window_minutes", "?"),
        ))
    actions = report.get("recommended_actions") or []
    if actions:
        lines.append("")
        lines.append("recommended:")
        lines.extend("  - " + str(a) for a in actions[:5])
    lines.append("")
    lines.append("host=%s at=%s" % (
        os.uname().nodename if hasattr(os, "uname") else "?",
        _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    ))
    return "\n".join(lines)


def http_post_json(url: str, payload: dict, timeout: int, headers: dict | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def send_telegram(token: str, chat_id: str, text: str, timeout: int) -> None:
    http_post_json(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        {"chat_id": chat_id, "text": text[:3800], "disable_web_page_preview": True},
        timeout,
    )


def send_smtp(host: str, port: int, user: str, password: str, sender: str,
              recipients: list[str], subject: str, text: str, timeout: int) -> None:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text)
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls(context=context)
                smtp.ehlo()
            except smtplib.SMTPException:
                pass
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)


def egress_targets(ops_env: dict[str, str]) -> list[str]:
    targets = []
    if cfg(ops_env, "webhook_url", ""):
        targets.append("webhook")
    if cfg(ops_env, "telegram_bot_token", "") and cfg(ops_env, "telegram_chat_id", ""):
        targets.append("telegram")
    if cfg(ops_env, "smtp_host", "") and cfg(ops_env, "smtp_to", ""):
        targets.append("smtp")
    return targets


def deliver(ops_env: dict[str, str], subject: str, text: str, payload: dict,
            dry_run: bool) -> list[str]:
    targets = egress_targets(ops_env)
    timeout = int(cfg(ops_env, "timeout", DEFAULTS["timeout"]))
    sent: list[str] = []

    if dry_run:
        print("--- would send to: %s" % (", ".join(targets) or "stdout only"))
        print(text)
        return targets

    if not targets:
        print(text)
        return ["log"]

    if "webhook" in targets:
        http_post_json(str(cfg(ops_env, "webhook_url")), payload, timeout)
        sent.append("webhook")
    if "telegram" in targets:
        send_telegram(str(cfg(ops_env, "telegram_bot_token")),
                      str(cfg(ops_env, "telegram_chat_id")), text, timeout)
        sent.append("telegram")
    if "smtp" in targets:
        to_list = [a.strip() for a in str(cfg(ops_env, "smtp_to")).split(",") if a.strip()]
        send_smtp(
            str(cfg(ops_env, "smtp_host")),
            int(cfg(ops_env, "smtp_port", 587)),
            str(cfg(ops_env, "smtp_user", "")),
            str(cfg(ops_env, "smtp_password", "")),
            str(cfg(ops_env, "smtp_from", "") or cfg(ops_env, "smtp_user", "")),
            to_list, subject, text, timeout,
        )
        sent.append("smtp")

    # 出口发出去之后，本地日志也留一份 —— 出事时「什么时候报过」要能查
    print(text)
    return sent


# --------------------------------------------------------------------------
# 状态
# --------------------------------------------------------------------------
def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, state: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
def run(args) -> int:
    ops_env = load_ops_env()
    now = time.time()

    base_url = str(cfg(ops_env, "base_url"))
    state_path = str(cfg(ops_env, "state_path"))
    window_minutes = int(cfg(ops_env, "window_minutes"))
    cooldown_minutes = int(cfg(ops_env, "cooldown_minutes"))
    repeat_seconds = float(cfg(ops_env, "repeat_minutes")) * 60.0
    timeout = int(cfg(ops_env, "timeout"))

    api_key = ""
    if not args.test:
        api_key, key_source = resolve_api_key(ops_env)
        if not api_key:
            sys.stderr.write(
                "no API key: set KARMA_ALERT_API_KEY in /opt/karma/.env.ops, or make sure "
                "/opt/karma/.env has an AUTH_API_KEYS entry named 'ops-admin'\n")
            return 2

    state = load_state(state_path)
    prev_seen = state.get("seen") or {}

    if args.test:
        text = (
            "Karma 告警出口自检\n\n"
            "这是一条测试告警，由 security_alert_poller.py --test 发出。\n"
            "收到它说明「告警能真的到达人」这件事成立。\n\n"
            "host=%s at=%s" % (
                os.uname().nodename if hasattr(os, "uname") else "?",
                _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            )
        )
        payload = {"source": "karma", "kind": "alert_egress_selftest", "text": text}
        sent = deliver(ops_env, "[Karma] 告警出口自检", text, payload, args.dry_run)
        if args.json:
            print(json.dumps({"kind": "selftest", "egress": sent}, ensure_ascii=False))
        return 0

    # 拉取
    fetch_error = None
    try:
        report = fetch_report(base_url, api_key, window_minutes, cooldown_minutes, timeout)
    except urllib.error.HTTPError as exc:
        fetch_error = "HTTP %s from %s" % (exc.code, base_url)
        report = {}
    except Exception as exc:  # noqa: BLE001 - 网络层任何异常都算「拉不到」
        fetch_error = "%s: %s" % (type(exc).__name__, exc)
        report = {}

    current = normalize_alerts(report)
    current.update({c["key"]: {k: v for k, v in c.items() if k != "key"}
                    for c in local_checks(
                        str(cfg(ops_env, "backup_root")),
                        float(cfg(ops_env, "backup_max_age_hours")),
                        str(cfg(ops_env, "disk_path")),
                        float(cfg(ops_env, "disk_max_percent")),
                    )})

    if fetch_error:
        current["karma_local|api_unreachable"] = {
            "severity": "critical",
            "alert_type": "api_unreachable",
            "message": "cannot pull /v1/security/ops/alerts: %s" % fetch_error,
        }

    born, resolved = compute_diff(prev_seen, current, now, repeat_seconds)
    for item in born:
        item["notify_at"] = now
    new_seen = merge_seen(prev_seen, current, born, now)

    state_out = {
        "last_run_ts": now,
        "last_ok_ts": None if fetch_error else now,
        "last_error": fetch_error,
        "base_url": base_url,
        "egress": egress_targets(ops_env) or ["log"],
        "active": sorted(current),
        "seen": new_seen,
    }

    exit_code = 0
    if born or resolved:
        subject = "[Karma] %d security alert(s)" % len(born) if born else "[Karma] alerts cleared"
        text = render_text(subject, born, resolved, report)
        payload = {
            "source": "karma",
            "kind": "security_alerts",
            "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "new": born,
            "resolved": resolved,
            "escalation": (report.get("escalation") or {}).get("level", "none"),
            "summary": report.get("summary") or {},
            "text": text,
        }
        sent = deliver(ops_env, subject, text, payload, args.dry_run)
        state_out["last_emit_ts"] = now
        state_out["last_emit_egress"] = sent
        if born:
            exit_code = 4
    elif fetch_error:
        exit_code = 3

    if not args.dry_run:
        save_state(state_path, state_out)

    if args.json:
        print(json.dumps({
            "ok": fetch_error is None,
            "new": len(born),
            "resolved": len(resolved),
            "active": len(current),
            "egress": state_out["egress"],
            "error": fetch_error,
        }, ensure_ascii=False))

    if fetch_error:
        sys.stderr.write("fetch failed: %s\n" % fetch_error)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Karma security alert egress poller")
    ap.add_argument("--test", action="store_true", help="send a self-test alert and exit")
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    ap.add_argument("--json", action="store_true", help="print one JSON result line")
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())