"""金额只能有一个口径 —— 链上最小单位。

2026-09-20 线上实测打出来的东西：
  · 一张 12.345 USDC 的单子全额结算后，账上写 released=12.35，链上只走了 12.345；
  · 一张 1.005 USDC 的单子，账上写 released=1.0 / refunded=0.0，加起来比托管少 0.005。
根因是「应结 / 应退」在账上 round 到 2 位小数，而链上是 6 位小数。
这一组测试锁住不变量：`应结 + 应退` 必须**精确**等于托管金额。
"""

from __future__ import annotations

import math

import pytest
from fastapi import HTTPException

from services.settlement_amounts import (
    assert_token_precision,
    excess_decimals,
    from_minor_units,
    normalize_amount,
    split_amounts,
    to_minor_units,
    token_decimals,
)

# 线上实际打过的那两笔，原样搬进来当回归用例
LIVE_REGRESSIONS = [
    (12.345, 100.0),
    (1.005, 100.0),
    (10.005, 100.0),
    (0.015, 100.0),
    (2.675, 100.0),
    (33.335, 100.0),
    (1234.565, 100.0),
]

GRID_AMOUNTS = [0.01, 0.1, 1.0, 1.005, 3.0, 4.0, 12.345, 99.999, 100.0, 9999.999999]
GRID_PERCENTS = [0.0, 0.000001, 1.0, 33.33, 50.0, 66.666, 99.999999, 100.0]


def test_token_decimals_is_six():
    assert token_decimals() == 6


@pytest.mark.parametrize("escrow,percent", LIVE_REGRESSIONS)
def test_full_settlement_never_exceeds_escrow(escrow, percent):
    settled, refunded = split_amounts(escrow, percent)
    assert settled <= escrow + 1e-12, (escrow, settled)
    assert refunded >= 0.0, (escrow, refunded)
    assert math.isclose(settled, escrow, abs_tol=1e-9)


@pytest.mark.parametrize("escrow", GRID_AMOUNTS)
@pytest.mark.parametrize("percent", GRID_PERCENTS)
def test_split_sums_back_to_escrow_exactly_in_minor_units(escrow, percent):
    settled, refunded = split_amounts(escrow, percent)
    assert to_minor_units(settled) + to_minor_units(refunded) == to_minor_units(escrow)
    assert settled >= 0.0 and refunded >= 0.0
    assert settled <= escrow + 1e-12


@pytest.mark.parametrize("escrow,percent,exp_settled,exp_refunded", [
    (12.345, 100.0, 12.345, 0.0),
    (1.005, 100.0, 1.005, 0.0),
    (1.005, 50.0, 0.5025, 0.5025),
    (4.0, 50.0, 2.0, 2.0),
    (0.01, 100.0, 0.01, 0.0),
    (0.01, 50.0, 0.005, 0.005),
])
def test_known_splits(escrow, percent, exp_settled, exp_refunded):
    assert split_amounts(escrow, percent) == (exp_settled, exp_refunded)


def test_percent_is_clamped():
    assert split_amounts(10.0, -5.0) == (0.0, 10.0)
    assert split_amounts(10.0, 250.0) == (10.0, 0.0)


def test_nan_percent_refunds_everything_instead_of_crashing():
    assert split_amounts(10.0, float("nan")) == (0.0, 10.0)


def test_normalize_amount_is_idempotent_and_snaps_to_token_precision():
    for v in (12.345, 0.01, 1.0, 3.0):
        assert normalize_amount(v) == v
        assert normalize_amount(normalize_amount(v)) == v
    # 链上表示不了的部分必须被抹平，不能留在账上
    assert normalize_amount(1.0000004) == 1.0
    assert from_minor_units(to_minor_units(1.0000004)) == 1.0


def test_precision_guard_accepts_chain_representable_amounts():
    for v in (0.01, 12.345, 1.005, 9999.999999, 0.000001):
        assert excess_decimals(v) is False
        assert_token_precision(v, field="escrow_amount")


def test_precision_guard_rejects_amounts_the_chain_cannot_represent():
    for v in (0.0000001, 1.0000001, 12.3456789):
        assert excess_decimals(v) is True
        with pytest.raises(HTTPException) as exc:
            assert_token_precision(v, field="escrow_amount")
        assert exc.value.status_code == 400
        assert "more decimals" in str(exc.value.detail)


def test_minor_unit_roundtrip_for_typed_values():
    for wei in (1, 5, 100000, 12345000, 1005000, 9999999999):
        assert to_minor_units(from_minor_units(wei)) == wei
