"""出站邮件 —— 配对「邮箱回执」的唯一出口。

安全第一：

* **没配就是没配**：``KARMA_MAIL_HOST`` / ``KARMA_MAIL_FROM`` 任一为空时
  ``configured()`` 为 False，``send_mail`` 抛 ``MailerUnavailable``。调用方必须把
  这当成「回执发不出去」并拒绝继续，**绝不允许**静默降级成「已发送」。
* 只发纯文本 + 一份等价的 HTML；正文里只出现短码与确认链接，**绝不**出现任何
  凭据（API Key / Runtime Key / 私钥）。
* 连接超时受控；465(SSL) 与 587/STARTTLS 两种常见形态都支持。
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from config.settings import settings


class MailerUnavailable(RuntimeError):
    """没有可用的出站邮件出口 —— 调用方必须 fail-closed，不许假装发出去了。"""


def configured() -> bool:
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
    """发一封邮件。没配置出口就抛 ``MailerUnavailable``（调用方 fail-closed）。"""
    if not configured():
        raise MailerUnavailable(
            "outbound mail is not configured (KARMA_MAIL_HOST / KARMA_MAIL_FROM)"
        )
    recipient = str(to or "").strip()
    if not recipient or "@" not in recipient:
        raise MailerUnavailable("recipient address is not usable")

    host = str(settings.karma_mail_host).strip()
    port = int(settings.karma_mail_port)
    user = str(getattr(settings, "karma_mail_user", "") or "").strip()
    password = str(getattr(settings, "karma_mail_password", "") or "")
    sender = sender_address()
    use_ssl = bool(getattr(settings, "karma_mail_ssl", True))
    use_starttls = bool(getattr(settings, "karma_mail_starttls", False))
    wait = int(timeout or getattr(settings, "karma_mail_timeout_seconds", 15) or 15)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

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
