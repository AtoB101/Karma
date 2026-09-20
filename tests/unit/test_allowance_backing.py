"""v2 allowance escrow —— 同一个钱包的多张账单共用一条 ERC-20 授权。

合约的 ``isBacked`` 只回答「**单张**账单 ≤ 授权额」。所以「账单合计 170、钱包只授权
50」在链上逐张看全部 backed，真到划款却只划得动 50 —— 剩下的账单会在结算那一刻变成
收不到钱的孤儿单，而台账里的「锁仓额度」还显示着 170。

这些用例钉住修复后的口径：把授权额按账单号（= 承诺时间）最早优先分下去，只有分到的
部分才算「真划得动的钱」，也才是能记进 capacity 台账、能让 agent 花出去的额度；分不到
的账单仍然 open，但额度和台账里都不再算它。
"""
from __future__ import annotations

import pytest

from config.settings import settings
from db.models.orm import AllowanceCommitModel, CapacityModel
from services.chain import allowance_escrow as escrow
from services.chain.wallet_lock import WalletLockError

IDENTITY = "identity-backing-test"
WALLET = "0x7ed437e5786ab0d217d52937da4ff4790998d94c"
OTHER_WALLET = "0x5acc51116f66b84802c8321f286d09014a78346f"
TOKEN = "0x6af606f5b071bf649dc136fcd308ed0c9adf38ff"
CONTRACT = "0x3fe45f40c19978e81296efaf63eb2ca0c79f0e66"
#: 合约升级之后被留在身后的那台（v2 → v3 的真实形状）。
RETIRED = "0x" + "77" * 20
OPERATOR = "0x1d147c9eefd9d1d4c4725700a05edc6ca13975cc"
DECIMALS = 10 ** 6

#: 生产台账里的形状：8 张账单合计 170，而钱包只给托管合约授权了 50。
BILLS_170 = [
    ("1", 25.0),
    ("2", 20.0),
    ("3", 30.0),
    ("4", 15.0),
    ("5", 20.0),
    ("6", 25.0),
    ("7", 10.0),
    ("8", 25.0),
]


async def _seed_commits(
    db,
    bills,
    *,
    identity_id: str = IDENTITY,
    wallet: str = WALLET,
    state: str = escrow.IDLE,
    contract: str = CONTRACT,
):
    """记一条 v2 承诺：钱从未离开钱包，只是一条链上责任 + 一条 ERC-20 授权。"""
    for bill_id, amount in bills:
        db.add(
            AllowanceCommitModel(
                bill_id=bill_id,
                identity_id=identity_id,
                wallet_address=wallet,
                chain_id=11155111,
                contract_address=contract,
                token_address=TOKEN,
                operator=OPERATOR,
                amount_wei=str(int(amount * DECIMALS)),
                amount_usdc=float(amount),
                backed=True,
                commit_tx_hash="0x" + bill_id.encode("utf-8").hex().ljust(64, "0")[:64],
                state=state,
            )
        )
    await db.flush()


