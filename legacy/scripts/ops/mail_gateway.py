#!/usr/bin/env python3
"""Karma 出境邮件中继网关 —— 一台境外小机器上的唯一职责：把邮件投出去。

为什么需要它
------------
大陆机器到 Gmail / Outlook 这类出境 SMTP 时通时断（GFW 抖动），出站 25 端口
还被封；而本服务在「邮箱回执」这条链上是 fail-closed 的 —— 连不上出境 SMTP 就
503，主人反而开不了那把锁。把「必须连外网 SMTP」这件事从大陆机器上摘出去，交给
这台境外网关：本服务只用 HTTPS(443) 把邮件 POST 过来，443 对大陆机器永远通。

安全边界（这台机器就架在边界上，按边界来写）
------------------------------------------
* 只认一把钥匙：``Authorization: Bearer <KARMA_GATEWAY_TOKEN>``，用
  ``hmac.compare_digest`` 常数时间比较。没配 token 直接拒绝启动。
* 不是开放中继：除「持钥匙的后端」外没有任何转发路径；收件人由调用方指定，
  本机不做任意转发。
* 拒转「像凭据」的邮件：正文任何位置（大小写不敏感）出现 ``karma_``
  （API Key / Runtime Key 的前缀）一律拒绝 —— 中继端也守一道，凭据不出境。
* 不落盘、不排队：同步投递，成功 200、失败 502；没有本地邮件队列，也就没有被翻的落盘面。
* 不反射输入：响应体只有极简 JSON，绝不回显收件人 / 正文。

用法
----
    python3 mail_gateway.py --check     # 自检：读配置、打裁决，不监听
    python3 mail_gateway.py             # 启动（配置从 $GATEWAY_ENV 读）

配置（KEY=VALUE；同名进程环境变量优先）
------------------------------------
    KARMA_GATEWAY_TOKEN          必填。与后端 KARMA_MAIL_RELAY_TOKEN 逐字节相同。
    KARMA_GATEWAY_BIND           默认 127.0.0.1
    KARMA_GATEWAY_PORT           默认 8080
    KARMA_GATEWAY_CERT / _KEY    可选；都给了就本进程自己终结 TLS，否则等反代
    KARMA_GATEWAY_SMTP_HOST      默认 127.0.0.1
    KARMA_GATEWAY_SMTP_PORT      默认 25
    KARMA_GATEWAY_SMTP_USER      可空；有就登录
    KARMA_GATEWAY_SMTP_PASSWORD
    KARMA_GATEWAY_SMTP_FROM      必填。发件人地址
    KARMA_GATEWAY_SMTP_SSL       默认 0（465 直连用 1）
    KARMA_GATEWAY_SMTP_STARTTLS  默认 1（587 用 1；本机 25 可设 0）
    KARMA_GATEWAY_TIMEOUT        默认 20 秒
"""
from __future__ import annotations

import hmac
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_ENV_PATH = "/opt/karma-mail-gateway/gateway.env"
MAX_BODY_BYTES = 256 * 1024
MAX_TO_LEN = 254
MAX_SUBJECT_LEN = 200
MAX_TEXT_LEN = 20000
MAX_HTML_LEN = 50000


def load_config() -> dict[str, str]:
    """读 $GATEWAY_ENV（默认 /opt/karma-mail-gateway/gateway.env）的 KEY=VALUE。

    不依赖 python-dotenv：格式就这么简单，自己解析更可控。同名进程环境变量优先 ——
    这样 systemd 或单测里 setenv 就能覆盖文件，不必去动盘上的密件。
    """
    path = os.environ.get("GATEWAY_ENV") or DEFAULT_ENV_PATH
    cfg: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    for key in list(cfg):
        if key in os.environ:
            cfg[key] = os.environ[key]
    for key, value in os.environ.items():
        if key.startswith("KARMA_GATEWAY_"):
            cfg[key] = value
    return cfg


def _as_bool(value: str, default: bool) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _validate(payload: dict) -> tuple[dict | None, str | None]:
    """把请求体收敛成一封干净、有界、且不含凭据的邮件。

    任何一项不达标就整封拒绝 —— 网关不做「尽力而为」。
    """
    to = str(payload.get("to") or "").strip()
    subject = payload.get("subject")
    text = payload.get("text")
    html = payload.get("html")
    if not to or "@" not in to or len(to) > MAX_TO_LEN or any(c in to for c in "\r\n"):
        return None, "to"
    if not isinstance(subject, str) or len(subject) > MAX_SUBJECT_LEN or any(c in subject for c in "\r\n"):
        return None, "subject"
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT_LEN:
        return None, "text"
    if html is not None and (not isinstance(html, str) or len(html) > MAX_HTML_LEN):
        return None, "html"
    if "karma_" in (text + (html or "")).lower():
        return None, "credential_shaped"
    return {"to": to, "subject": subject, "text": text, "html": html}, None


