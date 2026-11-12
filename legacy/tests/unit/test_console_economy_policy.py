"""操作台收益口径（``/v1/console/economy-policy``）。

这个接口存在的唯一理由是：把「验证者 / 仲裁员能拿多少、要先押多少」摊成一处口径。
所以这里钉四件事：

1. 没有会话就 401 —— 不匿名回一份「政策」；
2. 普通身份能读到，且明确是 ``policy-preview``（口径已定、结算还没接上），
   页面不会把它误当成「你现在就能赚到」；
3. 夹逼（clamp）算得对：低于下限抬到下限、高于上限压回上限，配置写反也不出负数；
4. 「谁能自助开通」这类**在任状态**必须现读现算，与真正的闸门逐字一致 ——
   页面说「可以申请」而后端 403，就是这套口径发霉的开始。
"""
from __future__ import annotations

import pytest

from config.settings import settings
from services import arbitration_rules, economy_policy


def _keys(actor: str, secret: str = "supersecret123456") -> dict[str, str]:
    return {"X-Karma-Api-Key": "karma_%s_%s" % (actor, secret)}


@pytest.fixture
def restore_policy():
    """口径与开关都是进程级 settings，用完必须还原。"""
    saved = (
        settings.auth_api_keys,
        settings.settlement_fee_bps,
        settings.verifier_network_min_case_usdc,
        settings.verifier_reward_bps,
        settings.verifier_reward_min_usdc,
        settings.verifier_reward_max_usdc,
        settings.verifier_quorum_required,
        settings.verifier_quorum_total,
        settings.arbitration_fee_bps,
        settings.arbitration_fee_min_usdc,
        settings.arbitration_fee_max_usdc,
        settings.arbitration_fee_loser_pays,
        settings.arbitration_slash_multiple,
        settings.arbitration_pool_open_join,
        settings.governance_open_join,
    )
    try:
        yield
    finally:
        (
            settings.auth_api_keys,
            settings.settlement_fee_bps,
            settings.verifier_network_min_case_usdc,
            settings.verifier_reward_bps,
            settings.verifier_reward_min_usdc,
            settings.verifier_reward_max_usdc,
            settings.verifier_quorum_required,
            settings.verifier_quorum_total,
            settings.arbitration_fee_bps,
            settings.arbitration_fee_min_usdc,
            settings.arbitration_fee_max_usdc,
            settings.arbitration_fee_loser_pays,
            settings.arbitration_slash_multiple,
            settings.arbitration_pool_open_join,
            settings.governance_open_join,
        ) = saved


@pytest.mark.asyncio
async def test_policy_requires_a_session(client):
    resp = await client.get("/v1/console/economy-policy")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_plain_identity_can_read_the_published_policy(client, restore_policy):
    """公示不是机密：普通身份读得到，但必须被标成「还没接上结算」。"""
    settings.auth_api_keys = "pol-plain:supersecret123456"

    resp = await client.get("/v1/console/economy-policy", headers=_keys("pol-plain"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "policy-preview"
    assert body["verifier"]["reward_bps"] == 1.0
    assert body["arbitrator"]["fee_bps"] == 150.0
    assert body["arbitrator"]["loser_pays"] is True
    assert body["preview"]["verifier_paid_seats"] == 3


@pytest.mark.asyncio
async def test_sample_case_preview_is_computed_from_the_same_policy(client, restore_policy):
    """样例案值 100 USDC：出证价吃下限、立案费落在区间内。"""
    settings.auth_api_keys = "pol-math:supersecret123456"

    resp = await client.get(
        "/v1/console/economy-policy?case_value=100", headers=_keys("pol-math")
    )
    assert resp.status_code == 200
    preview = resp.json()["preview"]
    # 100 x 1bp = 0.01，低于下限 0.02 -> 抬到下限；三席合计 0.06。
    assert preview["verifier_reward_per_attestation_usdc"] == 0.02
    assert preview["verifier_reward_per_panel_usdc"] == 0.06
    # 100 x 1.5% = 1.5，落在 [0.5, 100] 中间，原样。
    assert preview["arbitrator_fee_usdc"] == 1.5


def test_clamp_holds_both_ends_and_never_goes_negative(restore_policy):
    assert economy_policy.case_reward(100) == 0.02      # 下限
    assert economy_policy.case_reward(1000) == 0.1      # 比例段
    assert economy_policy.case_reward(10_000_000) == 1.0  # 上限
    assert economy_policy.case_reward(-5) == 0.02
    assert economy_policy.case_fee(1) == 0.5            # 下限
    assert economy_policy.case_fee(10_000_000) == 100.0  # 上限

    # 配置写反（下限 > 上限）也不许算出负数或穿过区间。
    settings.verifier_reward_min_usdc = 5.0
    settings.verifier_reward_max_usdc = 1.0
    assert economy_policy.case_reward(1000) == 1.0


def test_policy_reads_the_arbitration_gates_instead_of_copying_them(restore_policy):
    """在任状态现读现算：页面说的「能不能自助开通」必须与闸门同一处。"""
    settings.arbitration_pool_open_join = False
    settings.governance_open_join = False
    block = economy_policy.snapshot()["arbitrator"]
    assert block["open_join"] is False
    assert block["self_serve_profile"] is False

    settings.arbitration_pool_open_join = True
    settings.governance_open_join = True
    block = economy_policy.snapshot()["arbitrator"]
    assert block["open_join"] is True
    assert block["self_serve_profile"] is True

    # 庭人数与覆盖倍数不许在这一层另立一套。
    lo, hi = arbitration_rules.panel_bounds()
    assert (block["panel_min"], block["panel_max"]) == (lo, hi)
    assert block["coverage_multiple"] == arbitration_rules.stake_coverage_multiple()
