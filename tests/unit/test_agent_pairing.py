"""Agent pairing: agent asks → owner approves in the console → agent collects.

Two things are asserted rather than assumed, because both are the reason this
flow exists at all:

* no credential is ever handed to the console (the agent collects it itself),
* a credential is delivered exactly once (second claim gets nothing).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app import app
from api.middleware.auth import validate_api_key_for_agent
from db.models.orm import Base
from db.session import get_db
from services import agent_pairing as pairing
from services.agent_bootstrap_credentials import reset_bootstrap_keys
from services.agent_onboarding_template import (
    get_industry,
    load_onboarding_catalog,
    validate_service_specs_for_industries,
)
from services.agent_profile_store import clear_profile_cards
from services.runtime_key_service import create_runtime_key_record

OWNER = "kid_pairapprover0001"
OTHER = "kid_pairsomeoneelse02"

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
PAGE = CONSOLE / "pages" / "cyber" / "index.html"
PAIRING_JS = CONSOLE / "scripts" / "cyber-pairing.js"
SPEC_JS = CONSOLE / "scripts" / "karma-service-spec.js"
PHRASE_DIR = CONSOLE / "scripts" / "i18n-phrase"
GATE = ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh"


@pytest_asyncio.fixture
async def db_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pair.sqlite", future=True)
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


def _food_specs() -> dict:
    spec = dict(get_industry("food_delivery")["example_service_spec"])
    assert validate_service_specs_for_industries(["food_delivery"], {"food_delivery": spec}) == []
    return {"food_delivery": spec}


async def _client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _open_request(client, **over) -> dict:
    body = {
        "agent_name": "OpenClaw 采购助手",
        "platform": "openclaw",
        "public_key": "ed25519:AAAA",
        "requested_side": "seller",
        "requested_vertical": "food",
        "self_description": "handles supplier orders",
    }
    body.update(over)
    r = await client.post("/v1/agent-pairing/request", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _issue_handoff(client, user_code: str) -> str:
    """批准之后请主人签发交接码，返回那串明文（只在签发响应里出现一次）。"""
    r = await client.post(
        "/v1/agent-pairing/handoff",
        json={"user_code": user_code},
        headers={"X-Karma-Identity-Id": OWNER},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handoff_state"] == "active"
    code = body["handoff_code"]
    assert code
    # 明文不许落库：磁盘上只有 SHA-256。
    assert code not in str(pairing._RECORDS)  # noqa: SLF001
    return code


@pytest.mark.asyncio
async def test_request_is_public_and_hands_out_one_time_codes(db_session):
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            assert opened["user_code"].count("-") == 1
            assert len(opened["pairing_code"]) >= 32
            assert opened["verification_uri"].endswith("?pair=" + opened["user_code"])
            # The agent's own code must not come back from any owner-facing read.
            assert "pairing_code" not in pairing.lookup_by_user_code(opened["user_code"])
            # ...and the raw code is not what sits on disk.
            stored = pairing._RECORDS  # noqa: SLF001 - deliberate storage assertion
            assert opened["pairing_code"] not in str(stored)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_agent_polls_pending_until_the_owner_approves(db_session):
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            r = await client.post(
                "/v1/agent-pairing/claim", json={"pairing_code": opened["pairing_code"]}
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "pending"
            assert "credentials" not in r.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approval_needs_an_owner_session(db_session):
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            r = await client.post(
                "/v1/agent-pairing/approve",
                json={"user_code": opened["user_code"], "side": "seller", "vertical": "food"},
            )
            assert r.status_code == 403, r.text
            r2 = await client.get(
                "/v1/agent-pairing/lookup", params={"user_code": opened["user_code"]}
            )
            assert r2.status_code == 403, r2.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_full_flow_delivers_the_bootstrap_key_exactly_once(db_session, monkeypatch):
    monkeypatch.setattr("api.routes.agents.is_prod_like_env", lambda: True)
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)

            # The console sees who is asking, and nothing it could leak.
            seen = await client.get(
                "/v1/agent-pairing/lookup",
                params={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert seen.status_code == 200, seen.text
            view = seen.json()
            assert view["status"] == "pending"
            assert view["agent_name"] == "OpenClaw 采购助手"
            assert view["public_key_fingerprint"]
            assert "pairing_code" not in view

            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "display_name": "Owner Food Agent",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text
            body = approved.json()
            agent_id = body["agent"]["agent_id"]
            assert body["pairing"]["has_api_key"] is True
            # The console never receives the secret — that is the whole point.
            assert "KARMA_API_KEY" not in approved.text
            assert f"karma_{agent_id}_" not in approved.text

            # 只有 agent 自己那串 pairing_code 已经不够了 —— 第二把锁还没发。
            half = await client.post(
                "/v1/agent-pairing/claim", json={"pairing_code": opened["pairing_code"]}
            )
            assert half.status_code == 200, half.text
            assert half.json()["status"] == "awaiting_handoff"
            assert half.json()["handoff_state"] == "none"
            assert "credentials" not in half.json()

            handoff_code = await _issue_handoff(client, opened["user_code"])

            # 操作台只看得到「签没签、还剩多久」，永远看不到那串码本身。
            recheck = await client.get(
                "/v1/agent-pairing/lookup",
                params={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert recheck.json()["handoff_state"] == "active"
            assert handoff_code not in recheck.text

            claimed = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": handoff_code},
            )
            assert claimed.status_code == 200, claimed.text
            payload = claimed.json()
            assert payload["status"] == "approved"
            assert payload["agent_id"] == agent_id
            assert payload["handoff"] == {"required": True, "consumed": True}
            api_key = payload["credentials"]["api_key"]
            assert api_key and validate_api_key_for_agent(agent_id, api_key)
            assert payload["env_snippet"]["KARMA_API_KEY"] == api_key

            # One shot: the plaintext is gone from the store and from any retry.
            again = await client.post(
                "/v1/agent-pairing/claim", json={"pairing_code": opened["pairing_code"]}
            )
            assert again.json()["status"] == "claimed"
            assert "credentials" not in again.json()
            assert api_key not in str(pairing._RECORDS)  # noqa: SLF001

            # Approving the same request twice must not mint a second agent.
            replay = await client.post(
                "/v1/agent-pairing/approve",
                json={"user_code": opened["user_code"], "side": "seller", "vertical": "food"},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert replay.status_code == 409, replay.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_approval_needs_a_valid_service_spec_that_the_console_can_supply(db_session):
    """agent 自报的硬指标不合规时，批准会被 400 拒掉。

    这正是配对面板必须带上一份可编辑表单的原因：主人看到的不能只是「HTTP 400」，
    而且要能在同一页把指标改成合规的那一份。
    """
    client = await _client(db_session)
    try:
        async with client:
            # agent 报了一份残的：绝大多数必填项没填，价格还写成了数字。
            opened = await _open_request(
                client,
                answers={
                    "industry_ids": ["food_delivery"],
                    "service_specs": {"food_delivery": {"pricing": {"base_fare": 3.5}}},
                },
            )
            missing = await client.post(
                "/v1/agent-pairing/approve",
                json={"user_code": opened["user_code"], "side": "seller", "vertical": "food"},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert missing.status_code == 400, missing.text
            assert "service_specs" in missing.text
            # 被拒之后配对还是 pending，主人补完指标能接着批。
            still = await client.get(
                "/v1/agent-pairing/lookup",
                params={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert still.json()["status"] == "pending"

            # 主人在操作台把指标改成合规的那一份 —— 表单里的答案覆盖 agent 自报的。
            fixed = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert fixed.status_code == 200, fixed.text
            assert fixed.json()["p1_status"]["checks"]["service_specs_valid"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_lookup_resolves_the_agents_vertical_into_a_catalog_industry(db_session):
    """agent 说「food」，操作台要认成 food_delivery —— 否则硬指标表单渲染不出来。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            seen = await client.get(
                "/v1/agent-pairing/lookup",
                params={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            view = seen.json()
            assert view["requested_vertical"] == "food"
            assert view["requested_industry_id"] == "food_delivery"
    finally:
        app.dependency_overrides.clear()


def test_vertical_alias_resolution_matches_the_one_click_table():
    assert pairing.normalize_requested_vertical("food") == "food_delivery"
    assert pairing.normalize_requested_vertical("FOOD") == "food_delivery"
    assert pairing.normalize_requested_vertical("food_delivery") == "food_delivery"
    assert pairing.normalize_requested_vertical("  hotel ") == "hotel_booking"
    # 认不出来就原样留着，让主人自己选，别猜。
    assert pairing.normalize_requested_vertical("not_a_real_vertical") == "not_a_real_vertical"
    assert pairing.normalize_requested_vertical(None) == ""


@pytest.mark.asyncio
async def test_runtime_key_can_only_be_attached_by_its_own_identity(db_session):
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "display_name": "Owner Food Agent",
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text

            foreign_token, _ = await create_runtime_key_record(
                db=db_session,
                wallet_address="0x" + "22" * 20,
                karma_identity_id=OTHER,
                permissions=["request_voucher"],
                single_limit=10.0,
                daily_limit=20.0,
                expire_at=datetime.utcnow() + timedelta(days=1),
                agent_name="someone else's agent",
                agent_binding=None,
            )
            rejected = await client.post(
                "/v1/agent-pairing/attach-runtime-key",
                json={"user_code": opened["user_code"], "runtime_key": foreign_token},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert rejected.status_code == 403, rejected.text

            own_token, _ = await create_runtime_key_record(
                db=db_session,
                wallet_address="0x" + "11" * 20,
                karma_identity_id=OWNER,
                permissions=["request_voucher", "submit_receipt"],
                single_limit=25.0,
                daily_limit=50.0,
                expire_at=datetime.utcnow() + timedelta(days=7),
                agent_name="OpenClaw 采购助手",
                agent_binding=None,
            )
            attached = await client.post(
                "/v1/agent-pairing/attach-runtime-key",
                json={"user_code": opened["user_code"], "runtime_key": own_token},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert attached.status_code == 200, attached.text
            assert attached.json()["has_runtime_key"] is True
            assert own_token not in attached.text

            handoff_code = await _issue_handoff(client, opened["user_code"])
            claimed = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": handoff_code},
            )
            payload = claimed.json()
            assert payload["credentials"]["runtime_key"] == own_token
            assert payload["env_snippet"]["KARMA_RUNTIME_KEY"] == own_token
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_expired_pairing_delivers_nothing(db_session, monkeypatch):
    monkeypatch.setattr(pairing, "DEFAULT_TTL_SECONDS", 0)
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            claimed = await client.post(
                "/v1/agent-pairing/claim", json={"pairing_code": opened["pairing_code"]}
            )
            assert claimed.json()["status"] == "expired"
            assert "credentials" not in claimed.json()
            denied = await client.post(
                "/v1/agent-pairing/approve",
                json={"user_code": opened["user_code"], "side": "seller", "vertical": "food"},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert denied.status_code == 409, denied.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_denied_pairing_delivers_nothing(db_session):
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            r = await client.post(
                "/v1/agent-pairing/deny",
                json={"user_code": opened["user_code"], "reason": "not mine"},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "denied"
            claimed = await client.post(
                "/v1/agent-pairing/claim", json={"pairing_code": opened["pairing_code"]}
            )
            assert claimed.json()["status"] == "denied"
            assert "credentials" not in claimed.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unknown_codes_are_rejected_without_leaking_anything(db_session):
    client = await _client(db_session)
    try:
        async with client:
            bad_claim = await client.post(
                "/v1/agent-pairing/claim", json={"pairing_code": "not-a-real-code-000000"}
            )
            assert bad_claim.status_code == 404, bad_claim.text
            bad_lookup = await client.get(
                "/v1/agent-pairing/lookup",
                params={"user_code": "ZZZZ-ZZZZ"},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert bad_lookup.status_code == 404, bad_lookup.text
    finally:
        app.dependency_overrides.clear()


def test_the_console_has_a_pairing_panel_wired_to_the_panel_script():
    """静态接线：页面、侧栏、脚本映射三者少一个，用户就点不到这一页。"""
    html = PAGE.read_text(encoding="utf-8")
    assert 'id="ag-pair"' in html
    assert 'data-sub="pair"' in html
    assert "cyber-pairing.js" in html
    assert 'id="pair-code"' in html
    assert 'id="pair-approve"' in html
    assert 'id="pair-grant-go"' in html
    # 交接码那一块：没有它，主人就没法把第二把锁交给 agent。
    assert 'id="pair-handoff"' in html
    assert 'id="pair-handoff-go"' in html

    console_js = (CONSOLE / "scripts" / "cyber-console.js").read_text(encoding="utf-8")
    assert 'pair: "#ag-pair"' in console_js
    assert 'pair: ["#ag-pair"]' in console_js


def test_the_pairing_panel_never_asks_the_owner_for_a_secret():
    """方向不能反：这一页只批准请求，不接受任何「把密钥填进来」。"""
    js = PAIRING_JS.read_text(encoding="utf-8")
    for call in (
        "lookupPairing",
        "approvePairing",
        "denyPairing",
        "attachPairingRuntimeKey",
        "issuePairingHandoff",
    ):
        assert call in js, call
    # 签发与倒计时的渲染都得在面板脚本里，不能在别处再抄一份。
    for needle in ("renderHandoff", "issueHandoff", "handoffExpiresAt"):
        assert needle in js, needle
    for banned in ("privateKey", "private_key", "mnemonic", "seedPhrase", "seed_phrase"):
        assert banned not in js, banned
    # The agent's own secret must never be asked for on screen either.
    assert "pairing_code" not in js


def test_the_pairing_panel_carries_an_editable_hard_requirements_form():
    """行业硬指标不是只读展示：agent 报错了，主人要在这一页当场改得动。"""
    html = PAGE.read_text(encoding="utf-8")
    assert 'id="pair-spec-form"' in html
    assert 'id="pair-spec-note"' in html
    assert "karma-service-spec.js" in html
    # 共用模块必须先加载：两个用它的脚本都在后面。
    assert html.index("karma-service-spec.js") < html.index("cyber-agents.js")
    assert html.index("karma-service-spec.js") < html.index("cyber-pairing.js")

    js = PAIRING_JS.read_text(encoding="utf-8")
    for needle in (
        "KarmaServiceSpec",
        "renderPairSpec",
        "applyValues",
        "getOnboardingIndustry",
        "requested_industry_id",
    ):
        assert needle in js, needle
    # 表单本身不许在这里再抄一份渲染 / 收集逻辑。
    for banned in ("function renderSpecField", "function collectSpec", "data-spec-object="):
        assert banned not in js, banned


def test_the_wizard_and_the_pairing_panel_share_one_hard_requirements_form():
    """两处各写一套必然会漂，所以它只存在于 karma-service-spec.js。"""
    spec_js = SPEC_JS.read_text(encoding="utf-8")
    for needle in ("renderForm", "applyValues", "fillFromExample", "collect", "industryTitle"):
        assert needle in spec_js, needle
    for banned in ("privateKey", "private_key", "mnemonic"):
        assert banned not in spec_js, banned

    agents = (CONSOLE / "scripts" / "cyber-agents.js").read_text(encoding="utf-8")
    assert "KarmaServiceSpec" in agents
    # 向导里那份副本必须删干净，别再长回来。
    assert "function isPricePath" not in agents
    assert "function pathKey" not in agents

    gate = GATE.read_text(encoding="utf-8")
    assert "scripts/karma-service-spec.js" in gate
    loops = [ln for ln in gate.splitlines() if ln.strip().startswith("for js in")]
    assert loops and "karma-service-spec.js" in loops[0]


def test_every_language_pack_carries_the_pairing_copy():
    """六种语言都要有这一页的文案，否则切语言就会掉回中文。"""
    i18n = (CONSOLE / "scripts" / "i18n-cyber.js").read_text(encoding="utf-8")
    assert i18n.count('"sub.agents.pair"') == 5, "五个语言包（es-AR/es-SV 共用拉美西语）都要有这一项"

    samples = (
        "配对码接入",
        "授权额度并交付",
        "等待你批准",
        "公钥指纹",
        "行业硬指标还差 {0} 项",
        "请先选择行业 —— 硬指标是按行业定的",
        "硬指标表单未加载，请刷新页面",
        # 交接码（第二把锁）：五门语言都要有，否则切语言就掉回中文。
        "交接码 · 交给 agent 的第二把锁",
        "签发交接码",
        "复制交接码",
        "剩余 {0} · 交给 agent 后它就能领凭据了",
    )
    for lang in ("en", "ja", "ko", "es-AR", "es-SV"):
        pack = (PHRASE_DIR / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"


@pytest.mark.asyncio
async def test_handoff_needs_an_owner_session_and_an_approved_pairing(db_session):
    """签发交接码是主人的动作：没登录、没批准、不是自己的配对，都要被挡住。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)

            # 批准之前没有交接码可签。
            early = await client.post(
                "/v1/agent-pairing/handoff",
                json={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert early.status_code == 409, early.text

            # 没有主人会话也不行 —— 否则任何人都能给自己签发第二把锁。
            anon = await client.post(
                "/v1/agent-pairing/handoff", json={"user_code": opened["user_code"]}
            )
            assert anon.status_code == 403, anon.text

            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text

            # 别人的配对，签不动。
            foreign = await client.post(
                "/v1/agent-pairing/handoff",
                json={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OTHER},
            )
            assert foreign.status_code == 403, foreign.text

            ok = await client.post(
                "/v1/agent-pairing/handoff",
                json={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert ok.status_code == 200, ok.text
            assert ok.json()["handoff_code"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reissuing_the_handoff_code_kills_the_old_one(db_session):
    """重签就是重签：旧码当场作废，免得两串码同时在世上流转。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text

            first = await _issue_handoff(client, opened["user_code"])
            second = await _issue_handoff(client, opened["user_code"])
            assert first != second

            stale = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": first},
            )
            assert stale.status_code == 403, stale.text

            fresh = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": second},
            )
            assert fresh.status_code == 200, fresh.text
            assert fresh.json()["credentials"]["api_key"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_expired_handoff_code_delivers_nothing(db_session, monkeypatch):
    """交接码过期就只剩「重新签发」，agent 拿不到凭据。"""
    monkeypatch.setattr(pairing, "HANDOFF_TTL_SECONDS", -1)
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text

            issued = await client.post(
                "/v1/agent-pairing/handoff",
                json={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert issued.status_code == 200, issued.text
            code = issued.json()["handoff_code"]

            claimed = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": code},
            )
            assert claimed.status_code == 200, claimed.text
            body = claimed.json()
            assert body["status"] == "awaiting_handoff"
            assert body["handoff_state"] == "expired"
            assert "credentials" not in body

            # 配对本身还没过期：主人重新签发就能救回来。
            again = await client.post(
                "/v1/agent-pairing/handoff",
                json={"user_code": opened["user_code"]},
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert again.status_code == 200, again.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_five_wrong_handoff_codes_expire_the_pairing(db_session):
    """连着猜错交接码：就地作废这次配对，凭据一并销毁，只能重新申请。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text
            good = await _issue_handoff(client, opened["user_code"])
            wrong = "ZZZZ-ZZZZ" if good != "ZZZZ-ZZZZ" else "YYYY-YYYY"

            for i in range(4):
                bad = await client.post(
                    "/v1/agent-pairing/claim",
                    json={"pairing_code": opened["pairing_code"], "handoff_code": wrong},
                )
                assert bad.status_code == 403, (i, bad.text)

            # 第 5 次：配对作废。
            last = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": wrong},
            )
            assert last.status_code == 403, last.text
            assert "expired" in last.text

            # 就算现在拿着正确的那串码，也领不到东西了。
            after = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": good},
            )
            assert after.status_code == 200, after.text
            assert after.json()["status"] == "expired"
            assert "credentials" not in after.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_the_plaintext_handoff_code_never_lands_on_disk(db_session):
    """交接码和 pairing_code 一样：磁盘上只留哈希，明文只回一次。"""
    client = await _client(db_session)
    try:
        async with client:
            opened = await _open_request(client)
            approved = await client.post(
                "/v1/agent-pairing/approve",
                json={
                    "user_code": opened["user_code"],
                    "side": "seller",
                    "vertical": "food",
                    "answers": {
                        "industry_ids": ["food_delivery"],
                        "service_specs": _food_specs(),
                    },
                },
                headers={"X-Karma-Identity-Id": OWNER},
            )
            assert approved.status_code == 200, approved.text
            code = await _issue_handoff(client, opened["user_code"])

            dumped = str(pairing._RECORDS)  # noqa: SLF001
            assert code not in dumped
            assert code.replace("-", "") not in dumped
            # 再看一眼落盘的那份 JSON。
            blob = Path(pairing._STORE_PATH).read_text(encoding="utf-8")  # noqa: SLF001
            assert code not in blob
            assert code.replace("-", "") not in blob

            # 领取之后连状态都变成 used，重放只剩 claimed。
            claimed = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": code},
            )
            assert claimed.status_code == 200, claimed.text
            replay = await client.post(
                "/v1/agent-pairing/claim",
                json={"pairing_code": opened["pairing_code"], "handoff_code": code},
            )
            assert replay.json()["status"] == "claimed"
            assert "credentials" not in replay.json()
    finally:
        app.dependency_overrides.clear()
