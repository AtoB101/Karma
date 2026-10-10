"""邮箱回执（第三把锁）：agent 自动接入的最后一道「人味」确认。

锁的语义必须是可证明的，而不是写在文档里：

* **配对码泄漏也换不到东西** —— 偷到 pairing_code 的人能在 agent 侧读到
  match_code，但读不到主人邮箱里的那封邮件，也就拿不到链接上的 token；
* **明文 token 不落盘** —— 磁盘上只有 SHA-256，回执正文里只有短码与链接；
* **点错有代价** —— 连错到上限就把这次配对就地作废，与交接码同一口径；
* **出口没配就是没配** —— KARMA_MAIL_* 没配齐时 approve 直接 503，绝不静默
  降级成「已加锁」。

agent 侧脚手架（私钥签名申请、服务规格、owner 会话）与 ``test_agent_pairing.py``
共用同一套，避免两处各写一份、慢慢跑偏。
"""
from __future__ import annotations

import re

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from db.models.orm import Base
from db.session import get_db
from services import agent_pairing as pairing
from services import mailer
from services.agent_bootstrap_credentials import reset_bootstrap_keys
from services.agent_onboarding_template import load_onboarding_catalog
from services.agent_profile_store import clear_profile_cards

from tests.unit.test_agent_pairing import OWNER, _client, _food_specs, _open_request

EMAIL = "owner@example.com"


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pair_email.sqlite", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KARMA_AGENT_KEY_DIR", str(tmp_path / "agent_keys"))
    monkeypatch.setattr(pairing, "_STORE_PATH", tmp_path / "agent_pairing.json")
    reset_bootstrap_keys()
    pairing.reset_pairings()
    clear_profile_cards()
    load_onboarding_catalog.cache_clear()
    yield
    reset_bootstrap_keys()
    pairing.reset_pairings()
    clear_profile_cards()
    load_onboarding_catalog.cache_clear()


@pytest.fixture
def outbox(monkeypatch):
    """拦下出站邮件：把「实际会发出去的那封信」原样收进列表。"""
    sent: list[dict] = []
    monkeypatch.setattr(mailer, "configured", lambda: True)

    def _fake_send_mail(*, to, subject, text, html=None, timeout=None):
        sent.append({"to": to, "subject": subject, "text": text, "html": html})

    monkeypatch.setattr(mailer, "send_mail", _fake_send_mail)
    return sent


def _approve_body(user_code: str, notify_email: str | None = None) -> dict:
    body = {
        "user_code": user_code,
        "side": "seller",
        "vertical": "food",
        "display_name": "Owner Food Agent",
        "answers": {"industry_ids": ["food_delivery"], "service_specs": _food_specs()},
    }
    if notify_email is not None:
        body["notify_email"] = notify_email
    return body


async def _approve(client, user_code: str, notify_email: str | None = None):
    return await client.post(
        "/v1/agent-pairing/approve",
        json=_approve_body(user_code, notify_email),
        headers={"X-Karma-Identity-Id": OWNER},
    )