def _allowance_chain(
    monkeypatch,
    allowance_usdc: float,
    *,
    readable: bool = True,
    owner_allowances: dict | None = None,
) -> None:
    """装一个「配了托管合约、授权额读得到」的链。

    ``readable=False`` 模拟 Sepolia RPC 抖动：链在，但这一次读不出来。
    """
    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", True)
    monkeypatch.setattr(settings, "allowance_escrow_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    monkeypatch.setattr(escrow, "_web3", lambda: object())

    def _read(w3, token, owner, spender):
        if not readable:
            raise RuntimeError("sepolia rpc is down")
        amount = (owner_allowances or {}).get(str(owner).lower(), allowance_usdc)
        return int(round(float(amount) * DECIMALS))

    monkeypatch.setattr(escrow, "_erc20_allowance_wei", _read)


# ------------------------------------------------------------ 纯函数：分配口径


def test_allocate_allowance_serves_the_oldest_bills_first():
    secured = escrow.allocate_allowance(BILLS_170, 50.0)

    assert secured["1"] == pytest.approx(25.0)
    assert secured["2"] == pytest.approx(20.0)
    # 第 3 张只剩零头，第 4 张之后一张都分不到。
    assert secured["3"] == pytest.approx(5.0)
    for bill_id in ("4", "5", "6", "7", "8"):
        assert secured[bill_id] == pytest.approx(0.0)
    assert sum(secured.values()) == pytest.approx(50.0)


def test_allocate_allowance_never_hands_out_more_than_a_bill_can_spend():
    """授权额比账单合计还大时，多出来的部分不能凭空变成额度。"""
    secured = escrow.allocate_allowance(BILLS_170, 1000.0)
    assert sum(secured.values()) == pytest.approx(170.0)
    assert secured["1"] == pytest.approx(25.0)
    assert secured["8"] == pytest.approx(25.0)


def test_allocate_allowance_with_no_allowance_secures_nothing():
    secured = escrow.allocate_allowance(BILLS_170, 0.0)
    assert sum(secured.values()) == pytest.approx(0.0)
    assert set(secured) == {bill_id for bill_id, _ in BILLS_170}


def test_allocate_allowance_keeps_fractions_intact():
    secured = escrow.allocate_allowance([("1", 0.2), ("2", 0.2)], 0.3)
    assert secured["1"] == pytest.approx(0.2)
    assert secured["2"] == pytest.approx(0.1)
    assert sum(secured.values()) == pytest.approx(0.3)


def test_assert_room_refuses_what_the_chain_cannot_fund():
    with pytest.raises(WalletLockError) as exc:
        escrow.assert_room("buyer", 30.0, 12.0)
    message = str(exc.value)
    assert "30" in message and "12" in message
    assert "allowance" in message


def test_assert_room_accepts_an_exact_fit():
    escrow.assert_room("seller", 9.0, 9.0)
    escrow.assert_room("buyer", 9.0, 12.5)


# ------------------------------------------------------------------ 链上担保口径


@pytest.mark.asyncio
async def test_backing_report_is_empty_for_an_identity_without_commits(db_session):
    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["committed_usdc"] == pytest.approx(0.0)
    assert report["secured_usdc"] == pytest.approx(0.0)
    assert report["unsecured_usdc"] == pytest.approx(0.0)
    assert report["bills"] == {}


@pytest.mark.asyncio
async def test_backing_report_caps_the_committed_total_at_the_wallet_allowance(
    db_session, monkeypatch
):
    """核心：账上 170、授权 50 —— 只有 50 是真划得动的。"""
    await _seed_commits(db_session, BILLS_170)
    _allowance_chain(monkeypatch, 50.0)

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["enforced"] is True
    assert report["chain_checked"] is True
    assert report["committed_usdc"] == pytest.approx(170.0)
    assert report["allowance_usdc"] == pytest.approx(50.0)
    assert report["secured_usdc"] == pytest.approx(50.0)
    assert report["unsecured_usdc"] == pytest.approx(120.0)
    assert report["bills"]["1"]["secured_usdc"] == pytest.approx(25.0)
    assert report["bills"]["3"]["secured_usdc"] == pytest.approx(5.0)
    assert report["bills"]["8"]["secured_usdc"] == pytest.approx(0.0)
    assert sum(b["secured_usdc"] for b in report["bills"].values()) == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_backing_report_orders_bills_numerically_not_lexically(db_session, monkeypatch):
    """账单 10 比 9 晚，所以先到先得时 9 先拿钱（按字符串排会把 10 排到前面）。"""
    await _seed_commits(db_session, [("10", 5.0), ("9", 5.0)])
    _allowance_chain(monkeypatch, 5.0)

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["bills"]["9"]["secured_usdc"] == pytest.approx(5.0)
    assert report["bills"]["10"]["secured_usdc"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_backing_report_reads_each_wallet_separately(db_session, monkeypatch):
    """两个钱包各有自己的授权额，不能拿一个钱包的授权去担保另一个钱包的账单。"""
    await _seed_commits(db_session, [("1", 25.0)], wallet=WALLET)
    await _seed_commits(db_session, [("2", 30.0)], wallet=OTHER_WALLET)
    _allowance_chain(monkeypatch, 0.0, owner_allowances={WALLET: 20.0, OTHER_WALLET: 30.0})

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["allowance_usdc"] == pytest.approx(50.0)
    assert report["committed_usdc"] == pytest.approx(55.0)
    assert report["secured_usdc"] == pytest.approx(50.0)
    assert report["unsecured_usdc"] == pytest.approx(5.0)
    assert report["bills"]["1"]["secured_usdc"] == pytest.approx(20.0)
    assert report["bills"]["2"]["secured_usdc"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_backing_report_refuses_to_trust_a_chain_it_could_not_read(
    db_session, monkeypatch
):
    """读不到链就不能声称担保：宁可说「不知道」，也不能按台账数字放行。"""
    await _seed_commits(db_session, [("1", 40.0)])
    _allowance_chain(monkeypatch, 0.0, readable=False)

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["enforced"] is True
    assert report["chain_checked"] is False
    assert report["secured_usdc"] == pytest.approx(0.0)
    assert report["unsecured_usdc"] == pytest.approx(40.0)
    # 读不到链就一分钱都不认：这张账单的份额也是 0。
    assert report["bills"]["1"]["secured_usdc"] == pytest.approx(0.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "1") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_backing_report_falls_back_to_the_ledger_when_escrow_is_not_configured(
    db_session, monkeypatch
):
    """这个部署没配托管合约：链上根本没有授权额这回事，回落到台账口径。"""
    await _seed_commits(db_session, [("1", 40.0)])
    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", False)
    monkeypatch.setattr(settings, "allowance_escrow_address", "")
    monkeypatch.setattr(settings, "erc20_token_address", "")
    monkeypatch.setattr(settings, "testnet_rpc_url", "")

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["enforced"] is False
    assert report["chain_checked"] is False
    assert report["secured_usdc"] == pytest.approx(40.0)
    assert report["unsecured_usdc"] == pytest.approx(0.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "1") == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_secured_usdc_for_bill_only_pays_the_oldest_bills(db_session, monkeypatch):
    await _seed_commits(db_session, BILLS_170)
    _allowance_chain(monkeypatch, 50.0)

    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "1") == pytest.approx(25.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "3") == pytest.approx(5.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "8") == pytest.approx(0.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "999") == pytest.approx(0.0)


def _stub_sync(monkeypatch) -> None:
    """扫描本身不读链：``sync_commits`` 的链上副作用由别的用例覆盖。"""

    async def _noop(db, identity_id):
        return []

    monkeypatch.setattr(escrow, "sync_commits", _noop)


# --------------------------------------------------------- capacity 台账镜像


@pytest.mark.asyncio
async def test_capacity_mirror_credits_only_the_backed_part(db_session, monkeypatch):
    """台账不能再虚增：170 的账单只授权了 50，能花的就只有 50。"""
    await _seed_commits(db_session, BILLS_170)
    _allowance_chain(monkeypatch, 50.0)

    result = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)

    assert result["credited_usdc"] == pytest.approx(50.0)
    assert result["delta_usdc"] == pytest.approx(50.0)
    assert result["unsecured_usdc"] == pytest.approx(120.0)

    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(50.0)
    assert cap.total_locked_usdc == pytest.approx(50.0)
    assert cap.total_bill_credits == pytest.approx(50.0)

    # 每行记住自己贡献了多少，所以再跑一次不会重复记账
    again = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)
    assert again["delta_usdc"] == pytest.approx(0.0)
    assert again["credited_usdc"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_capacity_mirror_waits_out_an_unreadable_chain(db_session, monkeypatch):
    """RPC 抖动时台账保持原样：读不到链不能放行，也不能把已锁的额度清零。"""
    await _seed_commits(db_session, [("1", 40.0)])
    _allowance_chain(monkeypatch, 40.0)
    await escrow.reconcile_capacity_mirror(db_session, IDENTITY)

    _allowance_chain(monkeypatch, 0.0, readable=False)
    result = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)

    assert result["delta_usdc"] == pytest.approx(0.0)
    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(40.0)
    assert cap.total_locked_usdc == pytest.approx(40.0)

    # 链读回来之后，对账自己纠偏
    _allowance_chain(monkeypatch, 10.0)
    healed = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)
    assert healed["delta_usdc"] == pytest.approx(-30.0)
    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_revoked_bills_stop_eating_the_allowance(db_session, monkeypatch):
    """撤销掉的账单不再占额度，剩下的授权额要留给还活着的账单。"""
    await _seed_commits(db_session, [("1", 25.0)])
    await _seed_commits(db_session, [("2", 30.0)], state=escrow.REVOKED)
    _allowance_chain(monkeypatch, 25.0)

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["committed_usdc"] == pytest.approx(25.0)
    assert report["secured_usdc"] == pytest.approx(25.0)
    assert report["unsecured_usdc"] == pytest.approx(0.0)
    assert "2" not in report["bills"]


