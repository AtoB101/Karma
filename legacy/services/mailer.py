"""出站邮件 —— 唯一出口。

安全第一
--------

* **没配就是没配**：``KARMA_MAIL_*`` 没配齐、又没配出境中继时 ``configured()`` 为
  False，``send_mail`` 抛 ``MailerUnavailable``，调用方 fail-closed 拒绝 —— 绝不
  「当没发过」继续走。默认是「不发送」。
* **两种出口，二选一**：
  1. 直连 SMTP（``KARMA_MAIL_HOST/PORT/USER/PASSWORD/FROM/SSL/STARTTLS``）；
  2. 出境中继（``KARMA_MAIL_RELAY_URL/TOKEN``）—— 见 ``scripts/ops/mail_gateway.py``。
     本机只用 HTTPS(443) 把邮件交给境外中继，自己不碰外网 SMTP。中继优先。
* 只发文本 + 一份等价的 HTML；正文只含「人可读」的说明与确认链接，**不含**任何
  凭据（API Key / Runtime Key / 私钥）。
* 超时上限控制：465(SSL) 与 587/STARTTLS 两种常见形态都支持；中继走 HTTPS 超时。
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from config.settings import settings


class MailerUnavailable(RuntimeError):
    """没有可用的出站邮件出口 —— 调用方必须 fail-closed，不许「装作发过了」。"""


def relay_configured() -> bool:
    """出境中继是否配齐。url 与 token 缺一不可（只配一个 = 没配）。"""
    url = str(getattr(settings, "karma_mail_relay_url", "") or "").strip()
    token = str(getattr(settings, "karma_mail_relay_token", "") or "").strip()
    return bool(url and token)


def configured() -> bool:
    if relay_configured():
        return True
    host = str(getattr(settings, "karma_mail_host", "") or "").strip()
    sender = str(getattr(settings, "karma_mail_from", "") or "").strip()
    port = int(getattr(settings, "karma_mail_port", 0) or 0)
    return bool(host and sender and port > 0)


def sender_address() -> str:
    explicit = str(getattr(settings, "karma_mail_from", "") or "").strip()
    return explicit or str(getattr(settings, "karma_mail_user", "") or "").strip()


def send_mail(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    timeout: int | None = None,
) -> None:
    """发一封邮件。没配出口就抛 ``MailerUnavailable``（调用方 fail-closed）。"""
    if not configured():
        raise MailerUnavailable(
            "outbound mail is not configured "
            "(KARMA_MAIL_HOST / KARMA_MAIL_FROM / KARMA_MAIL_RELAY_URL)"
        )
    recipient = str(to or "").strip()
    if not recipient or "@" not in recipient:
        raise MailerUnavailable("recipient address is not usable")

    wait = int(timeout or getattr(settings, "karma_mail_timeout_seconds", 15) or 15)
    if relay_configured():
        _send_via_relay(recipient=recipient, subject=subject, text=text, html=html, wait=wait)
        return
    _send_via_smtp(recipient=recipient, subject=subject, text=text, html=html, wait=wait)


def _build_message(*, recipient: str, subject: str, text: str, html: str | None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender_address()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _send_via_relay(*, recipient: str, subject: str, text: str, html: str | None, wait: int) -> None:
    """把邮件交给境外中继。只认 2xx；其余一律 fail-closed。

    不把上游响应体放进异常 —— 它可能回显收件人；错误信息只要状态码与类名就够定位。
    """
    import httpx

    url = str(settings.karma_mail_relay_url).strip()
    token = str(settings.karma_mail_relay_token).strip()
    payload = {"to": recipient, "subject": subject, "text": text, "html": html}
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": "Bearer " + token},
            timeout=wait,
        )
    except Exception as exc:  # noqa: BLE001 - 网络/协议错误全部收敛成一个 fail-closed 信号
        raise MailerUnavailable("mail relay unreachable (%s)" % type(exc).__name__) from exc
    if response.status_code // 100 != 2:
        raise MailerUnavailable("mail relay refused (%s)" % response.status_code)


def _send_via_smtp(*, recipient: str, subject: str, text: str, html: str | None, wait: int) -> None:
    host = str(settings.karma_mail_host).strip()
    port = int(settings.karma_mail_port)
    user = str(getattr(settings, "karma_mail_user", "") or "").strip()
    password = str(getattr(settings, "karma_mail_password", "") or "")
    use_ssl = bool(getattr(settings, "karma_mail_ssl", True))
    use_starttls = bool(getattr(settings, "karma_mail_starttls", False))
    message = _build_message(recipient=recipient, subject=subject, text=text, html=html)
    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=wait, context=context) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(host, port, timeout=wait) as smtp:
        smtp.ehlo()
        if use_starttls:
            smtp.starttls(context=context)
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)
