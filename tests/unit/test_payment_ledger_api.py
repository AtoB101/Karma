"""收付中心：一个身份一张台账（后端行为）。

前端的「总览 / 收入明细 / 支出明细 / 确认区 / 争议区」全部由
GET /v1/payments/ledger 画出来，所以这里把口径钉死：

- 支出 = 我是付款方的单；收入 = 我是收款方的单。
- 只有真金已结算的才算「已收 / 已付」；执行中/待确认的是在途与待收款。
- 子身份视角按档案 id 归属，付款方一侧和收款方一侧都算，且只看得到自己的。
- 别人的身份、别人的档案，一律拒绝。
"""
from __future__ import annotations

import pytest

from db.models.orm import (
    AllowanceCommitModel,
    EscrowBindingModel,
    IdentityRoleProfile,
    SettlementModel,
)

BUYER = "kid_ledger_buyer"
SELLER = "kid_ledger_seller"


async def _profile(db, owner: str, name: str) -> IdentityRoleProfile:
    row = IdentityRoleProfile(
        owner_identity_id=owner, class_="individual", display_name=name
    )
    db.add(row)
    await db.flush()
    return row


async def _settlement(
    db,
    task_id: str,
    buyer: str,
    worker: str | None = None,
    *,
    amount: float = 10.0,
    status: str = "in_progress",
    profile_id: str | None = None,
    worker_profile_id: str | None = None,
    released: float | None = None,
    refunded: float | None = None,
) -> SettlementModel:
    row = SettlementModel(
        task_id=task_id,
        escrow_amount=amount,
        currency="USDC",
        status=status,
        client_agent_id=buyer,
        worker_agent_id=worker,
        profile_id=profile_id,
        worker_profile_id=worker_profile_id,
        released_amount=released,
        refunded_amount=refunded,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed(db):
    work = await _profile(db, BUYER, "工作助理")
    life = await _profile(db, BUYER, "生活助理")
    await _settlement(
        db, "task-buy-1", BUYER, SELLER, amount=20.0, status="delivered",
        profile_id=work.profile_id,
    )
    await _settlement(
        db, "task-buy-2", BUYER, SELLER, amount=5.0, status="settled",
        profile_id=life.profile_id, released=5.0,
    )
    await _settlement(
        db, "task-sell-1", "kid_ledger_other", BUYER, amount=7.0, status="settled",
        released=7.0, worker_profile_id=work.profile_id,
    )
    await _settlement(
        db, "task-dispute-1", BUYER, "kid_ledger_other", amount=9.0, status="disputed",
        refunded=0.0,
    )
    return work, life


@pytest.mark.asyncio
async def test_master_view_separates_income_expense_confirm_and_dispute(client, db_session):
    await _seed(db_session)

    r = await client.get("/v1/payments/ledger", headers={"X-Karma-Identity-Id": BUYER})
    assert r.status_code == 200, r.text
    body = r.json()
    summary = body["summary"]

    assert summary["counts"]["expense"] == 3, "三单我是付款方"
    assert summary["counts"]["income"] == 1, "一单我是收款方"
    assert summary["income_usdc"] == 7.0, "只有已结算的才算已收"
    assert summary["expense_usdc"] == 5.0, "只有已结算的才算已付"
    assert summary["in_flight_usdc"] == 29.0, "执行中 + 争议中的付款占用"
    assert summary["counts"]["confirm"] == 1, "已交付待确认进确认区"
    assert summary["counts"]["dispute"] == 1, "争议中进争议区"

    assert [e["ref_id"] for e in body["confirmation"]] == ["task-buy-1"]
    assert [e["ref_id"] for e in body["disputes"]] == ["task-dispute-1"]

    by_id = {e["ref_id"]: e for e in body["entries"]}
    assert by_id["task-buy-1"]["direction"] == "out"
    assert by_id["task-buy-1"]["phase"] == "confirm"
    assert by_id["task-sell-1"]["direction"] == "in"
    assert by_id["task-sell-1"]["phase"] == "closed"
    assert by_id["task-sell-1"]["settled_usdc"] == 7.0
    assert by_id["task-dispute-1"]["phase"] == "dispute"


@pytest.mark.asyncio
async def test_sub_identity_scope_keeps_both_sides_of_its_own_money(client, db_session):
    work, life = await _seed(db_session)

    r = await client.get(
        "/v1/payments/ledger",
        params={"profile_id": work.profile_id},
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    refs = sorted(e["ref_id"] for e in body["entries"])
    assert refs == ["task-buy-1", "task-sell-1"], "只认这个子身份名下的单"
    assert body["summary"]["counts"]["income"] == 1
    assert body["summary"]["counts"]["expense"] == 1

    r2 = await client.get(
        "/v1/payments/ledger",
        params={"profile_id": life.profile_id},
        headers={"X-Karma-Identity-Id": BUYER},
    )
    refs2 = [e["ref_id"] for e in r2.json()["entries"]]
    assert refs2 == ["task-buy-2"], "另一个子身份的单不能混进来"


@pytest.mark.asyncio
async def test_ledger_refuses_other_identities_and_foreign_profiles(client, db_session):
    work, _ = await _seed(db_session)

    denied = await client.get(
        "/v1/payments/ledger",
        params={"identity_id": SELLER},
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert denied.status_code == 403, denied.text

    foreign = await client.get(
        "/v1/payments/ledger",
        params={"profile_id": work.profile_id},
        headers={"X-Karma-Identity-Id": SELLER},
    )
    assert foreign.status_code in (403, 404), foreign.text


@pytest.mark.asyncio
async def test_entry_detail_carries_history_and_stays_inside_the_identity(client, db_session):
    await _seed(db_session)

    r = await client.get(
        "/v1/payments/entries/settlement/task-buy-2",
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"]["ref_id"] == "task-buy-2"
    assert body["entry"]["settled_usdc"] == 5.0
    assert isinstance(body["history"], list)

    # SELLER 是 task-buy-2 的收款方，看得到；换成和他无关的那一单就该被拒。
    nope = await client.get(
        "/v1/payments/entries/settlement/task-dispute-1",
        headers={"X-Karma-Identity-Id": SELLER},
    )
    assert nope.status_code == 403, nope.text


@pytest.mark.asyncio
async def test_locks_show_up_as_pledges_and_have_their_own_detail(client, db_session):
    db_session.add(
        AllowanceCommitModel(
            bill_id="41",
            identity_id=BUYER,
            wallet_address="0xabc",
            chain_id=11155111,
            contract_address="0xcontract",
            token_address="0xusdc",
            operator="0xoperator",
            amount_wei="15000000",
            amount_usdc=15.0,
            spent_usdc=0.0,
            reserved_usdc=0.0,
            backed=True,
            commit_tx_hash="0xdeadbeef",
            state="open",
        )
    )
    await db_session.flush()

    r = await client.get("/v1/payments/ledger", headers={"X-Karma-Identity-Id": BUYER})
    body = r.json()
    assert body["summary"]["locked_usdc"] == 15.0
    lock = next(e for e in body["entries"] if e["kind"] == "lock")
    assert lock["phase"] == "active"
    assert lock["amount_usdc"] == 15.0

    detail = await client.get(
        "/v1/payments/entries/lock/41", headers={"X-Karma-Identity-Id": BUYER}
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["entry"]["detail"]["wallet_address"] == "0xabc"

    # bill_id 是字符串主键：带前导零的单号不能被当成数字去查（线上 Postgres 会直接报错）。
    db_session.add(
        AllowanceCommitModel(
            bill_id="007",
            identity_id=BUYER,
            wallet_address="0xabc",
            chain_id=11155111,
            contract_address="0xcontract",
            token_address="0xusdc",
            operator="0xoperator",
            amount_wei="1000000",
            amount_usdc=1.0,
            spent_usdc=0.0,
            reserved_usdc=0.0,
            backed=True,
            commit_tx_hash="0xfeed0007",
            state="open",
        )
    )
    await db_session.flush()
    zero = await client.get(
        "/v1/payments/entries/lock/007", headers={"X-Karma-Identity-Id": BUYER}
    )
    assert zero.status_code == 200, zero.text
    assert zero.json()["entry"]["ref_id"] == "007"


@pytest.mark.asyncio
async def test_role_profile_ledger_endpoint_exists_for_the_bills_page(client, db_session):
    """账单页调 /v1/identity/role-profiles/{id}/ledger：字段名保持历史兼容，私有档案要授权。"""
    work, _ = await _seed(db_session)

    r = await client.get(
        f"/v1/identity/role-profiles/{work.profile_id}/ledger",
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_id"] == work.profile_id
    assert [t["task_id"] for t in body["transactions"]] == ["task-buy-1"]
    first = body["transactions"][0]
    for key in ("task_id", "settlement_id", "currency", "escrow_amount", "status", "created_at"):
        assert key in first, f"账单页要的字段缺了 {key}"

    # 披露语义：私有档案对非 owner 默认拒绝，只有被明确披露才放行。
    work.visibility = "private"
    await db_session.flush()
    denied = await client.get(
        f"/v1/identity/role-profiles/{work.profile_id}/ledger",
        headers={"X-Karma-Identity-Id": SELLER},
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.asyncio
async def test_payee_side_profile_binding_is_optional_and_additive(client, db_session):
    """没有收款方档案归属的老单，照样出现在主身份视角里。"""
    db_session.add(
        EscrowBindingModel(
            binding_id="7001",
            buyer_identity_id=BUYER,
            seller_identity_id=SELLER,
            buyer_bill_id="1",
            seller_bill_id="2",
            scope_hash="0x00",
            task_id="binding-task-1",
            amount_usdc=30.0,
            stake_usdc=9.0,
            state="settled",
        )
    )
    await db_session.flush()

    body = (
        await client.get("/v1/payments/ledger", headers={"X-Karma-Identity-Id": BUYER})
    ).json()
    binding = next(e for e in body["entries"] if e["kind"] == "binding")
    assert binding["direction"] == "out"
    assert binding["phase"] == "closed"
    assert binding["settled_usdc"] == 30.0
    assert binding["profile_id"] is None

    seller_view = (
        await client.get("/v1/payments/ledger", headers={"X-Karma-Identity-Id": SELLER})
    ).json()
    assert seller_view["summary"]["income_usdc"] == 30.0