# -------------------------------------------- 合约升级：账单属于具体某一台合约


@pytest.mark.asyncio
async def test_bills_left_on_a_retired_contract_do_not_back_the_current_one(
    db_session, monkeypatch
):
    """2026-09-20 实测：v2 换 v3 之后旧账单还在台账里，但它们救不了新单。

    钱没丢（还在用户钱包里、还在旧合约上记着），可它不能变成「可花额度」——
    当前合约那条 ERC-20 授权额跟它没有任何关系。
    """
    await _seed_commits(db_session, [("1", 25.0)])
    await _seed_commits(db_session, [("37", 40.0)], contract=RETIRED)
    _allowance_chain(monkeypatch, 50.0)

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["committed_usdc"] == pytest.approx(25.0)
    assert report["secured_usdc"] == pytest.approx(25.0)
    assert "37" not in report["bills"]
    # 旧合约的锁仓要如实报出来，不能让用户以为钱不见了
    assert report["legacy"]["contracts"] == [RETIRED]
    assert report["legacy"]["committed_usdc"] == pytest.approx(40.0)
    assert report["legacy"]["bills"]["37"]["live_usdc"] == pytest.approx(40.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "37") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_a_retired_contract_never_eats_the_current_allowance(db_session, monkeypatch):
    """反例保护：旧账单不能先到先得地把当前合约的授权额分走（升级前它确实会）。"""
    await _seed_commits(db_session, [("1", 30.0)])
    await _seed_commits(db_session, [("2", 900.0)], contract=RETIRED)
    _allowance_chain(monkeypatch, 30.0)

    report = await escrow.backing_report(db_session, IDENTITY)

    assert report["secured_usdc"] == pytest.approx(30.0)
    assert await escrow.secured_usdc_for_bill(db_session, IDENTITY, "1") == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_capacity_mirror_drops_the_credit_of_a_bill_on_a_retired_contract(
    db_session, monkeypatch
):
    """合约升级把一张账单留在身后时，它撑出来的额度必须跟着消失（否则就是虚增）。"""
    await _seed_commits(db_session, [("1", 25.0)])
    _allowance_chain(monkeypatch, 50.0)
    first = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)
    assert first["credited_usdc"] == pytest.approx(25.0)

    row = await db_session.get(AllowanceCommitModel, "1")
    row.contract_address = RETIRED
    await db_session.flush()

    again = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)

    assert again["credited_usdc"] == pytest.approx(0.0)
    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_capacity_mirror_heals_a_pool_that_drifted_from_the_chain(
    db_session, monkeypatch
):
    """池子被别的东西改小过（历史 bug / 人工修库）时，对账要能把缺口补回来。

    老的「只补差额」口径看不见这种缺口：它只比 ``capacity_credited_usdc`` 的总和，
    而那个总和跟池子本身已经对不上，于是用户的可用额度会永远少一截。
    """
    await _seed_commits(db_session, [("1", 25.0)])
    _allowance_chain(monkeypatch, 25.0)
    await escrow.reconcile_capacity_mirror(db_session, IDENTITY)
    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(25.0)

    cap.available_credits = 5.0          # 错账：链上一分没变
    cap.total_locked_usdc = 5.0
    await db_session.flush()

    out = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)

    assert out["delta_usdc"] == pytest.approx(20.0)
    assert out["credited_usdc"] == pytest.approx(25.0)
    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(25.0)
    assert cap.total_locked_usdc == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_capacity_mirror_never_eats_credits_the_chain_does_not_back(
    db_session, monkeypatch
):
    """运营方直接发放的内部额度不能被对账抹掉，也不能被当成链上担保。"""
    await _seed_commits(db_session, [("1", 25.0)])
    _allowance_chain(monkeypatch, 25.0)
    db_session.add(
        CapacityModel(identity_id=IDENTITY, available_credits=225.0, total_locked_usdc=225.0)
    )
    await db_session.flush()

    out = await escrow.reconcile_capacity_mirror(db_session, IDENTITY)

    assert out["credited_usdc"] == pytest.approx(25.0)
    assert out["delta_usdc"] == pytest.approx(0.0)
    cap = await db_session.get(CapacityModel, IDENTITY)
    assert cap.available_credits == pytest.approx(225.0)
    assert cap.total_locked_usdc == pytest.approx(225.0)


