"""补绑必须是一次性的：两个并发入口不能各绑一条。

2026-09-30 并发压测实测：同一单在链上出现两条绑定（binding 188 与 190），
两边都从买方额度里占走了一笔钱。原因是 materialize_pending_bind 只做了一次
普通 SELECT：请求路径（交付 / 验收 / 争议都会先补绑）和 autosettle 的
bind_due 同时读到 pending_bind，于是各绑一条。

这里钉住：这行是按 FOR UPDATE 读的 —— 第二条进来时读到的是第一条已经落定的
状态，直接返回 None，不会再去开一条新绑定。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.chain import escrow_settlement as es


class _Result:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _DB:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.row)


def _pending_row():
    return SimpleNamespace(task_id="t-1", onchain_status=es.PENDING_BIND)


@pytest.mark.asyncio
async def test_pending_bind_row_is_read_for_update(monkeypatch):
    monkeypatch.setattr(es, "enabled", lambda: True)

    async def _no_params(db, *, task_id):
        return None

    monkeypatch.setattr(es, "_bind_params_from_books", _no_params)
    db = _DB(_pending_row())

    assert await es.materialize_pending_bind(db, task_id="t-1") is None
    assert len(db.statements) == 1
    assert db.statements[0]._for_update_arg is not None


@pytest.mark.asyncio
async def test_settled_row_is_left_alone(monkeypatch):
    monkeypatch.setattr(es, "enabled", lambda: True)
    db = _DB(SimpleNamespace(task_id="t-1", onchain_status="bound"))

    assert await es.materialize_pending_bind(db, task_id="t-1") is None


@pytest.mark.asyncio
async def test_missing_row_is_left_alone(monkeypatch):
    monkeypatch.setattr(es, "enabled", lambda: True)
    db = _DB(None)

    assert await es.materialize_pending_bind(db, task_id="t-1") is None
