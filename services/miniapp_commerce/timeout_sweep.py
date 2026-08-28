"""超时托管资金自动退款 sweep。

背景（资金安全核查 P2-8）：offchain 模式下 LOCKED 订单若无人推进，
退款此前需要人工触发——挂死订单会让用户资金无限期滞留。
本模块扫描超过 ESCROW_TIMEOUT_SWEEP_HOURS 仍停留在
LOCKED / EXECUTED / EVIDENCE_SUBMITTED 的订单，自动走保守退款：

- 订单状态 -> REFUNDED（复用 orders.mark_refunded，已结算订单拒绝退款）
- 账单状态 -> refunded（pipeline.update_bill，幂等）
- 争议中（fulfillment_status == DISPUTED）的订单跳过——争议有自己的
  仲裁与超时路径，sweep 不得抢跑仲裁。
- VERIFIED 状态跳过——验收已通过，资金应走结算 finalize，而不是退款。

触发方式：
- Celery beat：worker.tasks.sweep_timed_out_escrows（每小时）
- 手动：python scripts/maintenance/sweep_timed_out_escrows.py
"""
from __future__ import annotations

import logging
import time

from services.miniapp_commerce import orders, pipeline

logger = logging.getLogger("karma.timeout_sweep")

# sweep 适用的"卡在执行链路上"的状态：锁了钱但验收从未通过
_SWEEPABLE_STATUSES = {"LOCKED", "EXECUTED", "EVIDENCE_SUBMITTED"}


def sweep_timed_out_escrows(
    *,
    timeout_hours: int | None = None,
    now: float | None = None,
) -> dict:
    """扫描并退款超时订单。返回统计信息（幂等，可重复调用）。

    Returns:
        {"refunded": [order_id...], "skipped_disputed": n, "scanned": n}
    """
    from config.settings import settings

    hours = timeout_hours if timeout_hours is not None else settings.escrow_timeout_sweep_hours
    if hours <= 0:
        return {"refunded": [], "skipped_disputed": 0, "scanned": 0, "disabled": True}

    cutoff = (now if now is not None else time.time()) - hours * 3600
    refunded: list[str] = []
    skipped_disputed = 0
    scanned = 0

    for order in list(orders._ORDERS.values()):
        if order.status.value not in _SWEEPABLE_STATUSES:
            continue
        scanned += 1
        # 争议中的订单交给仲裁路径，sweep 不碰
        if order.fulfillment_status.value == "DISPUTED":
            skipped_disputed += 1
            continue
        # 以 updated_at 判定停滞（锁仓/推进都会 touch）
        if (order.updated_at or 0) > cutoff:
            continue
        try:
            orders.mark_refunded(order.order_id)
        except (KeyError, ValueError):
            # 订单消失 / 已结算——人工路径兜底，跳过即可
            continue
        try:
            pipeline.update_bill(order.order_id, status="refunded")
        except KeyError:
            pass
        refunded.append(order.order_id)
        logger.info(
            "timeout_refund",
            extra={"order_id": order.order_id, "hours": hours},
        )

    if refunded:
        logger.info(
            "timeout_sweep_complete",
            extra={"refunded_count": len(refunded), "skipped_disputed": skipped_disputed},
        )
    return {
        "refunded": refunded,
        "skipped_disputed": skipped_disputed,
        "scanned": scanned,
    }
