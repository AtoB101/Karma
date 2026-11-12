"""Runtime Gateway — agent 读得懂边界，也只能按边界办事。

线上真机验过、也在这里钉死：

* ``GET /runtime/policy`` 把「我能自己拍板到什么程度」说清楚（只本人）。
* ``GET /runtime/capacity`` 和操作台读同一个口径（不是那张空表）。
* ``POST /runtime/discover`` 需要 ``discover_agents``；``POST /runtime/place-order``
  需要 ``place_order``，而且额度边界全在服务端算：超硬上限直接 403，
  超自动额度就地停下、不出凭证、不扣额度，等主人在操作台点头。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from services import human_confirmation_policy as hcp
from services.agent_boundary import clear_agent_boundaries, get_agent_boundary
from services.agent_directory import connect_agent, refresh_p1_ready
from services.agent_onboarding_template import materialize_onboarding
from services.agent_p1_readiness import (
    attest_responsibility_ack,
    boundary_content_hash,
    canonical_responsibility_ack,
    ensure_owner_identity,
)
from services.agent_profile_store import clear_profile_cards
from services.important_fields_capture import auto_triple_lock_fields
from services.important_fields_standard import example_for_scene
from services.human_confirmation_policy import resolve_gate
from services.runtime_key_service import ALLOWED_PERMISSIONS
from services.runtime_wallet import build_create_key_message

def test_the_owners_budget_is_what_lets_the_agent_act_alone():
    """主人给过额度 → 额度内的「挑商家 / 下单」agent 自己走；

    取消 / 争议 / 改价 / 锁重要字段这几步永远不放开 —— 额度再大也不行。
    """
    auto = resolve_gate(
        scene_id="food_delivery", role="buyer", step="accept_order", policy_auto_allowed=True
    )
    assert auto["needs_owner_confirmation"] is False
    assert auto["effective_mode"] == "AUTO"
    assert auto["automation_policy_override"] is True

    no_policy = resolve_gate(
        scene_id="food_delivery", role="buyer", step="accept_order", policy_auto_allowed=False
    )
    assert no_policy["needs_owner_confirmation"] is True
    assert no_policy["automation_policy_override"] is False

    for step in ("cancel", "dispute_or_refund", "price_change_or_surge", "lock_important_fields"):
        gate = resolve_gate(
            scene_id="food_delivery", role="buyer", step=step, policy_auto_allowed=True
        )
        assert gate["needs_owner_confirmation"] is True, step
        assert gate["automation_policy_override"] is False, step

ROOT = Path(__file__).resolve().parents[2]
CONSOLE_JS = ROOT / "apps/console/scripts/cyber-authorize.js"
GUIDE = ROOT / "docs/runtime-key-guide.md"

BASE_PERMS = ["sync_task_status", "discover_agents", "place_order"]


@pytest.fixture(autouse=True)
def _reset_in_process_state():
    clear_agent_boundaries()
    clear_profile_cards()
    hcp.reset_confirmation_sessions()
    hcp.load_policy_catalog.cache_clear()
    yield
    clear_agent_boundaries()
    clear_profile_cards()
    hcp.reset_confirmation_sessions()


async def _mint(
    client: AsyncClient,
    *,
    account: Account,
    karma_identity_id: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
) -> str:
    expire = datetime.utcnow() + timedelta(days=7)
    agent_name = f"agent-{karma_identity_id[:8]}"
    msg = build_create_key_message(
        karma_identity_id=karma_identity_id,
        wallet_address=account.address,
        permissions=permissions,
        single_limit=single_limit,
        daily_limit=daily_limit,
        expire_time=expire,
        agent_name=agent_name,
        agent_binding=None,
    )
    signed = account.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": account.address,
            "karma_identity_id": karma_identity_id,
            "wallet_signature": signed.signature.hex(),
            "permissions": permissions,
            "single_limit": single_limit,
            "daily_limit": daily_limit,
            "expire_time": expire.isoformat(),
            "agent_name": agent_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["runtime_key"])


async def _save_policy(
    client: AsyncClient,
    *,
    identity: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
    high_risk_mode: str = "above_single",
) -> None:
    resp = await client.put(
        f"/v1/identities/{identity}/automation-policy",
        headers={"X-Karma-Identity-Id": identity},
        json={
            "auto_enabled": True,
            "responsibility_acknowledged": True,
            "single_limit": single_limit,
            "daily_limit": daily_limit,
            "permissions": sorted(permissions),
            "high_risk_mode": high_risk_mode,
        },
    )
    assert resp.status_code == 200, resp.text


async def _p1_merchant(db: AsyncSession, *, agent_id: str, industry: str, capability: str) -> None:
    owner = f"owner-{agent_id}"
    await ensure_owner_identity(db, owner, display_hint=owner)
    mat = materialize_onboarding(
        profile_id="merchant",
        answers={
            "display_name": agent_id,
            "industry_ids": [industry],
            "use_example_service_specs": True,
            "service_targets": ["consumer"],
            "service_area": {"mode": "local", "regions": ["上海"]},
            "capability_summary": industry,
            "boundaries": "超范围不接单",
        },
        agent_id=agent_id,
    )
    caps = list(mat["agent_connect"]["capabilities"] or []) + [
        "onboarding:merchant",
        f"industry:{industry}",
        capability,
    ]
    row = await connect_agent(
        db,
        agent_id=agent_id,
        name=mat["agent_connect"]["name"],
        role="worker",
        capabilities=caps,
        profile_card=mat["profile_card"],
        identity_class="merchant",
        owner_identity_id=owner,
        responsibility_acknowledged=True,
    )
    bhash = boundary_content_hash(get_agent_boundary(row.agent_id)) or ""
    ack = attest_responsibility_ack(
        {
            **canonical_responsibility_ack(
                agent_id=row.agent_id,
                owner_identity_id=owner,
                identity_class="merchant",
                boundary_hash=bhash,
                acknowledged_at="2026-08-01T00:00:00Z",
            ),
            "acknowledged": True,
        }
    )
    meta = dict(row.onboarding_meta or {})
    meta.update(
        {
            "responsibility_ack": ack,
            "boundary_hash": bhash,
            "used_example_service_specs": True,
            "owner_identity_id": owner,
        }
    )
    row.onboarding_meta = meta
    row.boundary_hash = bhash
    await db.flush()
    await refresh_p1_ready(db, row.agent_id)


def _matched_capture(*, scene_id: str, amount: float, buyer: str, seller: str) -> str:
    fields = dict(example_for_scene(scene_id)["fields"])
    if "amount" in fields:
        fields["amount"] = f"{amount:.2f}"
    matched = auto_triple_lock_fields(
        scene_id=scene_id,
        fields=fields,
        interaction_ref=f"fulfill:{buyer}:{seller}",
        buyer_agent_id=buyer,
        seller_agent_id=seller,
    )
    assert matched.get("triple_match"), matched
    return str(matched["capture_id"])


# --------------------------------------------------------------------------- 接线


def test_the_new_permissions_are_wired_on_both_sides():
    """服务端允许的权限，操作台必须勾得到、文档必须写清楚，否则用户永远开不出来。"""
    assert {"discover_agents", "place_order"} <= set(ALLOWED_PERMISSIONS)
    js = CONSOLE_JS.read_text(encoding="utf-8")
    for key in ("discover_agents", "place_order"):
        assert f'key: "{key}"' in js, f"向导缺少权限项 {key}"
        assert f'"{key}",' in js, f"默认勾选缺少 {key}"
    guide = GUIDE.read_text(encoding="utf-8")
    assert "discover_agents" in guide and "place_order" in guide


# --------------------------------------------------------------------------- 读边界


@pytest.mark.asyncio
async def test_capacity_reports_the_same_lock_as_the_console(client: AsyncClient, db_session):
    acct = Account.create()
    identity = f"cap-{uuid.uuid4().hex[:10]}"
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=["sync_task_status"],
        single_limit=100.0,
        daily_limit=500.0,
    )
    lock = await client.post(
        f"/v1/capacity/{identity}/lock",
        json={"amount": 15.0},
        headers={"X-Karma-Identity-Id": identity},
    )
    assert lock.status_code == 200, lock.text

    cap = await client.get("/runtime/capacity", headers={"X-Karma-Runtime-Key": rt})
    assert cap.status_code == 200, cap.text
    body = cap.json()
    assert body["identity_id"] == identity
    assert body["scope"] == "identity"
    assert body["total_locked_usdc"] == pytest.approx(15.0)
    assert body["available_usdc"] == pytest.approx(15.0)

    alloc = await client.get(
        f"/v1/capacity/{identity}/allocations", headers={"X-Karma-Identity-Id": identity}
    )
    assert alloc.status_code == 200, alloc.text
    # 两边必须是同一个数：agent 读到的额度就是操作台显示的额度。
    assert alloc.json()["locked_usdc"] == pytest.approx(body["total_locked_usdc"])


@pytest.mark.asyncio
async def test_policy_endpoint_reads_the_own_saved_boundary(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    acct = Account.create()
    identity = f"pol-{uuid.uuid4().hex[:10]}"
    await _save_policy(
        client, identity=identity, permissions=BASE_PERMS, single_limit=5.0, daily_limit=15.0
    )
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=BASE_PERMS,
        single_limit=5.0,
        daily_limit=15.0,
    )
    resp = await client.get("/runtime/policy", headers={"X-Karma-Runtime-Key": rt})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["karma_identity_id"] == identity
    assert body["configured"] is True
    assert set(body["permissions"]) == set(BASE_PERMS)
    assert body["limits"]["per_order_auto_approve_usdc"] == pytest.approx(5.0)
    assert body["limits"]["per_order_hard_cap_usdc"] == pytest.approx(5.0)
    assert body["limits"]["daily_hard_cap_usdc"] == pytest.approx(15.0)
    assert body["rules_zh"]
    # 没有策略就不给自动额度：读到的必须是 0，不能编数字出来。
    assert body["limits"]["daily_used_usdc"] == pytest.approx(0.0)
    assert body["boundaries"]["high_risk_mode"] == "above_single"


@pytest.mark.asyncio
async def test_high_risk_mode_always_leaves_no_auto_budget(
    client: AsyncClient, db_session, monkeypatch
):
    """主人选了「每一笔都找我确认」，额度再小也不能自动下。"""
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    acct = Account.create()
    identity = f"pol-always-{uuid.uuid4().hex[:8]}"
    await _save_policy(
        client,
        identity=identity,
        permissions=BASE_PERMS,
        single_limit=5.0,
        daily_limit=15.0,
        high_risk_mode="always",
    )
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=BASE_PERMS,
        single_limit=5.0,
        daily_limit=15.0,
    )
    body = (await client.get("/runtime/policy", headers={"X-Karma-Runtime-Key": rt})).json()
    assert body["limits"]["per_order_auto_approve_usdc"] == 0.0
    assert any("每一笔" in r for r in body["rules_zh"])


# --------------------------------------------------------------------------- 发现


@pytest.mark.asyncio
async def test_discovery_needs_the_permission(client: AsyncClient, db_session):
    acct = Account.create()
    identity = f"disc-{uuid.uuid4().hex[:10]}"
    blind = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=["sync_task_status"],
        single_limit=5.0,
        daily_limit=15.0,
    )
    blocked = await client.post(
        "/runtime/discover",
        headers={"X-Karma-Runtime-Key": blind},
        json={"requirement_text": "帮我点一份披萨外卖 12 USDC", "client_nonce": uuid.uuid4().hex},
    )
    assert blocked.status_code == 403

    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=["sync_task_status", "discover_agents"],
        single_limit=5.0,
        daily_limit=15.0,
    )
    ok = await client.post(
        "/runtime/discover",
        headers={"X-Karma-Runtime-Key": rt},
        json={"requirement_text": "帮我点一份披萨外卖 12 USDC", "client_nonce": uuid.uuid4().hex},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["requested_by_identity_id"] == identity
    assert "recommended" in body and "candidates" in body


# --------------------------------------------------------------------------- 下单边界


@pytest.mark.asyncio
async def test_place_order_refuses_above_the_key_hard_cap(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    acct = Account.create()
    identity = f"ord-cap-{uuid.uuid4().hex[:8]}"
    await _save_policy(
        client, identity=identity, permissions=BASE_PERMS, single_limit=5.0, daily_limit=15.0
    )
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=BASE_PERMS,
        single_limit=5.0,
        daily_limit=15.0,
    )
    resp = await client.post(
        "/runtime/place-order",
        headers={"X-Karma-Runtime-Key": rt},
        json={
            "requirement_text": "帮我点一份披萨外卖 50 USDC",
            "amount": 50.0,
            "client_nonce": uuid.uuid4().hex,
        },
    )
    assert resp.status_code == 403, resp.text
    assert "single_limit" in resp.text


@pytest.mark.asyncio
async def test_place_order_without_the_permission_is_refused(client: AsyncClient, db_session):
    acct = Account.create()
    identity = f"ord-perm-{uuid.uuid4().hex[:8]}"
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=["sync_task_status", "discover_agents"],
        single_limit=5.0,
        daily_limit=15.0,
    )
    resp = await client.post(
        "/runtime/place-order",
        headers={"X-Karma-Runtime-Key": rt},
        json={
            "requirement_text": "帮我点一份披萨外卖 5 USDC",
            "amount": 5.0,
            "client_nonce": uuid.uuid4().hex,
        },
    )
    assert resp.status_code == 403
    assert "place_order" in resp.text


@pytest.mark.asyncio
async def test_place_order_inside_the_budget_gets_a_voucher(
    client: AsyncClient, db_session, monkeypatch
):
    """额度内的单：agent 自己就能跑到「出凭证」，钱仍要验收才划转。"""
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "1")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    seller = f"rt-food-{uuid.uuid4().hex[:6]}"
    await _p1_merchant(db_session, agent_id=seller, industry="food_delivery", capability="order_food")

    acct = Account.create()
    identity = f"ord-ok-{uuid.uuid4().hex[:8]}"
    await _save_policy(
        client, identity=identity, permissions=BASE_PERMS, single_limit=12.0, daily_limit=12.0
    )
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=BASE_PERMS,
        single_limit=12.0,
        daily_limit=12.0,
    )
    capture = _matched_capture(
        scene_id="food_delivery", amount=12.0, buyer=identity, seller=seller
    )
    resp = await client.post(
        "/runtime/place-order",
        headers={"X-Karma-Runtime-Key": rt},
        json={
            "requirement_text": "帮我点一份披萨外卖 12 USDC",
            "amount": 12.0,
            "seller_identity_id": seller,
            "negotiate_a2a": False,
            "important_fields_capture_id": capture,
            "client_nonce": uuid.uuid4().hex,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["awaiting_owner_confirmation"] is False
    assert body["voucher_id"]
    assert body["seller_identity_id"] == seller

    # 出了凭证才算动用额度：日上限 12 已经用光，同一天再来一单就该被拦住。
    again = await client.post(
        "/runtime/place-order",
        headers={"X-Karma-Runtime-Key": rt},
        json={
            "requirement_text": "帮我点一份披萨外卖 12 USDC",
            "amount": 12.0,
            "seller_identity_id": seller,
            "negotiate_a2a": False,
            "important_fields_capture_id": _matched_capture(
                scene_id="food_delivery", amount=12.0, buyer=identity, seller=seller
            ),
            "client_nonce": uuid.uuid4().hex,
        },
    )
    assert again.status_code == 403, again.text


@pytest.mark.asyncio
async def test_place_order_above_the_auto_budget_waits_for_the_owner(
    client: AsyncClient, db_session, monkeypatch
):
    """超了自动额度的单：不出凭证、不扣额度，等主人在操作台点确认。"""
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    monkeypatch.setenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "1")
    monkeypatch.setenv("A2A_REGISTRY_URL", "")
    seller = f"rt-food2-{uuid.uuid4().hex[:6]}"
    await _p1_merchant(db_session, agent_id=seller, industry="food_delivery", capability="order_food")

    acct = Account.create()
    identity = f"ord-wait-{uuid.uuid4().hex[:8]}"
    await _save_policy(
        client,
        identity=identity,
        permissions=BASE_PERMS,
        single_limit=20.0,
        daily_limit=40.0,
        high_risk_mode="always",
    )
    rt = await _mint(
        client,
        account=acct,
        karma_identity_id=identity,
        permissions=BASE_PERMS,
        single_limit=20.0,
        daily_limit=40.0,
    )
    capture = _matched_capture(
        scene_id="food_delivery", amount=20.0, buyer=identity, seller=seller
    )
    payload = {
        "requirement_text": "帮我点一份披萨外卖 20 USDC",
        "amount": 20.0,
        "seller_identity_id": seller,
        "negotiate_a2a": False,
        "important_fields_capture_id": capture,
        "client_nonce": uuid.uuid4().hex,
    }
    first = await client.post(
        "/runtime/place-order", headers={"X-Karma-Runtime-Key": rt}, json=payload
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "awaiting_owner_confirmation"
    assert body["awaiting_owner_confirmation"] is True
    assert not body.get("voucher_id")
    session_id = body["confirmation"]["session_id"]

    # 确认区看得到这一笔（只有本人看得到）。
    pending = await client.get(
        "/v1/confirmations/pending",
        params={"identity_id": identity},
        headers={"X-Karma-Identity-Id": identity},
    )
    assert pending.status_code == 200, pending.text
    assert session_id in [s["session_id"] for s in pending.json()["pending"]]

    stranger = await client.get(
        "/v1/confirmations/pending",
        params={"identity_id": f"someone-{uuid.uuid4().hex[:6]}"},
        headers={"X-Karma-Identity-Id": f"someone-{uuid.uuid4().hex[:6]}"},
    )
    if stranger.status_code == 200:
        assert session_id not in [s["session_id"] for s in stranger.json()["pending"]]

    # 主人点头 → agent 带 session 重试 → 出凭证。
    decided = await client.post(
        f"/v1/confirmations/sessions/{session_id}/decide",
        headers={"X-Karma-Identity-Id": identity},
        json={"confirm": True, "actor_agent_id": identity},
    )
    assert decided.status_code == 200, decided.text

    payload["client_nonce"] = uuid.uuid4().hex
    payload["confirmation_session_id"] = session_id
    second = await client.post(
        "/runtime/place-order", headers={"X-Karma-Runtime-Key": rt}, json=payload
    )
    assert second.status_code == 200, second.text
    assert second.json()["voucher_id"]