@pytest.mark.asyncio
async def test_the_mirror_sweep_locks_identities_in_a_fixed_order(db_session, monkeypatch):
    """并发对账必须按同一顺序加锁，否则 Postgres 判 ABBA 死锁。

    2026-09-20 线上实测：运维脚本和 API 定时任务同时在跑，两边更新同一批账单行的顺序
    不同 —— ``DeadlockDetectedError``，其中一方整轮被回滚，那一轮账就没对上。
    这里钉死顺序：身份按 id 升序（账单按号升序由另两条用例覆盖）。
    """
    await _seed_commits(db_session, [("7", 10.0)], identity_id="identity-zz")
    await _seed_commits(db_session, [("2", 10.0)], identity_id="identity-aa",
                        wallet=OTHER_WALLET)
    _allowance_chain(monkeypatch, 10.0)
    _stub_sync(monkeypatch)

    seen: list[str] = []
    real = escrow.reconcile_capacity_mirror

    async def spy(db, identity_id):
        seen.append(identity_id)
        return await real(db, identity_id)

    monkeypatch.setattr(escrow, "reconcile_capacity_mirror", spy)
    out = await escrow.reconcile_all_capacity_mirrors(db_session)

    assert seen == ["identity-aa", "identity-zz"]
    assert {row["identity_id"] for row in out} == {"identity-aa", "identity-zz"}


