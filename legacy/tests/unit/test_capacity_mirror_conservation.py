"""镜像对账写台账时，守恒式必须**由数据库自己**算出来。

2026-09-29 真钱实测抓到的那一笔：

    POST /v1/settlement/{task}/dispute -> 500 "capacity invariant check failed"

钱的路径一步没走错，坏的是台账里两列**派生值**：``reconcile_capacity_mirror`` 老写法是
「读快照 -> Python 里加 delta -> 整列赋值」，而它只写 available / total_bill_credits /
total_locked_usdc 三列，不碰 reserved 这些责任桶。autosettle 那一轮的会话跨了好几次
commit + 一次读链，身份映射里的 ``capacity`` 行停在几分钟前，中间那笔「卖方接单 -> 买方
额度进 reserved」根本没进它的快照：写回去的 ``total_bill_credits`` 于是少算了那笔预留，
``total_bill_credits == active`` 当场破掉。紧接着用户点「开争议」，冻结走到自检就 500 ——
钱一分没动，但用户开不了争议（责任状态也进不去）。

修法两条，这里各钉一组：

1. 镜像写入改成**一条 UPDATE + 相对增量**，``active`` / ``total_locked_usdc`` 由数据库按
   当前那一行现算（``escrow._apply_capacity_delta``）—— 中间被谁改过都算得进去；
2. 派生列真被写坏时（老 bug / 人工修库留下的行），动钱的入口**就地按守恒式修复**并大声
   记日志，而不是把钱的路 500 掉（``capacity_ledger.heal_capacity_conservation``）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from core.schemas import CapacityState
from db.models.orm import AllowanceCommitModel, CapacityModel
from services import atomic_ledger, capacity_resolution
from services.capacity_ledger import (
    assert_capacity_invariants,
    capacity_conservation_gap,
    heal_capacity_conservation,
)
from services.chain import allowance_escrow as escrow

IDENTITY = "kid_capacity_conservation"
TOKEN = "0x6af606f5b071bf649dc136fcd308ed0c9adf38ff"
CONTRACT = "0x3fe45f40c19978e81296efaf63eb2ca0c79f0e66"
OPERATOR = "0x1d147c9eefd9d1d4c4725700a05edc6ca13975cc"
DECIMALS = 10 ** 6


def _state(cap: CapacityModel) -> CapacityState:
    return CapacityState(
        identity_id=cap.identity_id,
        total_locked_usdc=cap.total_locked_usdc,
        total_bill_credits=cap.total_bill_credits,
        available_credits=cap.available_credits,
        reserved_credits=cap.reserved_credits,
        in_progress_credits=cap.in_progress_credits,
        confirmed_progress_credits=cap.confirmed_progress_credits,
        disputed_credits=cap.disputed_credits,
        pending_settlement_credits=cap.pending_settlement_credits,
        burned_credits=cap.burned_credits,
        released_credits=cap.released_credits,
    )


async def _fresh(db, identity_id: str = IDENTITY) -> CapacityModel:
    cap = await db.get(CapacityModel, identity_id)
    db.expire(cap)
    await db.refresh(cap)
    return cap


@pytest.fixture(autouse=True)
async def _clean(db_session):
    await db_session.execute(
        delete(AllowanceCommitModel).where(AllowanceCommitModel.identity_id == IDENTITY)
    )
    await db_session.execute(
        delete(CapacityModel).where(CapacityModel.identity_id == IDENTITY)
    )
    await db_session.commit()
    yield
    await db_session.execute(
        delete(AllowanceCommitModel).where(AllowanceCommitModel.identity_id == IDENTITY)
    )
    await db_session.execute(
        delete(CapacityModel).where(CapacityModel.identity_id == IDENTITY)
    )
    await db_session.commit()


async def _seed(db, *, total: float = 12.0) -> None:
    """一个身份：锁仓 total，全部可用，链上担保也是 total。"""
    db.add(
        CapacityModel(
            identity_id=IDENTITY,
            total_locked_usdc=total,
            total_bill_credits=total,
            available_credits=total,
            updated_at=None,
        )
    )
    db.add(
        AllowanceCommitModel(
            bill_id="1",
            identity_id=IDENTITY,
            wallet_address="0x7ed437e5786ab0d217d52937da4ff4790998d94c",
            chain_id=11155111,
            contract_address=CONTRACT,
            token_address=TOKEN,
            operator=OPERATOR,
            amount_wei=str(int(total * DECIMALS)),
            amount_usdc=float(total),
            backed=True,
            commit_tx_hash="0x" + "11" * 32,
            state=escrow.IDLE,
            capacity_credited_usdc=float(total),
        )
    )
    await db.flush()


def _chain(monkeypatch, allowance: float) -> None:
    from config.settings import settings

    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", True)
    monkeypatch.setattr(settings, "allowance_escrow_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    monkeypatch.setattr(escrow, "_web3", lambda: object())
    monkeypatch.setattr(
        escrow,
        "_erc20_allowance_wei",
        lambda w3, token, owner, spender: int(round(float(allowance) * DECIMALS)),
    )


# ------------------------------------------------- 相对增量：并发预留不算丢

@pytest.mark.asyncio
async def test_capacity_delta_write_survives_a_concurrent_reservation(db_session):
    """写数之前，另一条路把 2 美元挪进了 ``reserved`` —— 守恒式不许破。

    这正是线上那笔的形状：镜像手里的快照里 ``reserved=0``，而落库的那一行已经是
    ``reserved=2``。老写法会把 ``total_bill_credits`` 写成一个「按快照算的绝对数」，
    于是 ``total_bill_credits`` 与 active 差出正好这 2 美元。
    """
    await _seed(db_session, total=12.0)
    # 镜像读到的快照：全部可用。
    cap = await _fresh(db_session)
    assert capacity_conservation_gap(cap) is None

    # 并发路：卖方接单，把 2 美元从可用挪进责任桶（raw UPDATE，绕过这份快照）。
    await atomic_ledger.apply_delta_or_raise(
        db_session,
        CapacityModel,
        "identity_id",
        IDENTITY,
        {"available_credits": -2.0, "reserved_credits": 2.0},
        guards=[(lambda C: C.available_credits + 1e-9 >= 2.0)],
    )

    # 镜像此刻才知道链上担保少 0.1（比如结算划走了一笔）。
    await escrow._apply_capacity_delta(db_session, IDENTITY, -0.1)

    fresh = await _fresh(db_session)
    assert capacity_conservation_gap(fresh) is None
    assert_capacity_invariants(_state(fresh))
    # 预留一分没丢，链上的差额只从可用那一侧扣。
    assert fresh.reserved_credits == pytest.approx(2.0)
    assert fresh.available_credits == pytest.approx(12.0 - 2.0 - 0.1)
    assert fresh.total_bill_credits == pytest.approx(12.0 - 0.1)
    assert fresh.total_locked_usdc == pytest.approx(12.0 - 0.1)


@pytest.mark.asyncio
async def test_capacity_delta_write_never_pushes_locked_below_active(db_session):
    """差额是正的也一样：``total_locked_usdc`` 只能被抬到 active，不能被压低过去。"""
    await _seed(db_session, total=12.0)
    await atomic_ledger.apply_delta_or_raise(
        db_session,
        CapacityModel,
        "identity_id",
        IDENTITY,
        {"available_credits": -12.0, "disputed_credits": 12.0},
        guards=[(lambda C: C.available_credits + 1e-9 >= 12.0)],
    )
    # 台账里的 total_locked 被写小过（历史坏账）。
    await db_session.execute(
        CapacityModel.__table__.update()
        .where(CapacityModel.identity_id == IDENTITY)
        .values(total_locked_usdc=0.0)
    )
    await db_session.flush()

    await escrow._apply_capacity_delta(db_session, IDENTITY, 0.5)

    fresh = await _fresh(db_session)
    assert_capacity_invariants(_state(fresh))
    assert fresh.total_locked_usdc >= 12.5


# ------------------------------------------------- 镜像之后开争议：不许 500

@pytest.mark.asyncio
async def test_dispute_freeze_after_a_mirror_write_is_still_conserved(
    db_session, monkeypatch
):
    """镜像写过台账之后紧接着开争议 —— 冻结照样成功，账还是守恒的。"""
    await _seed(db_session, total=12.0)
    _chain(monkeypatch, 11.9)

    async def _noop_sync(db, identity_id):
        return []

    monkeypatch.setattr(escrow, "sync_commits", _noop_sync)
    # 卖方接单：2 美元进责任桶。
    await atomic_ledger.apply_delta_or_raise(
        db_session,
        CapacityModel,
        "identity_id",
        IDENTITY,
        {"available_credits": -2.0, "reserved_credits": 2.0},
        guards=[(lambda C: C.available_credits + 1e-9 >= 2.0)],
    )
    result = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)
    assert result["delta_usdc"] == pytest.approx(-0.1)

    # 0.5 的单子开争议：reserved -> disputed。
    await capacity_resolution.move_reserved_to_disputed(
        db=db_session, buyer_identity_id=IDENTITY, escrow_amount=0.5
    )

    fresh = await _fresh(db_session)
    assert_capacity_invariants(_state(fresh))
    assert fresh.disputed_credits == pytest.approx(0.5)
    assert fresh.reserved_credits == pytest.approx(1.5)


# ------------------------------------------------- 坏行：就地修复，不是 500

@pytest.mark.asyncio
async def test_move_reserved_to_disputed_heals_a_broken_derived_column(db_session):
    """``total_bill_credits`` 被写坏（少算了责任桶）时，开争议不该 500。"""
    await _seed(db_session, total=12.0)
    await atomic_ledger.apply_delta_or_raise(
        db_session,
        CapacityModel,
        "identity_id",
        IDENTITY,
        {"available_credits": -2.0, "reserved_credits": 2.0},
        guards=[(lambda C: C.available_credits + 1e-9 >= 2.0)],
    )
    # 老 bug 留下的形状：bill 少算了那笔预留，locked 也被压到 active 以下。
    await db_session.execute(
        CapacityModel.__table__.update()
        .where(CapacityModel.identity_id == IDENTITY)
        .values(total_bill_credits=10.0, total_locked_usdc=10.0)
    )
    await db_session.flush()

    await capacity_resolution.move_reserved_to_disputed(
        db=db_session, buyer_identity_id=IDENTITY, escrow_amount=0.5
    )

    fresh = await _fresh(db_session)
    assert_capacity_invariants(_state(fresh))
    assert fresh.disputed_credits == pytest.approx(0.5)
    assert fresh.total_bill_credits == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_heal_capacity_conservation_is_a_noop_when_healthy(db_session):
    await _seed(db_session, total=12.0)

    assert await heal_capacity_conservation(db_session, IDENTITY, context="test") is None
    fresh = await _fresh(db_session)
    assert_capacity_invariants(_state(fresh))


@pytest.mark.asyncio
async def test_heal_capacity_conservation_raises_locked_never_lowers_it(db_session):
    """修复只可能把 ``total_locked_usdc`` 抬高：它是「钱锚」的下界。"""
    await _seed(db_session, total=12.0)
    await db_session.execute(
        CapacityModel.__table__.update()
        .where(CapacityModel.identity_id == IDENTITY)
        .values(total_locked_usdc=0.0)
    )
    await db_session.flush()

    gap = await heal_capacity_conservation(db_session, IDENTITY, context="test")

    assert gap is not None
    fresh = await _fresh(db_session)
    assert fresh.total_locked_usdc == pytest.approx(12.0)
    assert fresh.available_credits == pytest.approx(12.0)
    assert_capacity_invariants(_state(fresh))