async def _lookup(client, user_code: str) -> dict:
    r = await client.get(
        "/v1/agent-pairing/lookup",
        params={"user_code": user_code},
        headers={"X-Karma-Identity-Id": OWNER},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _claim(client, pairing_code: str) -> dict:
    r = await client.post("/v1/agent-pairing/claim", json={"pairing_code": pairing_code})
    assert r.status_code == 200, r.text
    return r.json()


async def _click(client, user_code: str, token: str):
    return await client.get(
        "/v1/agent-pairing/email-confirm", params={"user_code": user_code, "token": token}
    )


def _token_for(mail_text: str, code: str) -> str:
    """从邮件正文里取出「这个码」那条链接上的 token。"""
    m = re.search(rf"码 {re.escape(code)}：(https?\S+)", mail_text)
    assert m, mail_text
    t = re.search(r"token=([A-Za-z0-9_\-]+)", m.group(1))
    assert t, m.group(1)
    return t.group(1)


def _other_codes(mail_text: str, match_code: str) -> list[str]:
    codes = re.findall(r"码 (\d{6})：", mail_text)
    assert len(codes) == 3, mail_text
    assert match_code in codes
    return [c for c in codes if c != match_code]


@pytest.mark.asyncio
async def test_without_a_notify_email_the_lock_stays_off(db_session):
    """不发确认邮件时行为与从前完全一致 —— 这版是可选的第三把锁。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await _approve(client, opened["user_code"])
            assert approved.status_code == 200, approved.text
            assert approved.json()["email_confirm"] == {"required": False, "state": "off"}
            claimed = await _claim(client, opened["pairing_code"])
            assert claimed["status"] == "approved"
            assert claimed["credentials"]["api_key"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approve_with_email_refuses_when_outbound_mail_is_not_configured(db_session):
    """出口没配 -> 503，而且配对必须还是 pending：不许「批了但锁没加上」。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            refused = await _approve(client, opened["user_code"], notify_email=EMAIL)
            assert refused.status_code == 503, refused.text
            # 关键：没有半个状态 —— 配对没被批准，agent 没被建。
            assert (await _lookup(client, opened["user_code"]))["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_email_confirm_is_a_real_third_lock(db_session, outbox, monkeypatch):
    monkeypatch.setattr("api.routes.agents.is_prod_like_env", lambda: True)
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await _approve(client, opened["user_code"], notify_email=EMAIL)
            assert approved.status_code == 200, approved.text
            confirm = approved.json()["email_confirm"]
            assert confirm["required"] is True and confirm["state"] == "pending"
            assert confirm["email_masked"] == "ow***@example.com"
            match_code = confirm["match_code"]
            assert re.fullmatch(r"\d{6}", match_code or "")

            # 信真的出去了，且正文里只有短码与链接 —— 没有任何凭据。
            assert len(outbox) == 1 and outbox[0]["to"] == EMAIL
            mail = outbox[0]
            assert match_code in mail["text"]
            assert "karma_" not in mail["text"] and "karma_" not in (mail["html"] or "")
            others = _other_codes(mail["text"], match_code)

            # 邮箱没点之前，agent 拿不到凭据 —— 但能看到要点哪个码。
            gated = await _claim(client, opened["pairing_code"])
            assert gated["status"] == "awaiting_email_confirm"
            assert gated["match_code"] == match_code
            assert gated["email_confirm_state"] == "pending"
            assert "credentials" not in gated

            # 光知道那个码换不到东西：码本身不是 token。
            misread = await _click(client, opened["user_code"], match_code)
            assert misread.status_code == 409, misread.text
            assert (await _lookup(client, opened["user_code"]))["email_confirm"]["attempts_left"] == 5

            # 点了一个干扰码同样算错（主人手滑也要记账）。
            wrong = await _click(client, opened["user_code"], _token_for(mail["text"], others[0]))
            assert wrong.status_code == 409
            assert (await _lookup(client, opened["user_code"]))["email_confirm"]["attempts_left"] == 4

            # 点对了：放行。
            good = await _click(client, opened["user_code"], _token_for(mail["text"], match_code))
            assert good.status_code == 200, good.text
            again = await _click(client, opened["user_code"], _token_for(mail["text"], match_code))
            assert again.status_code == 200  # 重复点不报错、也不重复扣
            assert (await _lookup(client, opened["user_code"]))["email_confirm"]["state"] == "confirmed"

            released = await _claim(client, opened["pairing_code"])
            assert released["status"] == "approved"
            api_key = released["credentials"]["api_key"]
            assert api_key and api_key not in mail["text"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wrong_clicks_exhaust_and_burn_the_pairing(db_session, outbox):
    """连错到上限就把这次配对就地作废 —— 与交接码同一口径。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await _approve(client, opened["user_code"], notify_email=EMAIL)
            assert approved.status_code == 200, approved.text
            mail = outbox[0]
            bad_tokens = [
                _token_for(mail["text"], c)
                for c in _other_codes(mail["text"], approved.json()["email_confirm"]["match_code"])
            ]
            verdicts = []
            for _ in range(pairing.EMAIL_CONFIRM_MAX_ATTEMPTS):
                r = await _click(client, opened["user_code"], bad_tokens[0])
                verdicts.append(r.status_code)
            assert verdicts[: pairing.EMAIL_CONFIRM_MAX_ATTEMPTS - 1] == [409] * (
                pairing.EMAIL_CONFIRM_MAX_ATTEMPTS - 1
            )
            assert verdicts[-1] == 409
            # 配对已作废：claim 拿不到凭据，也不再有「等你点码」的暗示。
            burned = await _lookup(client, opened["user_code"])
            assert burned["status"] == "expired"
            assert burned["email_confirm"]["state"] == "expired"
            claimed = await _claim(client, opened["pairing_code"])
            assert claimed["status"] == "expired"
            assert "credentials" not in claimed
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resend_rotates_the_token(db_session, outbox):
    """重发 = 重出码：旧 token 当场作废，只有新的那条能解锁。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await _approve(client, opened["user_code"], notify_email=EMAIL)
            assert approved.status_code == 200, approved.text
            old_code = approved.json()["email_confirm"]["match_code"]
            old_token = _token_for(outbox[0]["text"], old_code)

            resend = await client.post(
                "/v1/agent-pairing/email-confirm/resend",
                json={"user_code": opened["user_code"], "email": EMAIL},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert resend.status_code == 200, resend.text
            assert len(outbox) == 2
            new_code = resend.json()["match_code"]

            stale = await _click(client, opened["user_code"], old_token)
            assert stale.status_code == 409, stale.text

            fresh = await _click(client, opened["user_code"], _token_for(outbox[1]["text"], new_code))
            assert fresh.status_code == 200, fresh.text
            assert (await _claim(client, opened["pairing_code"]))["status"] == "approved"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resend_needs_the_owner_session(db_session, outbox):
    """重发也是一次「主人动作」：没有主人会话就 403，不给匿名者当发信机。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await _approve(client, opened["user_code"], notify_email=EMAIL)
            assert approved.status_code == 200, approved.text
            r = await client.post(
                "/v1/agent-pairing/email-confirm/resend",
                json={"user_code": opened["user_code"], "email": EMAIL},
            )
            assert r.status_code == 403, r.text
            assert len(outbox) == 1
    finally:
        app.dependency_overrides.clear()
