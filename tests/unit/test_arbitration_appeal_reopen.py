"""④-A3 窗口内上诉：把「已下发、还没放款」的裁决打回去重审，零链上动作。

④-A1 把放款推迟到窗口到点，但窗口里当时**没有任何入口** —— 空转。
这里钉住 ④-A3 的入口与它的边界：

* 窗口关着 / 窗口已过 / 不是当事人 -> 拒绝，且案件一字不动；
* 窗口内上诉：案件回 ``voting``、``execute_after`` 清空、链上一步不发、结算一步不动；
* 链上已经过了不归点（``finalizing``/``settled``）-> 拒绝（打回也倒不回钱）；
* 票按**轮次**算 —— 上一轮的票不能把新结果重新「投」出来（最容易写错的一条）；
* 限次（``ARBITRATION_MAX_APPEALS``）防无限拖期。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from config.settings import settings
from core.schemas import TaskStatus
from db.models.orm import (
    ArbitrationAssignmentModel,
    ArbitrationCaseEventModel,
    ArbitrationCaseModel,
    ArbitrationPoolMemberModel,
    ArbitrationVoteModel,
    SettlementModel,
    TaskContractModel,
)

BUYER = "buyer-a3"
SELLER = "seller-a3"
ARBS = ["arb-a3-1", "arb-a3-2", "arb-a3-3"]


async def _seed(
    db,
    *,
    case_id: str,
    task_id: str,
    escrow: float = 100.0,
    execute_after: datetime | None = None,
    status: str = "decided",
    outcome: str | None = "seller_wins",
    vote_round: int = 0,
    appeal_count: int = 0,
    panel: bool = False,
    votes: int = 0,
) -> None:
    db.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id=BUYER,
            title="appeal reopen case",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=escrow,
            deadline_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.add(
        SettlementModel(
            settlement_id="settle-" + task_id,
            task_id=task_id,
            escrow_amount=escrow,
            currency="USD",
            # 立案时已把 disputed 推到 arbitrated（api/routes/arbitration.py:220-238），
            # 所以这里必须是 arbitrated；写 disputed 会撞持久化守卫。
            status=TaskStatus.ARBITRATED.value,
            client_agent_id=BUYER,
            worker_agent_id=SELLER,
            released_amount=0.0,
            refunded_amount=0.0,
        )
    )
    db.add(
        ArbitrationCaseModel(
            case_id=case_id,
            task_id=task_id,
            opened_by=BUYER,
            status=status,
            required_arbitrators=3,
            decided_outcome=outcome,
            execute_after=execute_after,
            vote_round=vote_round,
            appeal_count=appeal_count,
        )
    )
    if panel:
        for arb in ARBS:
            db.add(
                ArbitrationPoolMemberModel(
                    arbitrator_identity_id=arb, stake_amount=500.0, status="active"
                )
            )
            db.add(
                ArbitrationAssignmentModel(case_id=case_id, arbitrator_identity_id=arb)
            )
    for arb in ARBS[:votes]:
        db.add(
            ArbitrationVoteModel(
                case_id=case_id,
                arbitrator_identity_id=arb,
                decision="seller_wins",
                vote_round=vote_round,
            )
        )
    await db.commit()


def _capture_chain_sync(monkeypatch) -> list:
    """把链上落钱那一步换成记录器 —— 上诉这条路上它一次都不该被调到。"""
    seen: list = []

    async def _recorder(*, db, state, target_status):
        seen.append(target_status)

    import api.routes.settlement as settlement_routes

    monkeypatch.setattr(settlement_routes, "_sync_escrow_settlement", _recorder)
    return seen


def _pretend_chain_is_open(monkeypatch, *, state: int | None = 1) -> None:
    """假装托管开着、链上绑定还在 active(1)/disputed(6)。"""
    import services.chain.escrow_settlement as es

    async def _binding(db, *, task_id):
        return object()

    async def _snapshot(binding):
        return None if state is None else {"state": state}

    monkeypatch.setattr(es, "enabled", lambda: True)
    monkeypatch.setattr(es, "newest_binding_for_task", _binding)
    monkeypatch.setattr(es, "chain_snapshot", _snapshot)


async def _case(db, case_id: str) -> ArbitrationCaseModel:
    return (
        await db.execute(select(ArbitrationCaseModel).where(ArbitrationCaseModel.case_id == case_id))
    ).scalars().one()


async def _settlement_status(db, task_id: str) -> str:
    row = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().one()
    return row.status


async def _events(db, case_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(ArbitrationCaseEventModel)
            .where(ArbitrationCaseEventModel.case_id == case_id)
            .order_by(ArbitrationCaseEventModel.created_at)
        )
    ).scalars().all()
    return [r.event_type for r in rows]


@pytest.mark.asyncio
async def test_appeal_with_the_window_off_is_refused(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 0)
    seen = _capture_chain_sync(monkeypatch)
    await _seed(db_session, case_id="case-a3-off", task_id="task-a3-off")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-a3-off/appeal",
        json={"appellant": BUYER, "reason": "second thoughts"},
    )
    assert resp.status_code == 409, resp.text
    assert seen == []
    case = await _case(db_session, "case-a3-off")
    assert case.status == "decided"
    assert case.appeal_count == 0


@pytest.mark.asyncio
async def test_in_window_appeal_reopens_the_case_for_free(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    seen = _capture_chain_sync(monkeypatch)
    _pretend_chain_is_open(monkeypatch, state=1)
    deadline = datetime.utcnow() + timedelta(seconds=300)
    await _seed(
        db_session, case_id="case-a3-open", task_id="task-a3-open", execute_after=deadline
    )

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-a3-open/appeal",
        json={"appellant": BUYER, "reason": "new evidence"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "voting"
    assert body["vote_round"] == 1
    assert body["appeal_count"] == 1
    assert body["previous_outcome"] == "seller_wins"
    assert body["chain_action"] == "none"

    # 关键：链上一笔没发、钱一分没动、结算还在 arbitrated。
    assert seen == [], "窗口内上诉不许碰链"
    assert await _settlement_status(db_session, "task-a3-open") == TaskStatus.ARBITRATED.value

    case = await _case(db_session, "case-a3-open")
    assert case.status == "voting"
    assert case.decided_outcome is None, "打回后不许留着旧裁决"
    assert case.execute_after is None, "打回必须取消已排期的放款"
    assert case.vote_round == 1
    assert case.appeal_count == 1
    assert "case_appeal_opened" in await _events(db_session, "case-a3-open")


@pytest.mark.asyncio
async def test_appeal_after_the_deadline_is_refused(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    seen = _capture_chain_sync(monkeypatch)
    await _seed(
        db_session,
        case_id="case-a3-late",
        task_id="task-a3-late",
        execute_after=datetime.utcnow() - timedelta(seconds=1),
    )

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-a3-late/appeal",
        json={"appellant": BUYER, "reason": "too late"},
    )
    assert resp.status_code == 409, resp.text
    assert seen == [], "窗口过了只能走 ④-B 的赔付，不许在这里假装能倒回来"
    case = await _case(db_session, "case-a3-late")
    assert case.status == "decided"
    assert case.execute_after is not None


@pytest.mark.asyncio
async def test_appeal_is_refused_once_the_chain_is_past_the_point_of_no_return(
    client_sec, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    _capture_chain_sync(monkeypatch)
    _pretend_chain_is_open(monkeypatch, state=2)  # finalizing = submitSettlement 已上链
    await _seed(
        db_session,
        case_id="case-a3-chain",
        task_id="task-a3-chain",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
    )

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-a3-chain/appeal",
        json={"appellant": BUYER, "reason": "reopen"},
    )
    assert resp.status_code == 409, resp.text
    assert (await _case(db_session, "case-a3-chain")).status == "decided"


@pytest.mark.asyncio
async def test_appeal_is_refused_when_the_chain_state_cannot_be_read(
    client_sec, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    _capture_chain_sync(monkeypatch)
    _pretend_chain_is_open(monkeypatch, state=None)
    await _seed(
        db_session,
        case_id="case-a3-blind",
        task_id="task-a3-blind",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
    )

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-a3-blind/appeal",
        json={"appellant": BUYER, "reason": "reopen"},
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_only_a_party_may_appeal(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    monkeypatch.setattr(settings, "arbitration_require_actor_binding", True)
    _capture_chain_sync(monkeypatch)
    await _seed(
        db_session,
        case_id="case-a3-party",
        task_id="task-a3-party",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
    )

    resp = await client.post(
        "/v1/arbitration/cases/case-a3-party/appeal",
        json={"appellant": "stranger-a3", "reason": "not my case"},
    )
    assert resp.status_code == 403, resp.text
    assert (await _case(db_session, "case-a3-party")).status == "decided"


@pytest.mark.asyncio
async def test_previous_round_votes_cannot_decide_the_new_round(
    client_sec, db_session, monkeypatch
):
    """上诉后：旧的 3 票不再算数，必须由新一轮重新投出来。

    这条是整个 ④-A3 最容易写错的地方 —— 只把状态改回 ``voting`` 而计票不分轮，
    那么重审里随便再来一票（甚至不用投）就会把旧结论立刻「投」出来，等于没打回。
    """
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    _capture_chain_sync(monkeypatch)
    await _seed(
        db_session,
        case_id="case-a3-round",
        task_id="task-a3-round",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
        panel=True,
        votes=3,
    )

    assert (
        await client_sec.post(
            "/v1/arbitration/cases/case-a3-round/appeal",
            json={"appellant": BUYER, "reason": "reopen"},
        )
    ).status_code == 200
    case = await _case(db_session, "case-a3-round")
    assert case.status == "voting"
    assert case.vote_round == 1

    # 新一轮的第一票：3 > 1，没到法定人数 -> 必须还停在 voting（旧票不算）。
    first = await client_sec.post(
        "/v1/arbitration/cases/case-a3-round/vote",
        json={"arbitrator_identity_id": ARBS[0], "decision": "buyer_wins"},
    )
    assert first.status_code == 200, first.text
    case = await _case(db_session, "case-a3-round")
    assert case.status == "voting", "上一轮的票不许把结果直接投出来"
    assert case.decided_outcome is None

    # 补齐新一轮的三票 -> 重新裁决，且结论按**新一轮**算（buyer_wins）。
    for arb in ARBS[1:]:
        voted = await client_sec.post(
            "/v1/arbitration/cases/case-a3-round/vote",
            json={"arbitrator_identity_id": arb, "decision": "buyer_wins"},
        )
        assert voted.status_code == 200, voted.text
    case = await _case(db_session, "case-a3-round")
    assert case.status == "decided"
    assert case.decided_outcome == "buyer_wins", "结论必须来自新一轮的票"

    # 裁决重新下发：又拿到一个新的到期时刻（窗口还开着）。
    again = await client_sec.post("/v1/arbitration/cases/case-a3-round/execute", json={})
    assert again.status_code == 200, again.text
    assert (await _case(db_session, "case-a3-round")).execute_after is not None


@pytest.mark.asyncio
async def test_reopened_case_cannot_run_the_scheduled_payout(client_sec, db_session, monkeypatch):
    """打回之后，原来那条 /execute-due 不许再放款。"""
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    seen = _capture_chain_sync(monkeypatch)
    await _seed(
        db_session,
        case_id="case-a3-nodue",
        task_id="task-a3-nodue",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
    )
    assert (
        await client_sec.post(
            "/v1/arbitration/cases/case-a3-nodue/appeal",
            json={"appellant": BUYER, "reason": "reopen"},
        )
    ).status_code == 200

    # 就算把到期时刻拨到过去，也不能放 —— 案件已不在 decided。
    row = await _case(db_session, "case-a3-nodue")
    row.execute_after = datetime.utcnow() - timedelta(seconds=1)
    await db_session.commit()

    resp = await client_sec.post("/v1/arbitration/cases/case-a3-nodue/execute-due", json={})
    assert resp.status_code == 409, resp.text
    assert seen == [], "打回的案件一分钱都不许动"


@pytest.mark.asyncio
async def test_the_number_of_appeals_is_capped(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_appeal_window_seconds", 300)
    monkeypatch.setattr(settings, "arbitration_max_appeals", 1)
    _capture_chain_sync(monkeypatch)
    await _seed(
        db_session,
        case_id="case-a3-cap",
        task_id="task-a3-cap",
        execute_after=datetime.utcnow() + timedelta(seconds=300),
        appeal_count=1,
    )

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-a3-cap/appeal",
        json={"appellant": BUYER, "reason": "again"},
    )
    assert resp.status_code == 409, resp.text
    case = await _case(db_session, "case-a3-cap")
    assert case.appeal_count == 1, "被拒的上诉不许把计数加上去"
    assert case.status == "decided"
