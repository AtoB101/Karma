"""F7 缺陷修复回归（2026-09-20，测试网端到端实测发现）。

对应 F6 报告的问题清单：

* 第 7 条 —— /partial 是一条「撤绑 → 重绑 → 划款」的同步长事务，实测 40s 以上。
  客户端超时后重试，服务端其实已经执行完，却甩一句 400 "requires delivered status"，
  调用方既判断不出成没成，文案还指错了方向。
* 第 8 条 —— /lock 同步返回 accepted 但 onchain_binding_id 恒为 null
  （绑定是 Celery 异步做的），调用方分不清「正在绑」和「压根没绑」。
* 第 9 条 —— confirm_window_hours 全代码库没有赋值点，恒为 null，
  于是交付后的唯一兜底 /auto-confirm 永远 409；而且
  DELIVERED → AUTO_CONFIRMED 这条边压根不在状态表里，双重不可达。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from httptest import post_minimal_contract, post_success_execution_receipt

from config.settings import settings
from core.schemas import TaskStatus
from core.settlement.engine import can_transition


def _voucher_body(*, buyer: str, seller: str, amount: float, task_type: str, nonce: str) -> dict:
    return {
        "buyer_identity_id": buyer,
        "seller_identity_id": seller,
        "amount": amount,
        "currency": "USDC",
        "bill_credit_amount": amount,
        "task_type": task_type,
        "task_description_hash": "a" * 64,
        "progress_rule_hash": "b" * 64,
        "evidence_requirement_hash": "c" * 64,
        "expiry_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        "nonce": nonce,
        "buyer_signature": "sig-" + nonce,
    }


async def _to_in_progress(
    client: AsyncClient,
    activate_identity,
    *,
    task_id: str,
    buyer: str,
    seller: str,
    amount: float = 100.0,
    task_type: str = "agent.f7",
) -> dict:
    """把一单推到 IN_PROGRESS（合同 → 凭证 → 结算 → 指派 → 开工 → 一条成功回执）。"""
    await client.post("/v1/capacity/" + buyer + "/lock", json={"amount": amount})
    await post_minimal_contract(
        client, task_id=task_id, client_agent_id=buyer, escrow_amount=amount, expected_step_count=5
    )
    v = await client.post(
        "/v1/vouchers",
        json=_voucher_body(buyer=buyer, seller=seller, amount=amount, task_type=task_type, nonce="n-" + task_id),
    )
    assert v.status_code == 201, v.text
    await activate_identity(seller)
    acc = await client.post(
        "/v1/vouchers/" + v.json()["voucher_id"] + "/accept", json={"seller_identity_id": seller}
    )
    assert acc.status_code == 200, acc.text
    created = await client.post(
        "/v1/settlement/create",
        json={"task_id": task_id, "client_agent_id": buyer, "escrow_amount": amount, "currency": "USD"},
    )
    assert created.status_code == 201, created.text
    locked = await client.post("/v1/settlement/" + task_id + "/lock", json={"worker_agent_id": seller})
    assert locked.status_code == 200, locked.text
    started = await client.post("/v1/settlement/" + task_id + "/start", json={})
    assert started.status_code == 200, started.text
    await post_success_execution_receipt(client, task_id=task_id, agent_id=seller)
    return locked.json()


async def _to_delivered(
    client: AsyncClient,
    activate_identity,
    *,
    task_id: str,
    buyer: str,
    seller: str,
    amount: float = 100.0,
    task_type: str = "agent.f7",
) -> dict:
    await _to_in_progress(
        client,
        activate_identity,
        task_id=task_id,
        buyer=buyer,
        seller=seller,
        amount=amount,
        task_type=task_type,
    )
    submitted = await client.post("/v1/settlement/" + task_id + "/submit", json={})
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


# ---------------------------------------------------------------------------
# 第 9 条：确认窗口 + /auto-confirm 可达性
# ---------------------------------------------------------------------------

class TestDefect9ConfirmWindowReachable:
    def test_delivered_to_auto_confirmed_edge_exists(self):
        """旧行为：这条边不在 VALID_TRANSITIONS 里，兜底路径从状态机就被堵死。"""
        assert can_transition(TaskStatus.DELIVERED, TaskStatus.AUTO_CONFIRMED)
        assert can_transition(TaskStatus.AUTO_CONFIRMED, TaskStatus.SETTLED)

    @pytest.mark.asyncio
    async def test_submit_stamps_confirm_window_and_deadline(self, client, activate_identity):
        state = await _to_delivered(
            client,
            activate_identity,
            task_id="task-f7-window-stamp",
            buyer="buyer-f7-stamp",
            seller="seller-f7-stamp",
            task_type="agent.f7_stamp",
        )
        assert state["status"] == TaskStatus.DELIVERED.value
        assert state["confirm_window_hours"] == settings.settlement_confirm_window_hours
        assert state["confirm_deadline_at"]
        deadline = datetime.fromisoformat(state["confirm_deadline_at"])
        delivered_at = datetime.fromisoformat(state["updated_at"])
        delta_hours = (deadline - delivered_at).total_seconds() / 3600
        assert abs(delta_hours - settings.settlement_confirm_window_hours) < 0.05

    @pytest.mark.asyncio
    async def test_auto_confirm_still_409_before_window_expires(self, client, activate_identity):
        task_id = "task-f7-window-open"
        await _to_delivered(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-open",
            seller="seller-f7-open",
            task_type="agent.f7_open",
        )
        r = await client.post("/v1/settlement/" + task_id + "/auto-confirm")
        assert r.status_code == 409
        assert "not expired" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_auto_confirm_settles_after_window_expires(self, client, db_session, activate_identity):
        task_id = "task-f7-window-expired"
        await _to_delivered(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-exp",
            seller="seller-f7-exp",
            task_type="agent.f7_exp",
        )
        from sqlalchemy import select

        from db.models.orm import SettlementModel

        row = (
            await db_session.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
        ).scalars().first()
        row.confirm_deadline_at = datetime.utcnow() - timedelta(hours=1)
        await db_session.commit()

        r = await client.post("/v1/settlement/" + task_id + "/auto-confirm")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == TaskStatus.SETTLED.value
        assert body["released_amount"] == 100.0
        assert body["refunded_amount"] == 0.0

    @pytest.mark.asyncio
    async def test_auto_confirm_explains_missing_window(
        self, client, activate_identity, monkeypatch
    ):
        """窗口关掉（=0）时交付单不带确认窗口，409 文案必须说清原因，而不是含糊的 not set。"""
        monkeypatch.setattr(settings, "settlement_confirm_window_hours", 0)
        task_id = "task-f7-window-off"
        state = await _to_delivered(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-off",
            seller="seller-f7-off",
            task_type="agent.f7_off",
        )
        assert state["confirm_window_hours"] is None
        assert state["confirm_deadline_at"] is None
        r = await client.post("/v1/settlement/" + task_id + "/auto-confirm")
        assert r.status_code == 409
        assert "confirm window" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 第 7 条：/partial 超时重试要能回答「到底成没成」
# ---------------------------------------------------------------------------

class TestDefect7PartialReplay:
    @pytest.mark.asyncio
    async def test_partial_replay_same_split_is_idempotent(self, client, activate_identity):
        task_id = "task-f7-partial-replay"
        await _to_delivered(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-replay",
            seller="seller-f7-replay",
            task_type="agent.f7_replay",
        )
        first = await client.post(
            "/v1/settlement/" + task_id + "/partial",
            json={"settled_value_percent": 50, "reason": "half"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["released_amount"] == 50.0

        # 客户端超时后的重试：同一个比例，应该拿到 200 + 当前状态，而不是一句指错方向的 400。
        again = await client.post(
            "/v1/settlement/" + task_id + "/partial",
            json={"settled_value_percent": 50, "reason": "retry after client timeout"},
        )
        assert again.status_code == 200, again.text
        assert again.json()["status"] == TaskStatus.SETTLED.value
        assert again.json()["released_amount"] == 50.0
        assert again.json()["refunded_amount"] == 50.0

    @pytest.mark.asyncio
    async def test_partial_replay_different_split_says_already_settled(self, client, activate_identity):
        task_id = "task-f7-partial-mismatch"
        await _to_delivered(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-mm",
            seller="seller-f7-mm",
            task_type="agent.f7_mm",
        )
        first = await client.post(
            "/v1/settlement/" + task_id + "/partial",
            json={"settled_value_percent": 50, "reason": "half"},
        )
        assert first.status_code == 200, first.text
        other = await client.post(
            "/v1/settlement/" + task_id + "/partial",
            json={"settled_value_percent": 30, "reason": "different split"},
        )
        assert other.status_code == 409
        detail = other.json()["detail"]
        assert detail["error"] == "already_settled"
        assert detail["released_amount"] == 50.0
        assert detail["refunded_amount"] == 50.0

    @pytest.mark.asyncio
    async def test_partial_on_cancelled_settlement_is_explicit(self, client, activate_identity):
        task_id = "task-f7-partial-cancelled"
        buyer = "buyer-f7-cancel"
        seller = "seller-f7-cancel"
        await _to_in_progress(
            client,
            activate_identity,
            task_id=task_id,
            buyer=buyer,
            seller=seller,
            task_type="agent.f7_cancel",
        )
        failed = await client.post("/v1/settlement/" + task_id + "/fail", json={})
        assert failed.status_code == 200, failed.text
        assert failed.json()["status"] == TaskStatus.CANCELLED.value

        r = await client.post(
            "/v1/settlement/" + task_id + "/partial",
            json={"settled_value_percent": 50, "reason": "too late"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "settlement_not_open_for_partial"

    @pytest.mark.asyncio
    async def test_partial_without_delivery_names_the_actual_status(self, client, activate_identity):
        """中间态的 400 必须把「现在到底是什么状态」说出来，而不是只喊着要 delivered。"""
        task_id = "task-f7-partial-inprogress"
        await _to_in_progress(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-ip",
            seller="seller-f7-ip",
            task_type="agent.f7_ip",
        )
        r = await client.post(
            "/v1/settlement/" + task_id + "/partial",
            json={"settled_value_percent": 10, "reason": "skip delivered"},
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "delivered" in detail.lower()
        assert TaskStatus.IN_PROGRESS.value in detail


# ---------------------------------------------------------------------------
# 第 8 条：/lock 要能说清「正在绑」
# ---------------------------------------------------------------------------

class TestDefect8LockBindingPending:
    @pytest.mark.asyncio
    async def test_lock_marks_onchain_binding_pending(self, client, activate_identity, monkeypatch):
        from services.chain.settlement_adapter import settlement_router

        monkeypatch.setattr(settlement_router, "is_onchain", lambda: True)
        dispatched: list = []

        class _FakeTask:
            def delay(self, *args, **kwargs):
                dispatched.append((args, kwargs))

        import worker.tasks as worker_tasks

        monkeypatch.setattr(worker_tasks, "lock_and_bind_onchain", _FakeTask())

        task_id = "task-f7-lock-pending"
        state = await _to_in_progress(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-lock",
            seller="seller-f7-lock",
            task_type="agent.f7_lock",
        )
        # 同步响应里 onchain_binding_id 仍然给不出（异步），但必须明确标成「在绑」。
        assert state["onchain_status"] == "pending_bind"
        assert dispatched and dispatched[0][0][0] == task_id
        got = (await client.get("/v1/settlement/" + task_id)).json()
        assert got["onchain_status"] == "pending_bind"

    @pytest.mark.asyncio
    async def test_lock_offchain_leaves_status_untouched(self, client, activate_identity):
        task_id = "task-f7-lock-offchain"
        state = await _to_in_progress(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-lockoff",
            seller="seller-f7-lockoff",
            task_type="agent.f7_lockoff",
        )
        assert state["onchain_status"] is None

    @pytest.mark.asyncio
    async def test_lock_response_reflects_onchain_truth(self, client, activate_identity, monkeypatch):
        """托管通道是**同步**绑的：响应必须带链上真相，而不是陈旧的 null。

        防的是「数据库说已绑、响应说没绑」：操作台刚接完单，卡片上会显示成没上链，
        用户以为钱没锁进去，实际链上已经占了额度。整条链跑下来只有 _reflect 那一处
        会写这些列，所以这里用假的绑定实现把同样的效果做出来。
        """
        from services.chain import escrow_settlement

        async def _fake_bind(db, *, task_id, buyer_identity_id, seller_identity_id, amount_usdc):
            from sqlalchemy import select

            from db.models.orm import SettlementModel

            row = (
                await db.execute(
                    select(SettlementModel).where(SettlementModel.task_id == task_id)
                )
            ).scalars().first()
            row.onchain_status = "bound"
            row.onchain_binding_id = 4242
            row.tx_hash = "0x" + "ab" * 32
            await db.flush()
            return {"status": "bound", "binding_id": "4242"}

        monkeypatch.setattr(escrow_settlement, "enabled", lambda: True)
        monkeypatch.setattr(escrow_settlement, "bind_for_task", _fake_bind)

        task_id = "task-f7-lock-truth"
        state = await _to_in_progress(
            client,
            activate_identity,
            task_id=task_id,
            buyer="buyer-f7-truth",
            seller="seller-f7-truth",
            task_type="agent.f7_truth",
        )
        assert state["onchain_status"] == "bound"
        assert state["onchain_binding_id"] == 4242
        got = (await client.get("/v1/settlement/" + task_id)).json()
        assert got["onchain_status"] == "bound"
        assert got["onchain_binding_id"] == 4242
