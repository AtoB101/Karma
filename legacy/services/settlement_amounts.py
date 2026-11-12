"""金额的单一口径 —— 先把钱落到链上最小单位，再回到 USDC。

为什么必须有这个模块：托管在链上，钱是整数最小单位；服务端记账是 float。
两边如果各用各的舍入（链上 6 位小数、账上 ``round(x, 2)``），
``released_amount + refunded_amount`` 就不再等于 ``escrow_amount`` ——
2026-09-20 实测：一张 12.345 的单子账上多报 0.005，一张 1.005 的单子账上少报 0.005。

金额只允许有一个口径，就是链上那个。所有「按比例拆分托管金额」的地方
都必须走 ``split_amounts``，不要自己 ``round(..., 2)``。
"""

from __future__ import annotations

from fastapi import HTTPException

from config.settings import settings

_DEFAULT_DECIMALS = 6


def token_decimals() -> int:
    """结算币在链上的小数位（USDC = 6）。"""
    try:
        return int(settings.settlement_token_decimals)
    except (TypeError, ValueError):
        return _DEFAULT_DECIMALS


def to_minor_units(amount_usdc: float) -> int:
    """USDC → 链上最小单位（整数）。"""
    return int(round(float(amount_usdc) * (10 ** token_decimals())))


def from_minor_units(amount_minor: int) -> float:
    """链上最小单位 → USDC。"""
    return int(amount_minor) / float(10 ** token_decimals())


def normalize_amount(amount_usdc: float) -> float:
    """把一个金额对齐到链上能表示的精度。幂等。"""
    return from_minor_units(to_minor_units(amount_usdc))


def excess_decimals(amount_usdc: float) -> bool:
    """这个金额有没有比链上能表示的多出小数位。"""
    scaled = float(amount_usdc) * (10 ** token_decimals())
    return abs(scaled - round(scaled)) >= 1e-6


def assert_token_precision(amount_usdc: float, *, field: str = "amount") -> None:
    """金额小数位不能超过链上能表示的精度 —— 多出来的那部分在链上根本不存在。

    不拦住的话，账上会记一个链上不存在的金额，对账就永远对不平。
    """
    if excess_decimals(amount_usdc):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} has more decimals than the settlement token can represent "
                f"({token_decimals()} decimals)"
            ),
        )


def split_amounts(escrow_amount: float, settled_percent: float) -> tuple[float, float]:
    """把托管金额按百分比拆成 ``(应结, 应退)``，保证两者之和**精确**等于托管金额。

    先落到最小单位取整数，再把余数整个留给退款方 —— 所以既不会出现
    「应结比托管金额还多」，也不会出现「两笔加起来对不上托管金额」。
    """
    escrow_minor = to_minor_units(escrow_amount)
    pct = float(settled_percent)
    if pct != pct:  # NaN
        pct = 0.0
    pct = max(0.0, min(100.0, pct))
    settled_minor = int(round(escrow_minor * pct / 100.0))
    settled_minor = max(0, min(escrow_minor, settled_minor))
    return from_minor_units(settled_minor), from_minor_units(escrow_minor - settled_minor)
