"""④-B2：结算回滚赔付台账 + ``/overturn`` 接上赔付。

链上没有「把钱倒回来」的原语（``SETTLED`` / ``REFUNDED`` 是终局），所以「裁决被推翻」
的后果记成**一笔债** —— ``settlement_reversals``。这里钉的是钱那一半的硬规矩：

* 受害方与欠款额由后端**推定**，调用方口述只在「与推定一致」时才被接受（否则 409）；
* 钱没动（档 A）不建账；链上读不到一律 409 且**零写入**（fail-closed）；
* 台账幂等：同一案件对同一受害方只有一条账；
* ``paid_amount`` 只在链上 tx **回链核过**之后才增加，同一笔 tx 不重复计。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from db.models.orm import (
    ArbitrationAssignmentModel,
    ArbitrationCaseModel,
    EscrowBindingModel,
    IdentityProfileModel,
    IdentityRoleProfile,
    TaskContractModel,
)
from decentralized_verifier.models import BondSlash, SettlementReversal

BUYER = "a2a-buyer"
SELLER = "a2a-seller"
BUYER_WALLET = "0xD91acb5DE9ECc6b08eeBdC24e88A204619A17Cec"
SELLER_WALLET = "0x9C479392C27ac5f44cBF50ceB2f099aDD665475f"


def _stub_chain(monkeypatch, *, state=4, unreadable=False, self_dealing=None, funds_trace_error=None):
    """把「问链」整段换成替身：用例里没有 RPC，真读链必然是 None。

    默认 **档 C**（``slashed``）：钱已经动了，进赔付通道。
    """
    from services.chain import escrow_settlement
    from services.chain import funds_trace as funds_trace_module

    async def _snapshot(binding):
        if unreadable:
            return None
        return {
            "state": state,
            "buyer_confirmed": False,
            "confirmed_at": None,
            "slash_armed": True,
            "settle_after": None,
            "closed_at": None,
        }

    async def _detect(db, *, buyer_identity_id=None, seller_identity_id=None, **_kw):
        return self_dealing

    monkeypatch.setattr(escrow_settlement, "chain_snapshot", _snapshot)
    monkeypatch.setattr(escrow_settlement, "detect_self_dealing", _detect)

    if funds_trace_error is None:
        async def _trace_ok(db, *, task_id, stage):
            return None

        monkeypatch.setattr(funds_trace_module, "assert_funds_traceable", _trace_ok)
    else:
        async def _trace_boom(db, *, task_id, stage):
            raise escrow_settlement.EscrowSettlementError(409, funds_trace_error)

        monkeypatch.setattr(funds_trace_module, "assert_funds_traceable", _trace_boom)


def _bench_settings(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "arbitration_slash_multiple", 2.0)
    monkeypatch.setattr(settings, "arbitration_fee_bps", 150.0)
    monkeypatch.setattr(settings, "arbitration_fee_min_usdc", 0.5)
    monkeypatch.setattr(settings, "arbitration_fee_max_usdc", 100.0)


async def _seed_case(db, *, case_id, task_id, outcome="buyer_wins", escrow_amount=3.0):
    db.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id=BUYER,
            title="b2 reversal case",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=escrow_amount,
            deadline_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.add(
        ArbitrationCaseModel(
            case_id=case_id,
            task_id=task_id,
            opened_by=BUYER,
            status="executed",
            required_arbitrators=3,
            decided_outcome=outcome,
        )
    )
    await db.commit()


async def _seed_binding(
    db, *, task_id, binding_id="8", state="slashed", amount=3.0, stake=0.9
):
    db.add(
        EscrowBindingModel(
            binding_id=binding_id,
            buyer_identity_id=BUYER,
            seller_identity_id=SELLER,
            buyer_bill_id="bill-buyer",
            seller_bill_id="bill-seller",
            contract_address="0x2C9911F58CfDb5f097926c4aC104108f4f49743b",
            scope_hash="0x" + "ab" * 32,
            task_id=task_id,
            amount_usdc=amount,
            stake_usdc=stake,
            state=state,
        )
    )
    await db.commit()


async def _seed_wallets(db):
    db.add(
        IdentityProfileModel(
            identity_id=BUYER, display_id="d-buyer", bound_wallet_address=BUYER_WALLET
        )
    )
    db.add(
        IdentityProfileModel(
            identity_id=SELLER, display_id="d-seller", bound_wallet_address=SELLER_WALLET
        )
    )
    await db.commit()


async def _seed_bench(db, *, case_id, subject_id="arb-staked", stake=10.0):
    db.add(
        ArbitrationAssignmentModel(case_id=case_id, arbitrator_identity_id=subject_id)
    )
    db.add(
        IdentityRoleProfile(
            owner_identity_id=subject_id,
            class_="arbitrator",
            kyc_status="verified",
            stake_amount=stake,
        )
    )
    await db.commit()


async def _count(db, model) -> int:
    return len((await db.execute(select(model))).scalars().all())


async def _reversal_rows(db):
    return (await db.execute(select(SettlementReversal))).scalars().all()


async def _slash_rows(db):
    return (await db.execute(select(BondSlash))).scalars().all()


# ── 档 C：钱动了 → 建账 + 推定受害方 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_overturn_records_reversal_and_presumes_the_seller(
    client_sec, db_session, monkeypatch
):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=4)  # slashed
    await _seed_case(db_session, case_id="case-b2-1", task_id="task-b2-1")
    await _seed_binding(db_session, task_id="task-b2-1")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-1")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-1/overturn", json={"reason": "appeal upheld"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["settlement_reversal"] == "recorded"
    detail = body["settlement_reversal_detail"]
    # buyer_wins 被推翻 → 受害方是**卖方**；欠款 = 货款 3 + 被误划的质押 0.9（全额口径）。
    assert detail["victim_identity_id"] == SELLER
    assert detail["victim_wallet"] == SELLER_WALLET
    assert detail["owed_amount"] == 3.9
    assert detail["paid_amount"] == 0.0
    assert detail["funding_source"] == "bench_bond", "金库内先出被推翻那一庭的质押"
    assert detail["status"] == "pending"

    rows = await _reversal_rows(db_session)
    assert len(rows) == 1
    assert rows[0].case_id == "case-b2-1"
    assert rows[0].binding_id == "8"
    assert rows[0].task_id == "task-b2-1"

    # ④-B1 那条真链通路也要拿到**推定**出来的受害方钱包（80% 才真落到受损方身上）。
    slashes = await _slash_rows(db_session)
    assert len(slashes) == 1
    assert slashes[0].amount == 1.0  # 3.0 × 150bps → 夹到下限 0.5，×2 倍数
    assert slashes[0].victim_wallet_address == SELLER_WALLET
    assert slashes[0].victim_identity_id == SELLER
    assert slashes[0].victim_amount == 0.8
    assert slashes[0].pool_amount == 0.2


@pytest.mark.asyncio
async def test_overturn_is_idempotent_per_case_and_victim(
    client_sec, db_session, monkeypatch
):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=4)
    await _seed_case(db_session, case_id="case-b2-2", task_id="task-b2-2")
    await _seed_binding(db_session, task_id="task-b2-2")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-2")

    first = await client_sec.post(
        "/v1/arbitration/cases/case-b2-2/overturn", json={"reason": "again"}
    )
    second = await client_sec.post(
        "/v1/arbitration/cases/case-b2-2/overturn", json={"reason": "again"}
    )
    assert first.status_code == 200 and second.status_code == 200
    assert (
        first.json()["settlement_reversal_detail"]["reversal_id"]
        == second.json()["settlement_reversal_detail"]["reversal_id"]
    )
    assert len(await _reversal_rows(db_session)) == 1, "同一案件只允许一条账"
    assert len(await _slash_rows(db_session)) == 1, "重复推翻不重复罚、也不重复计债"


# ── 方向：seller_wins 被推翻 → 受害方是买方 ─────────────────────────────────


@pytest.mark.asyncio
async def test_seller_wins_presumes_the_buyer(client_sec, db_session, monkeypatch):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=3)  # settled：货款已经放给卖方
    await _seed_case(
        db_session, case_id="case-b2-3", task_id="task-b2-3", outcome="seller_wins"
    )
    await _seed_binding(db_session, task_id="task-b2-3", state="settled")
    await _seed_wallets(db_session)

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-3/overturn", json={"reason": "misjudged"}
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["settlement_reversal_detail"]
    assert detail["victim_identity_id"] == BUYER
    assert detail["victim_wallet"] == BUYER_WALLET
    # 这一档没有「被误划的质押」，欠款就是货款本身。
    assert detail["owed_amount"] == 3.0
    assert detail["funding_source"] == "slash_pool", "没有在庭质押承诺 → 记金库罚没池"


# ── 分档 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bucket_not_moved_records_nothing(client_sec, db_session, monkeypatch):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=1)  # active：钱没动
    await _seed_case(db_session, case_id="case-b2-4", task_id="task-b2-4")
    await _seed_binding(db_session, task_id="task-b2-4", state="active")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-4")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-4/overturn", json={"reason": "window still open"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["settlement_reversal"] == "not_moved"
    assert body["settlement_reversal_detail"] is None
    assert await _count(db_session, SettlementReversal) == 0, "钱没动，不谈回滚"
    # 但庭还是罚了（罚的是判错的人），而且受害方钱包已经推定出来。
    slashes = await _slash_rows(db_session)
    assert len(slashes) == 1
    assert slashes[0].victim_wallet_address == SELLER_WALLET


@pytest.mark.asyncio
async def test_bucket_in_window_records_pending(client_sec, db_session, monkeypatch):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=2)  # finalizing：窗口里还没走
    await _seed_case(db_session, case_id="case-b2-5", task_id="task-b2-5")
    await _seed_binding(db_session, task_id="task-b2-5", state="finalizing")
    await _seed_wallets(db_session)

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-5/overturn", json={"reason": "in window"}
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["settlement_reversal_detail"]
    assert detail["status"] == "pending"
    assert "落定" in (detail["basis"] or ""), "要如实注记「等落定再算实付」"
    rows = await _reversal_rows(db_session)
    assert len(rows) == 1
    # 窗口里质押还没被划，不算欠款。
    assert rows[0].owed_amount == 3.0


# ── fail-closed ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_unreadable_is_409_and_writes_nothing(
    client_sec, db_session, monkeypatch
):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, unreadable=True)
    await _seed_case(db_session, case_id="case-b2-6", task_id="task-b2-6")
    await _seed_binding(db_session, task_id="task-b2-6")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-6")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-6/overturn", json={"reason": "rpc down"}
    )
    assert resp.status_code == 409, resp.text
    assert await _count(db_session, SettlementReversal) == 0
    assert await _count(db_session, BondSlash) == 0, "链上读不到时连罚没也不许写"


@pytest.mark.asyncio
async def test_caller_cannot_point_the_payout_at_another_wallet(
    client_sec, db_session, monkeypatch
):
    """最贵的一个错误：把赔款指到别人的钱包上。"""
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=4)
    await _seed_case(db_session, case_id="case-b2-7", task_id="task-b2-7")
    await _seed_binding(db_session, task_id="task-b2-7")
    await _seed_wallets(db_session)

    other = "0x" + "fa" * 20
    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-7/overturn",
        json={"reason": "gimme", "victim_wallet_address": other},
    )
    assert resp.status_code == 409, resp.text
    assert await _count(db_session, SettlementReversal) == 0
    assert await _count(db_session, BondSlash) == 0, "指认不一致：一条账都不写"

    resp2 = await client_sec.post(
        "/v1/arbitration/cases/case-b2-7/overturn",
        json={"reason": "gimme", "victim_identity_id": "someone-else"},
    )
    assert resp2.status_code == 409, resp2.text

    # 与推定一致时照收（不因为「传了就拒」而把正常调用也挡掉）。
    ok = await client_sec.post(
        "/v1/arbitration/cases/case-b2-7/overturn",
        json={"reason": "ok", "victim_wallet_address": SELLER_WALLET, "victim_identity_id": SELLER},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["settlement_reversal_detail"]["victim_wallet"] == SELLER_WALLET


@pytest.mark.asyncio
async def test_funds_trace_failure_is_409_and_writes_nothing(
    client_sec, db_session, monkeypatch
):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=4, funds_trace_error="这一单的资金链路对不上")
    await _seed_case(db_session, case_id="case-b2-8", task_id="task-b2-8")
    await _seed_binding(db_session, task_id="task-b2-8")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-8")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-8/overturn", json={"reason": "trace fails"}
    )
    assert resp.status_code == 409, resp.text
    assert await _count(db_session, SettlementReversal) == 0
    assert await _count(db_session, BondSlash) == 0, "资金链路对不上：钱一分都不动"


@pytest.mark.asyncio
async def test_self_dealing_skips_compensation(client_sec, db_session, monkeypatch):
    _bench_settings(monkeypatch)
    _stub_chain(
        monkeypatch,
        state=4,
        self_dealing=("same_owner_identity", "main-1", "自成交不赔"),
    )
    await _seed_case(db_session, case_id="case-b2-9", task_id="task-b2-9")
    await _seed_binding(db_session, task_id="task-b2-9")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-9")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-9/overturn", json={"reason": "self deal"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settlement_reversal"] == "self_dealing"
    assert await _count(db_session, SettlementReversal) == 0, "自成交不进赔付"


@pytest.mark.asyncio
async def test_partial_outcome_is_409(client_sec, db_session, monkeypatch):
    """用户裁定：细则未定期间 partial **一律 409**，不猜一个比例出来。"""
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=4)
    await _seed_case(
        db_session, case_id="case-b2-10", task_id="task-b2-10", outcome="partial"
    )
    await _seed_binding(db_session, task_id="task-b2-10")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-10")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b2-10/overturn", json={"reason": "partial"}
    )
    assert resp.status_code == 409, resp.text
    assert await _count(db_session, SettlementReversal) == 0
    assert await _count(db_session, BondSlash) == 0

    # 没有链上绑定的 partial 也一样：推定这关挡不住「回滚金额算不出来」这件事，
    # 所以这一档**在进推定之前**就得拒（否则它会从旁边绕过去）。
    await _seed_case(
        db_session, case_id="case-b2-10b", task_id="task-b2-10b", outcome="partial"
    )
    await _seed_bench(db_session, case_id="case-b2-10b")
    bare = await client_sec.post(
        "/v1/arbitration/cases/case-b2-10b/overturn", json={"reason": "partial, no binding"}
    )
    assert bare.status_code == 409, bare.text
    assert await _count(db_session, SettlementReversal) == 0
    assert await _count(db_session, BondSlash) == 0


# ── paid_amount：只有「已 settled + 回链核过」才动 ─────────────────────────


@pytest.mark.asyncio
async def test_paid_amount_only_moves_with_a_verified_chain_tx(db_session):
    from services import bond_slash as bond_slash_service
    from services import settlement_reversal as reversal_service

    victim_wallet = SELLER_WALLET
    reversal, _ = await reversal_service.record_reversal(
        db_session,
        case_id="case-b2-11",
        task_id="task-b2-11",
        binding_id="8",
        victim_identity_id=SELLER,
        victim_wallet=victim_wallet,
        owed_amount=3.9,
        funding_source=reversal_service.FUNDING_BENCH_BOND,
    )
    slash, _ = await bond_slash_service.record_slash(
        db_session,
        subject_kind=bond_slash_service.SUBJECT_ARBITRATOR_ROLE,
        subject_id="arb-1",
        wallet_address="0x" + "11" * 20,
        victim_wallet_address=victim_wallet,
        victim_identity_id=SELLER,
        source_kind=bond_slash_service.SOURCE_ARBITRATION_OVERTURN,
        source_id="case-b2-11",
        amount=1.0,
    )
    await db_session.flush()

    proof = {"tx_hash": "0xabc", "victim": victim_wallet, "amount_usdc": 1.0}

    # 1) 还没 settled：不加（而且这是编程错误，直接拒）。
    with pytest.raises(reversal_service.SettlementReversalError):
        await reversal_service.credit_from_settled_slash(
            db_session, slash=slash, chain_proof=proof
        )
    assert reversal.paid_amount == 0.0

    # 2) **submitted**（有 tx hash 但还没落定）→ 也不加：只有 settled 才算数。
    await bond_slash_service.settle_slash(
        db_session,
        slash_id=slash.id,
        status=bond_slash_service.STATUS_SUBMITTED,
        tx_hash="0xabc",
    )
    with pytest.raises(reversal_service.SettlementReversalError):
        await reversal_service.credit_from_settled_slash(
            db_session, slash=slash, chain_proof=proof
        )
    assert reversal.paid_amount == 0.0

    # 3) settled 了、但没有回链核过 → 也不加。
    await bond_slash_service.settle_slash(
        db_session,
        slash_id=slash.id,
        status=bond_slash_service.STATUS_SETTLED,
        tx_hash="0xabc",
    )
    with pytest.raises(reversal_service.SettlementReversalError):
        await reversal_service.credit_from_settled_slash(
            db_session, slash=slash, chain_proof={}
        )
    assert reversal.paid_amount == 0.0

    # 4) 核过 → 只加这一笔罚没里属于受害方的份额（80%）。
    await reversal_service.credit_from_settled_slash(
        db_session, slash=slash, chain_proof=proof
    )
    assert reversal.paid_amount == 0.8
    assert reversal.status == reversal_service.STATUS_SUBMITTED, "还没赔完"

    # 5) 同一笔 tx 重复回写 → 不再记一次。
    await reversal_service.credit_from_settled_slash(
        db_session, slash=slash, chain_proof=proof
    )
    assert reversal.paid_amount == 0.8

    # 6) 第二笔（别的仲裁员）核过之后继续累，赔满就 settled。
    slash2, _ = await bond_slash_service.record_slash(
        db_session,
        subject_kind=bond_slash_service.SUBJECT_ARBITRATOR_ROLE,
        subject_id="arb-2",
        wallet_address="0x" + "22" * 20,
        victim_wallet_address=victim_wallet,
        victim_identity_id=SELLER,
        source_kind=bond_slash_service.SOURCE_ARBITRATION_OVERTURN,
        source_id="case-b2-11",
        amount=10.0,
    )
    await bond_slash_service.settle_slash(
        db_session,
        slash_id=slash2.id,
        status=bond_slash_service.STATUS_SETTLED,
        tx_hash="0xdef",
    )
    await reversal_service.credit_from_settled_slash(
        db_session,
        slash=slash2,
        chain_proof={"tx_hash": "0xdef", "victim": victim_wallet, "amount_usdc": 10.0},
    )
    # 8.0 的份额也不能把欠款赔过头：封顶在 owed。
    assert reversal.paid_amount == 3.9
    assert reversal.status == reversal_service.STATUS_SETTLED
    assert reversal.settled_at is not None


@pytest.mark.asyncio
async def test_settle_reversal_refuses_settled_without_tx(db_session):
    from services import settlement_reversal as reversal_service

    row, _ = await reversal_service.record_reversal(
        db_session,
        case_id="case-b2-12",
        task_id="task-b2-12",
        binding_id=None,
        victim_identity_id=SELLER,
        victim_wallet=SELLER_WALLET,
        owed_amount=1.0,
        funding_source=reversal_service.FUNDING_SLASH_POOL,
    )
    with pytest.raises(reversal_service.SettlementReversalError):
        await reversal_service.settle_reversal(
            db_session, reversal_id=row.reversal_id, status="settled"
        )
    updated = await reversal_service.settle_reversal(
        db_session, reversal_id=row.reversal_id, status="settled", tx_hash="0x1"
    )
    assert updated.status == "settled"


# ── 纯函数 / 守卫 ─────────────────────────────────────────────────────────


def test_chain_state_constants_match_allowance_escrow():
    """链上状态映射不许两边各写一份然后漂移（一处判据）。"""
    from services import settlement_reversal as reversal_service
    from services.chain.allowance_escrow import BINDING_STATE

    assert reversal_service.CHAIN_ACTIVE == 1 and BINDING_STATE[1] == "active"
    assert reversal_service.CHAIN_FINALIZING == 2 and BINDING_STATE[2] == "finalizing"
    assert reversal_service.CHAIN_SETTLED == 3 and BINDING_STATE[3] == "settled"
    assert reversal_service.CHAIN_SLASHED == 4 and BINDING_STATE[4] == "slashed"
    assert reversal_service.CHAIN_CANCELLED == 5 and BINDING_STATE[5] == "cancelled"
    assert reversal_service.CHAIN_DISPUTED == 6 and BINDING_STATE[6] == "disputed"
    assert reversal_service.bucket_of_chain_state(1) == "not_moved"
    assert reversal_service.bucket_of_chain_state(6) == "not_moved"
    assert reversal_service.bucket_of_chain_state(2) == "in_window"
    assert reversal_service.bucket_of_chain_state(3) == "moved"
    assert reversal_service.bucket_of_chain_state(4) == "moved"
    assert reversal_service.bucket_of_chain_state(None) == "unknown"
    assert reversal_service.bucket_of_chain_state("nonsense") == "unknown"
    assert reversal_service.bucket_of_chain_state(99) == "unknown"


def test_presume_victim_rejects_partial_and_unknown_outcomes():
    from services import settlement_reversal as reversal_service

    binding = EscrowBindingModel(
        binding_id="9",
        buyer_identity_id=BUYER,
        seller_identity_id=SELLER,
        buyer_bill_id="b",
        seller_bill_id="s",
        contract_address="0x" + "11" * 20,
        scope_hash="0x" + "ab" * 32,
        task_id="t",
        amount_usdc=3.0,
        stake_usdc=0.9,
        state="slashed",
    )
    with pytest.raises(reversal_service.SettlementReversalError):
        reversal_service.presume_victim(
            decided_outcome="partial", binding=binding, chain_state=4
        )
    with pytest.raises(reversal_service.SettlementReversalError):
        reversal_service.presume_victim(
            decided_outcome=None, binding=binding, chain_state=4
        )
    presumed = reversal_service.presume_victim(
        decided_outcome="buyer_wins", binding=binding, chain_state=4
    )
    assert (presumed.identity_id, presumed.owed_amount) == (SELLER, 3.9)
    # 链上没被划（档 A/B）：质押不计入欠款，不虚报。
    assert reversal_service.presume_victim(
        decided_outcome="buyer_wins", binding=binding, chain_state=2
    ).owed_amount == 3.0


def test_default_funding_source_is_always_the_vault():
    """用户裁定：一律由金库出账 —— 不写平台债。"""
    from services import settlement_reversal as reversal_service

    assert reversal_service.default_funding_source(bench_bonded=True) == "bench_bond"
    assert reversal_service.default_funding_source(bench_bonded=False) == "slash_pool"
    assert "platform_debt" not in (
        reversal_service.FUNDING_BENCH_BOND,
        reversal_service.FUNDING_SLASH_POOL,
    )


# ── 只读 API ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reversals_api_lists_the_ledger_and_requires_admin(
    client, client_sec, db_session, monkeypatch
):
    _bench_settings(monkeypatch)
    _stub_chain(monkeypatch, state=4)
    await _seed_case(db_session, case_id="case-b2-13", task_id="task-b2-13")
    await _seed_binding(db_session, task_id="task-b2-13")
    await _seed_wallets(db_session)
    await _seed_bench(db_session, case_id="case-b2-13")
    await client_sec.post(
        "/v1/arbitration/cases/case-b2-13/overturn", json={"reason": "list me"}
    )

    listed = await client_sec.get("/v1/arbitration/reversals")
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["outstanding_total_usdc"] == 3.9
    assert payload["reversals"][0]["case_id"] == "case-b2-13"
    assert payload["reversals"][0]["status"] == "pending"

    filtered = await client_sec.get("/v1/arbitration/reversals?case_id=case-b2-13")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert (await client_sec.get("/v1/arbitration/reversals?case_id=nope")).json()["total"] == 0

    no_creds = await client.get("/v1/arbitration/reversals")
    assert no_creds.status_code in (401, 403), no_creds.text
