"""出境邮件中继 —— 出口选择与 fail-closed 的证明。

中继是「大陆机器连不上出境 SMTP」时的第二条出口。它自己也必须 fail-closed：

* url / token 缺一不可 —— 只配一个一律按「没配」处理，回落直连 SMTP；
* 后端只认 2xx，其余（含网络异常）一律 ``MailerUnavailable``；
* 中继配了就走中继，不再碰直连 SMTP。

全部用 ``httpx.MockTransport`` 断言「实际发出去的那一次 HTTP」，不碰真网。
"""
from __future__ import annotations

import json

import httpx
import pytest

from config.settings import settings
from services import mailer


def _set(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value, raising=False)


@pytest.fixture(autouse=True)
def _bare(monkeypatch):
    """每条用例都从「什么都还没配」开始。"""
    _set(
        monkeypatch,
        karma_mail_relay_url="",
        karma_mail_relay_token="",
        karma_mail_host="",
        karma_mail_port=0,
        karma_mail_from="",
        karma_mail_user="",
        karma_mail_password="",
        karma_mail_ssl=True,
        karma_mail_starttls=False,
    )


def _install_transport(monkeypatch, handler) -> None:
    """把 ``httpx.post`` 接到一个 MockTransport 上 —— 真正被调用的就是它。"""
    transport = httpx.MockTransport(handler)

    def fake_post(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", fake_post)


def test_relay_needs_both_url_and_token(monkeypatch):
    _set(monkeypatch, karma_mail_relay_url="https://relay.example/send")
    assert mailer.relay_configured() is False
    assert mailer.configured() is False

    _set(monkeypatch, karma_mail_relay_url="", karma_mail_relay_token="t0ken")
    assert mailer.relay_configured() is False
    assert mailer.configured() is False

    _set(monkeypatch, karma_mail_relay_url="https://relay.example/send")
    assert mailer.relay_configured() is True
    assert mailer.configured() is True


def test_relay_post_carries_bearer_and_payload(monkeypatch):
    _set(monkeypatch, karma_mail_relay_url="https://relay.example/send", karma_mail_relay_token="s3cret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True})

    _install_transport(monkeypatch, handler)
    mailer.send_mail(to="owner@example.com", subject="S", text="T", html="<b>H</b>")

    assert seen["url"] == "https://relay.example/send"
    assert seen["auth"] == "Bearer s3cret"
    assert seen["json"] == {
        "to": "owner@example.com",
        "subject": "S",
        "text": "T",
        "html": "<b>H</b>",
    }


def test_relay_5xx_is_fail_closed(monkeypatch):
    _set(monkeypatch, karma_mail_relay_url="https://relay.example/send", karma_mail_relay_token="s3cret")
    _install_transport(monkeypatch, lambda request: httpx.Response(500, json={"ok": False}))
    with pytest.raises(mailer.MailerUnavailable):
        mailer.send_mail(to="owner@example.com", subject="S", text="T")


def test_relay_network_error_is_fail_closed(monkeypatch):
    _set(monkeypatch, karma_mail_relay_url="https://relay.example/send", karma_mail_relay_token="s3cret")

    def boom(url, **kwargs):
        raise httpx.ConnectError("relay is down")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(mailer.MailerUnavailable):
        mailer.send_mail(to="owner@example.com", subject="S", text="T")


def test_relay_beats_direct_smtp(monkeypatch):
    """中继配了就只走中继 —— 直连 SMTP 一次都不碰。"""
    _set(
        monkeypatch,
        karma_mail_relay_url="https://relay.example/send",
        karma_mail_relay_token="s3cret",
        karma_mail_host="smtp.internal",
        karma_mail_port=465,
        karma_mail_from="karma@example.com",
    )

    def _must_not_run(*args, **kwargs):
        raise AssertionError("direct SMTP must not be used while the relay is configured")

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _must_not_run)
    monkeypatch.setattr(mailer.smtplib, "SMTP", _must_not_run)
    _install_transport(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
    mailer.send_mail(to="owner@example.com", subject="S", text="T")


def test_nothing_configured_is_unavailable():
    assert mailer.relay_configured() is False
    assert mailer.configured() is False
    with pytest.raises(mailer.MailerUnavailable):
        mailer.send_mail(to="owner@example.com", subject="S", text="T")