@pytest.mark.asyncio
async def test_one_broken_identity_does_not_stop_the_rest_of_the_sweep(
    db_session, monkeypatch
):
    """某个身份上炸了，这一轮剩下的身份还得照常对上账。

    生产是 Postgres：出错的事务会变成 aborted，后面每条语句都跟着报
    "current transaction is aborted"。所以每个身份必须各自待在一个 SAVEPOINT 里
    （``begin_nested``）—— 否则一次死锁就让整轮自愈集体哑火。
    """
    await _seed_commits(db_session, [("7", 10.0)], identity_id="identity-zz")
    await _seed_commits(db_session, [("2", 10.0)], identity_id="identity-aa",
                        wallet=OTHER_WALLET)
    _allowance_chain(monkeypatch, 10.0)
    _stub_sync(monkeypatch)

    real = escrow.reconcile_capacity_mirror

    async def flaky(db, identity_id):
        if identity_id == "identity-aa":
            raise RuntimeError("deadlock detected")
        return await real(db, identity_id)

    monkeypatch.setattr(escrow, "reconcile_capacity_mirror", flaky)
    out = await escrow.reconcile_all_capacity_mirrors(db_session)

    assert [row["identity_id"] for row in out] == ["identity-zz"]
    cap = await db_session.get(CapacityModel, "identity-zz")
    assert cap.available_credits == pytest.approx(10.0)


# ------------------------------------------------------------------ 操作台口径


def test_fully_secured_looks_at_the_remaining_responsibility():
    """展示用的 fully_secured 只对还活着的账单有意义，比的是剩下要付的责任额。"""
    from api.routes import escrow as escrow_route

    row = AllowanceCommitModel(
        bill_id="1",
        identity_id=IDENTITY,
        wallet_address=WALLET,
        amount_usdc=80.0,
        spent_usdc=30.0,
        commit_tx_hash="0x" + "aa" * 32,
        state=escrow.IDLE,
    )

    # 划走 30 之后只剩 50 要付，授权额分到 50 就算全担保
    view = escrow_route._commit_view(row, {"secured_usdc": 50.0})
    assert view["secured_usdc"] == pytest.approx(50.0)
    assert view["fully_secured"] is True

    # 只分到 20：这 50 里有 30 是划不动的
    partial = escrow_route._commit_view(row, {"secured_usdc": 20.0})
    assert partial["fully_secured"] is False

    # 已撤销的账单不再承担责任额，不该一直被标成「缺担保」
    row.state = escrow.REVOKED
    assert escrow_route._commit_view(row, None)["fully_secured"] is True