def deliver(cfg: dict[str, str], *, to: str, subject: str, text: str, html: str | None) -> None:
    """经本机 SMTP 投递。失败就抛，由调用方转成 502。"""
    host = cfg.get("KARMA_GATEWAY_SMTP_HOST", "127.0.0.1") or "127.0.0.1"
    port = int(cfg.get("KARMA_GATEWAY_SMTP_PORT", "25") or "25")
    user = cfg.get("KARMA_GATEWAY_SMTP_USER", "")
    password = cfg.get("KARMA_GATEWAY_SMTP_PASSWORD", "")
    sender = cfg.get("KARMA_GATEWAY_SMTP_FROM", "")
    timeout = int(cfg.get("KARMA_GATEWAY_TIMEOUT", "20") or "20")
    use_ssl = _as_bool(cfg.get("KARMA_GATEWAY_SMTP_SSL", ""), False)
    use_starttls = _as_bool(cfg.get("KARMA_GATEWAY_SMTP_STARTTLS", ""), True)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        smtp.ehlo()
        if use_starttls:
            smtp.starttls(context=context)
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)


class GatewayHandler(BaseHTTPRequestHandler):
    """极薄的一层：鉴权 -> 校验 -> 投递。没有别的路径。"""

    server_version = "KarmaMailGateway/1.0"
    protocol_version = "HTTP/1.1"
    cfg: dict[str, str] = {}

    def log_message(self, fmt, *args):
        sys.stderr.write("mail-gateway %s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/healthz":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"ok": False})

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/send":
            self._json(404, {"ok": False})
            return
        expected = self.cfg.get("KARMA_GATEWAY_TOKEN", "")
        auth = self.headers.get("Authorization", "")
        presented = auth[7:] if auth.startswith("Bearer ") else ""
        if not expected or not hmac.compare_digest(presented, expected):
            # 不用 401：那等于告诉扫描器「这里有个口」。直接 404，像是什么都没有。
            self._json(404, {"ok": False})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            self._json(413, {"ok": False})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"ok": False})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False})
            return
        clean, problem = _validate(payload)
        if problem is not None:
            self._json(400, {"ok": False, "error": problem})
            return
        try:
            deliver(self.cfg, **(clean or {}))
        except Exception as exc:
            self.log_message("delivery failed: %s", type(exc).__name__)
            self._json(502, {"ok": False})
            return
        self._json(200, {"ok": True})


def _check(cfg: dict[str, str]) -> int:
    host = cfg.get("KARMA_GATEWAY_BIND", "127.0.0.1") or "127.0.0.1"
    port = int(cfg.get("KARMA_GATEWAY_PORT", "8080") or "8080")
    problems = []
    if not cfg.get("KARMA_GATEWAY_TOKEN"):
        problems.append("KARMA_GATEWAY_TOKEN is not set")
    if not cfg.get("KARMA_GATEWAY_SMTP_FROM"):
        problems.append("KARMA_GATEWAY_SMTP_FROM is not set")
    print(json.dumps({
        "token_set": bool(cfg.get("KARMA_GATEWAY_TOKEN")),
        "from_set": bool(cfg.get("KARMA_GATEWAY_SMTP_FROM")),
        "smtp": "%s:%s" % (
            cfg.get("KARMA_GATEWAY_SMTP_HOST", "127.0.0.1"),
            cfg.get("KARMA_GATEWAY_SMTP_PORT", "25"),
        ),
        "tls_terminates_here": bool(cfg.get("KARMA_GATEWAY_CERT") and cfg.get("KARMA_GATEWAY_KEY")),
        "bind": "%s:%d" % (host, port),
        "problems": problems,
    }, ensure_ascii=False))
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    cfg = load_config()
    if "--check" in argv:
        return _check(cfg)
    if not cfg.get("KARMA_GATEWAY_TOKEN"):
        print("refusing to start: KARMA_GATEWAY_TOKEN is not set", file=sys.stderr)
        return 2
    if not cfg.get("KARMA_GATEWAY_SMTP_FROM"):
        print("refusing to start: KARMA_GATEWAY_SMTP_FROM is not set", file=sys.stderr)
        return 2
    host = cfg.get("KARMA_GATEWAY_BIND", "127.0.0.1") or "127.0.0.1"
    port = int(cfg.get("KARMA_GATEWAY_PORT", "8080") or "8080")
    GatewayHandler.cfg = cfg
    httpd = ThreadingHTTPServer((host, port), GatewayHandler)
    cert = cfg.get("KARMA_GATEWAY_CERT", "")
    key = cfg.get("KARMA_GATEWAY_KEY", "")
    if cert and key:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert, key)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    sys.stderr.write("mail-gateway listening on %s:%d\n" % (host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
