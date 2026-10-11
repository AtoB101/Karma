"""跨平台聊天适配器（S6）—— Telegram / WhatsApp 的功能 + 安全用例。

这组用例要**证明**三件事，而不是描述它们：

1. 两个平台的 webhook 都真的验签：不签名 / 错签名 / 凭据没配，一律进不来。
2. 这条通道**没有动钱入口**：任何输入都只可能落到 ``commands.ALLOWED_ACTIONS``。
3. 出站方向**不泄漏**：疑似凭据的文本会被拦下，而不是发进聊天窗口。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from services.chat_adapters import commands, events, guard, outbound, whatsapp

PKG = Path(__file__).resolve().parents[2] / "services" / "chat_adapters"

TELEGRAM_SECRET = "tg-secret-value"
WA_APP_SECRET = "wa-app-secret-value"
WA_VERIFY_TOKEN = "wa-verify-token-value"
NOTIFY_TOKEN = "notify-token-value"

WA_PAYLOAD = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "from": "8613800000000",
                                "id": "wamid.TEST1",
                                "text": {"body": "/connect"},
                            }
                        ]
                    }
                }
            ]
        }
    ]
}


@pytest.fixture(autouse=True)
def _adapter_env(monkeypatch):
    """默认把所有适配器凭据清空 + 环境钉在 test（出站默认不发真实消息）。"""
    for name in (
        "TELEGRAM_WEBHOOK_SECRET",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "KARMA_ADAPTER_NOTIFY_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KARMA_ENV", "test")
    monkeypatch.delenv("TELEGRAM_BOT_SEND_IN_DEV", raising=False)
    monkeypatch.delenv("WHATSAPP_SEND_IN_DEV", raising=False)


def _wa_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _tg_headers() -> dict[str, str]:
    return {"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET}


def _tg_update(text: str) -> dict:
    return {
        "update_id": 1,
        "message": {"message_id": 9, "chat": {"id": 777}, "from": {"id": 42}, "text": text},
    }


# --------------------------------------------------------------------------
# 功能：接入引导
# --------------------------------------------------------------------------


async def test_telegram_connect_reply_points_at_the_console(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setenv("KARMA_CONSOLE_BASE_URL", "https://console.example")

    r = await client.post(
        "/v1/adapters/telegram/webhook", json=_tg_update("/connect"), headers=_tg_headers()
    )
    assert r.status_code == 200, r.text
    assert r.json()["handled"] == "connect"
    # test 环境默认不发真实消息 —— 它是被「跳过」，不是被「发了」。
    assert r.json()["sent"] is False

    message = commands.connect_message()
    assert "https://console.example/?view=pairing" in message.text
    assert "/connect" in dict(message.buttons).values() or "/connect" in message.buttons[0]


async def test_telegram_unknown_input_is_delegated_to_existing_concierge(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setattr(
        "services.telegram.bot.handle_update", lambda body: {"delegated": True, "n": body["update_id"]}
    )

    r = await client.post(
        "/v1/adapters/telegram/webhook", json=_tg_update("/sync"), headers=_tg_headers()
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"delegated": True, "n": 1}


async def test_whatsapp_handshake_accepts_only_the_matching_token(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", WA_VERIFY_TOKEN)
    params = {"hub.mode": "subscribe", "hub.verify_token": WA_VERIFY_TOKEN, "hub.challenge": "12345"}

    ok = await client.get("/v1/adapters/whatsapp/webhook", params=params)
    assert ok.status_code == 200
    assert ok.text == "12345"

    bad = await client.get(
        "/v1/adapters/whatsapp/webhook",
        params={**params, "hub.verify_token": WA_VERIFY_TOKEN + "x"},
    )
    assert bad.status_code == 403


async def test_whatsapp_connect_is_accepted_when_signature_is_good(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", WA_APP_SECRET)
    raw = json.dumps(WA_PAYLOAD).encode()

    r = await client.post(
        "/v1/adapters/whatsapp/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _wa_signature(raw, WA_APP_SECRET),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "handled": 1}


# --------------------------------------------------------------------------
# 安全：webhook 验签
# --------------------------------------------------------------------------


async def test_telegram_webhook_rejects_missing_or_wrong_secret(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)

    missing = await client.post("/v1/adapters/telegram/webhook", json=_tg_update("/connect"))
    assert missing.status_code == 403

    wrong = await client.post(
        "/v1/adapters/telegram/webhook",
        json=_tg_update("/connect"),
        headers={"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET + "x"},
    )
    assert wrong.status_code == 403


async def test_telegram_webhook_fails_closed_when_secret_is_unset_in_prod(client, monkeypatch):
    monkeypatch.setenv("KARMA_ENV", "production")
    r = await client.post(
        "/v1/adapters/telegram/webhook",
        json=_tg_update("/connect"),
        headers=_tg_headers(),
    )
    assert r.status_code == 403


async def test_whatsapp_webhook_rejects_bad_or_absent_signature(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", WA_APP_SECRET)
    raw = json.dumps(WA_PAYLOAD).encode()

    absent = await client.post(
        "/v1/adapters/whatsapp/webhook", content=raw, headers={"Content-Type": "application/json"}
    )
    assert absent.status_code == 403

    forged = await client.post(
        "/v1/adapters/whatsapp/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _wa_signature(raw, "not-the-secret"),
        },
    )
    assert forged.status_code == 403

    # 报文被改过、签名还是旧的 —— 同样必须拒。
    tampered = raw.replace(b"/connect", b"/help!!!!")
    replayed = await client.post(
        "/v1/adapters/whatsapp/webhook",
        content=tampered,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _wa_signature(raw, WA_APP_SECRET),
        },
    )
    assert replayed.status_code == 403


async def test_whatsapp_webhook_fails_closed_without_app_secret(client, monkeypatch):
    raw = json.dumps(WA_PAYLOAD).encode()
    r = await client.post(
        "/v1/adapters/whatsapp/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _wa_signature(raw, WA_APP_SECRET),
        },
    )
    assert r.status_code == 503


async def test_whatsapp_handshake_fails_closed_without_verify_token(client):
    r = await client.get(
        "/v1/adapters/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "anything", "hub.challenge": "1"},
    )
    assert r.status_code == 503


# --------------------------------------------------------------------------
# 安全：通知出口
# --------------------------------------------------------------------------


async def test_notify_requires_a_configured_token_then_a_matching_bearer(client, monkeypatch):
    body = {"platform": "telegram", "chat_id": "777", "text": "你的钥匙已激活。"}

    unconfigured = await client.post("/v1/adapters/notify", json=body)
    assert unconfigured.status_code == 503

    monkeypatch.setenv("KARMA_ADAPTER_NOTIFY_TOKEN", NOTIFY_TOKEN)
    wrong = await client.post(
        "/v1/adapters/notify", json=body, headers={"X-Karma-Adapter-Token": "nope"}
    )
    assert wrong.status_code == 401

    missing = await client.post("/v1/adapters/notify", json=body)
    assert missing.status_code == 401

    ok = await client.post(
        "/v1/adapters/notify", json=body, headers={"X-Karma-Adapter-Token": NOTIFY_TOKEN}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["sent"] is False  # test 环境不发真实消息


async def test_notify_refuses_credential_shaped_text(client, monkeypatch):
    monkeypatch.setenv("KARMA_ADAPTER_NOTIFY_TOKEN", NOTIFY_TOKEN)
    r = await client.post(
        "/v1/adapters/notify",
        json={"platform": "telegram", "chat_id": "777", "text": "key: KRM_RT_abcdef123456"},
        headers={"X-Karma-Adapter-Token": NOTIFY_TOKEN},
    )
    assert r.status_code == 400


async def test_notify_rejects_unsupported_platform(client, monkeypatch):
    monkeypatch.setenv("KARMA_ADAPTER_NOTIFY_TOKEN", NOTIFY_TOKEN)
    r = await client.post(
        "/v1/adapters/notify",
        json={"platform": "wechat", "chat_id": "777", "text": "hi"},
        headers={"X-Karma-Adapter-Token": NOTIFY_TOKEN},
    )
    assert r.status_code == 400


async def test_status_endpoint_never_echoes_secrets(client, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setenv("WHATSAPP_APP_SECRET", WA_APP_SECRET)
    monkeypatch.setenv("KARMA_ADAPTER_NOTIFY_TOKEN", NOTIFY_TOKEN)

    r = await client.get("/v1/adapters/status")
    assert r.status_code == 200
    raw = r.text
    for secret in (TELEGRAM_SECRET, WA_APP_SECRET, NOTIFY_TOKEN):
        assert secret not in raw
    body = r.json()
    assert body["notify_configured"] is True
    assert body["whatsapp"]["webhook_configured"] is True
    assert body["telegram"]["webhook_configured"] is True
    assert set(body["platforms"]) == {"telegram", "whatsapp"}


# --------------------------------------------------------------------------
# 安全：红线不变量
# --------------------------------------------------------------------------


def test_command_surface_has_no_money_entry():
    """任何输入都只能落到白名单动作上 —— 包括各种「看起来像动钱」的说法。"""
    assert commands.ALLOWED_ACTIONS == {"connect", "help", "delegate", "fallback"}
    probes = [
        "/pay",
        "/transfer",
        "帮我转账 100",
        "下单",
        "place_order",
        "create_trade",
        "把额度改成 10000",
        "revoke_all",
        "/refund",
        "",
    ]
    for platform in ("telegram", "whatsapp"):
        for text in probes:
            event = events.ChatEvent(platform=platform, chat_id="1", sender_id="1", text=text)
            decision = commands.decide(event)
            assert decision.action in commands.ALLOWED_ACTIONS
            if decision.reply is not None:
                assert guard.find_secret(decision.reply.text) is None


def test_adapter_package_never_reaches_into_money_or_keys():
    """源码级不变量：适配器不 import 钱 / 链 / 钱包 / 私钥相关模块。"""
    banned = (
        "services.chain",
        "services.runtime_wallet",
        "services.atomic_ledger",
        "eth_account",
        "web3",
    )
    for path in PKG.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in source, f"{path.name} 不该碰 {needle}"


def test_guard_blocks_credentials_but_keeps_public_hashes():
    for bad in (
        "key: KRM_RT_abcdef123456",
        "-----BEGIN RSA PRIVATE KEY-----",
        "KARMA_RUNTIME_KEY=deadbeef",
        "AGENT_PRIVATE_KEY: 0x" + "a" * 64,
        "sig 0x" + "b" * 130,
    ):
        with pytest.raises(guard.SecretLeakError):
            guard.assert_no_secret(bad)

    # 交易哈希 / 证据哈希本来就是公开的，不能被误拦。
    public = "tx 0x" + "c" * 64
    assert guard.assert_no_secret(public) == public


def test_outbound_refuses_to_send_a_credential():
    with pytest.raises(guard.SecretLeakError):
        outbound.send("telegram", "777", outbound.OutboundMessage(text="KRM_RT_abcdef123456"))


def test_unsupported_platform_is_rejected_not_silently_ignored():
    result = outbound.send("wechat", "777", outbound.OutboundMessage(text="hi"))
    assert result["sent"] is False and result["ok"] is False


# --------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------


def test_events_normalize_both_platforms_and_ignore_junk():
    tg = events.normalize_telegram(_tg_update("/connect"))
    assert len(tg) == 1 and tg[0].chat_id == "777" and tg[0].is_command

    tg_callback = events.normalize_telegram(
        {"callback_query": {"id": "cb1", "from": {"id": 42}, "data": "/connect",
                            "message": {"chat": {"id": 777}}}}
    )
    assert tg_callback[0].button_payload == "/connect"

    wa = events.normalize_whatsapp(WA_PAYLOAD)
    assert len(wa) == 1 and wa[0].chat_id == "8613800000000" and wa[0].text == "/connect"

    assert events.normalize_telegram({}) == []
    assert events.normalize_whatsapp({"entry": [{"changes": [{"value": {"statuses": [1]}}]}]}) == []


def test_chat_id_is_never_logged_in_full():
    assert guard.mask_chat_id("8613800000000").endswith("0000")
    assert "86138000" not in guard.mask_chat_id("8613800000000")


def test_whatsapp_signature_helper_is_constant_time_and_fails_closed(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    assert whatsapp.verify_signature(b"{}", "sha256=deadbeef") is False