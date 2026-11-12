"""F2：落库的 nonce 台账 —— 跨进程防重放 + 幂等回放。

并发压测抓到的 P2：客户端拿到 504 时服务端可能已经执行完了（Sepolia 上一笔 bind
就是一个区块），重发却只能拿到 409 duplicate —— 既判断不出成没成、也不敢再发。
这里钉死新的口径：第一次的结果存下来，重发原样回放。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from db.models.orm import RuntimeNonceLogModel
from services import runtime_nonce_log as nonce_log

KEY = "kid_nonce_test"


@pytest.fixture(autouse=True)
async def _clean_nonce_rows(db_session):
    await db_session.execute(delete(RuntimeNonceLogModel))
    await db_session.commit()
    yield
    await db_session.execute(delete(RuntimeNonceLogModel))
    await db_session.commit()


async def _claim(db_session, *, nonce="nonce-abcdefgh", body=None):
    body = body if body is not None else {"task": "t1"}
    return await nonce_log.claim(
        db_session,
        key_id=KEY,
        endpoint="place-order",
        nonce=nonce,
        request_hash=nonce_log.request_fingerprint(body),
    )


@pytest.mark.asyncio
async def test_first_claim_is_new_and_resend_while_running_is_busy(db_session):
    assert (await _claim(db_session))["state"] == "new"
    verdict = await _claim(db_session)
    assert verdict["state"] == "busy"


@pytest.mark.asyncio
async def test_a_finished_nonce_replays_its_first_response(db_session):
    assert (await _claim(db_session))["state"] == "new"
    await nonce_log.complete(
        db_session,
        key_id=KEY,
        endpoint="place-order",
        nonce="nonce-abcdefgh",
        http_status=201,
        payload={"task_id": "task-1", "voucher_id": "v-1"},
    )

    verdict = await _claim(db_session)
    assert verdict["state"] == "replay"
    assert verdict["http_status"] == 201
    assert verdict["payload"] == {"task_id": "task-1", "voucher_id": "v-1"}


@pytest.mark.asyncio
async def test_the_same_nonce_with_a_different_body_is_refused(db_session):
    assert (await _claim(db_session, body={"task": "t1"}))["state"] == "new"
    verdict = await _claim(db_session, body={"task": "t2"})
    assert verdict["state"] == "conflict"


@pytest.mark.asyncio
async def test_a_dead_attempt_can_be_taken_over(db_session, monkeypatch):
    """进程重启 / 请求半路夭折留下的占位不能把这个 nonce 永久锁死。"""
    monkeypatch.setattr(nonce_log, "STALE_IN_FLIGHT_SECONDS", -1.0)
    assert (await _claim(db_session))["state"] == "new"
    verdict = await _claim(db_session)
    assert verdict["state"] == "new"
    assert verdict.get("took_over") is True


@pytest.mark.asyncio
async def test_complete_without_a_claim_does_not_blow_up(db_session):
    await nonce_log.complete(
        db_session,
        key_id="kid_unknown",
        endpoint="place-order",
        nonce="nonce-never-claimed",
        http_status=200,
        payload={"ok": True},
    )
    assert (await _claim(db_session, nonce="nonce-never-claimed"))["state"] == "new"


@pytest.mark.asyncio
async def test_a_short_nonce_is_rejected(db_session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _claim(db_session, nonce="")
    assert exc.value.status_code == 400
