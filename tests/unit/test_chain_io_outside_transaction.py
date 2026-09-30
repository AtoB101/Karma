"""链上 I/O 必须待在 DB 事务之外（死锁根因）。

2026-09-30 并发压测：Postgres 报 deadlock detected，三方成环 —— 根因是
`_apply_transition` 在**同一个事务里**等链上回执（Sepolia 上 40~100s）。
这一路上 settlements 行锁（store.save）和 capacity 行锁（开争议时的
move_reserved_to_disputed）一直不放；autosettle 的 tick 是另一个事务，两边摸
同一批行的顺序相反，环就成形了。

这里钉住三件事：
  1. 链上那一步跑之前，事务已经 commit（行锁已放）；
  2. 链上失败时，已经落库的业务状态要退回去（不能声称一笔链上不认的结算）；
  3. 任何异常（不只是 HTTPException）都要退。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routes import settlement as S
from core.schemas import TaskStatus


class _Result:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._row or []


class _DB:
    """够用的假 session：只记事件顺序。"""

    def __init__(self, row=None, events=None):
        self.row = row
        self.events = events if events is not None else []
        self.commits = 0
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        self.events.append("execute")
        return _Result(self.row)

    async def commit(self):
        self.commits += 1
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")

    async def flush(self):
        self.events.append("flush")

    def add(self, obj):
        self.events.append("add")


class _Store:
    def __init__(self, events):
        self.events = events

    async def save(self, state):
        self.events.append("save")

    async def get(self, task_id):
        self.events.append("get")
        return None


def _row(*, status="delivered"):
    return SimpleNamespace(
        status=status,
        released_amount=None,
        refunded_amount=None,
        released_at=None,
        arbitration_notes=None,
        dispute_reason=None,
    )


def _state():
    return SimpleNamespace(
        settlement_id="s-1",
        task_id="t-1",
        client_agent_id="kid-b",
        escrow_amount=0.1,
        status=TaskStatus.DELIVERED,
        updated_at=None,
    )


def _patch_audit(monkeypatch, events):
    async def _audit(**kwargs):
        events.append("audit")
        return None

    monkeypatch.setattr(S, "_record_transition_audit", _audit)


@pytest.mark.asyncio
async def test_chain_io_runs_after_the_transition_is_committed(monkeypatch):
    events: list[str] = []
    db = _DB(_row(), events)
    store = _Store(events)
    _patch_audit(monkeypatch, events)

    seen: dict[str, int] = {}

    async def _chain(**kwargs):
        seen["commits_before_chain"] = db.commits
        events.append("chain")

    monkeypatch.setattr(S, "_sync_escrow_settlement", _chain)

    out = await S._apply_transition(
        db=db, store=store, state=_state(), target_status=TaskStatus.SETTLED,
        reason="test", route_path="/test", actor_id=None,
    )

    assert db.commits >= 1
    # 关键：动链之前就已经 commit 过 —— 链上等待期间不再持有行锁。
    assert seen["commits_before_chain"] >= 1
    assert events.index("commit") < events.index("chain")
    assert out.status == TaskStatus.SETTLED


@pytest.mark.asyncio
async def test_chain_gate_failure_rolls_the_committed_status_back(monkeypatch):
    events: list[str] = []
    db = _DB(_row(), events)
    store = _Store(events)
    _patch_audit(monkeypatch, events)

    async def _chain(**kwargs):
        raise HTTPException(409, "chain said no")

    monkeypatch.setattr(S, "_sync_escrow_settlement", _chain)

    with pytest.raises(HTTPException):
        await S._apply_transition(
            db=db, store=store, state=_state(), target_status=TaskStatus.SETTLED,
            reason="test", route_path="/test", actor_id=None,
        )

    updates = [s for s in db.statements if type(s).__name__ == "Update"]
    assert updates, "回退必须直接 UPDATE settlements 那一行"
    assert "rollback" in events
    assert db.commits >= 2  # 1) 状态落库 2) 回退落库


@pytest.mark.asyncio
async def test_any_exception_rolls_the_committed_status_back(monkeypatch):
    events: list[str] = []
    db = _DB(_row(), events)
    store = _Store(events)
    _patch_audit(monkeypatch, events)

    async def _chain(**kwargs):
        raise RuntimeError("rpc exploded")

    monkeypatch.setattr(S, "_sync_escrow_settlement", _chain)

    with pytest.raises(RuntimeError):
        await S._apply_transition(
            db=db, store=store, state=_state(), target_status=TaskStatus.SETTLED,
            reason="test", route_path="/test", actor_id=None,
        )

    assert [s for s in db.statements if type(s).__name__ == "Update"]


@pytest.mark.asyncio
async def test_snapshot_is_read_only(monkeypatch):
    db = _DB(_row())
    snap = await S._snapshot_settlement_row(db, "t-1")
    assert snap is not None and snap["status"] == "delivered"
    stmt = db.statements[0]
    assert stmt._for_update_arg is None


@pytest.mark.asyncio
async def test_snapshot_of_missing_row_is_none():
    assert await S._snapshot_settlement_row(_DB(None), "nope") is None



@pytest.mark.asyncio
async def test_dispute_revert_also_unfreezes_the_dispute_bucket(monkeypatch):
    """开争议的入口在状态机之前就冻了额度：状态退回去，冻结也得退。"""
    events: list[str] = []
    db = _DB(_row(), events)
    store = _Store(events)
    _patch_audit(monkeypatch, events)
    calls: list[dict] = []

    async def _delta(db_, model, key, identity, deltas, **kwargs):
        calls.append({"identity": identity, "deltas": deltas})
        return 1

    monkeypatch.setattr(S.atomic_ledger, "apply_delta_or_raise", _delta)

    async def _chain(**kwargs):
        raise HTTPException(409, "chain said no")

    monkeypatch.setattr(S, "_sync_escrow_settlement", _chain)
    state = _state()
    state.status = TaskStatus.IN_PROGRESS

    with pytest.raises(HTTPException):
        await S._apply_transition(
            db=db, store=store, state=state, target_status=TaskStatus.DISPUTED,
            reason="test", route_path="/test", actor_id=None,
        )

    move = [c for c in calls if c["identity"] == "kid-b"]
    assert move, "回退争议时必须把 disputed 里的冻结退回 reserved"
    assert move[0]["deltas"] == {"disputed_credits": -0.1, "reserved_credits": 0.1}

