"""仲裁员抵押必须覆盖案值（2026-09-17 收紧）。

规则：仲裁员的质押要**严格大于** 案值 × ARBITRATION_STAKE_COVERAGE_MULTIPLE。
等号不算覆盖 —— 抵押刚好等于案值时，一次误判就能把抵押打穿。
"""

from __future__ import annotations

import pytest

from config.settings import settings
from services import arbitration_rules as arb_rules


@pytest.fixture(autouse=True)
def _reset_rules(monkeypatch):
    monkeypatch.setattr(settings, "arbitration_stake_coverage_multiple", 1.0)
    monkeypatch.setattr(settings, "arbitration_min_stake_amount", 0.0)
    yield


class _Member:
    """只带 filter_qualified_members 会用到的字段。"""

    def __init__(self, identity_id: str, stake: float, status: str = "active"):
        self.arbitrator_identity_id = identity_id
        self.stake_amount = stake
        self.status = status


def test_equal_stake_does_not_cover_case():
    # 案值 100 / 抵押 100：不算覆盖，必须严格大于。
    assert arb_rules.stake_covers_case(100.0, 100.0) is False
    assert arb_rules.stake_covers_case(100.0001, 100.0) is True


def test_smaller_stake_never_covers():
    assert arb_rules.stake_covers_case(10.0, 100.0) is False
    assert arb_rules.stake_covers_case(99.999, 100.0) is False


def test_zero_case_value_only_needs_positive_stake():
    assert arb_rules.stake_covers_case(0.0, 0.0) is False
    assert arb_rules.stake_covers_case(1.0, 0.0) is True
    assert arb_rules.stake_covers_case(1.0, -5.0) is True


def test_bad_input_is_not_covered():
    assert arb_rules.stake_covers_case(None, 100.0) is False
    assert arb_rules.stake_covers_case("not-a-number", 100.0) is False


def test_multiple_leaves_a_safety_margin(monkeypatch):
    monkeypatch.setattr(settings, "arbitration_stake_coverage_multiple", 1.5)
    assert arb_rules.stake_covers_case(150.0, 100.0) is False  # 1.5 倍同样要求严格大于
    assert arb_rules.stake_covers_case(150.0001, 100.0) is True


def test_multiple_below_one_is_clamped(monkeypatch):
    # 配置被误设成 0.5 也不允许「抵押 < 案值」的人入庭（下限锁在 1.0）。
    monkeypatch.setattr(settings, "arbitration_stake_coverage_multiple", 0.5)
    assert arb_rules.stake_coverage_multiple() == 1.0
    assert arb_rules.stake_covers_case(60.0, 100.0) is False


def test_filter_drops_undercollateralized_members():
    members = [
        _Member("rich", 150.0),
        _Member("poor", 10.0),
        _Member("exact", 100.0),  # 刚好等于案值：不算覆盖
    ]
    kept = arb_rules.filter_qualified_members(members, conflicted=set(), case_value=100.0)
    assert [m.arbitrator_identity_id for m in kept] == ["rich"]


def test_filter_without_case_value_keeps_old_behaviour():
    members = [_Member("poor", 10.0)]
    kept = arb_rules.filter_qualified_members(members, conflicted=set())
    assert [m.arbitrator_identity_id for m in kept] == ["poor"]


def test_filter_still_recuses_parties_and_skips_inactive():
    members = [
        _Member("party", 500.0),
        _Member("asleep", 500.0, status="paused"),
        _Member("ok", 500.0),
    ]
    kept = arb_rules.filter_qualified_members(
        members, conflicted={"party"}, exclude_ids={"ok"}, case_value=100.0
    )
    assert kept == []
