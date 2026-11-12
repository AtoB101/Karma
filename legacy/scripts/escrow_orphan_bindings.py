#!/usr/bin/env python3
"""孤儿绑定：先出清单，再按 binding 收尾。

一个 task 有多条绑定时，`cancel/submit/slash_for_task` 只会碰**最新那条**（它们内部都
是 ``_find_binding(task_id)``）。老的那条链上还占着买方的授权额，谁也解不开 —— 线上
实测（2026-10-14）task 3327dbc2 / 06797bd4 / 4538ae75 各有一条（92 / 161 / 171），
每轮 tick 打一条 ``escrow_stranded_reap_noop``。

这个脚本把「够格收的孤儿」列出来；``--apply`` 才真的收（链上发一笔 ``cancelBinding``，
花 operator 的 gas）。收尾本身走 ``escrow_settlement.cancel_binding_row``：只动这一条
绑定，**不回写 settlements**（兄弟绑定那格是 settled，不能被盖成 cancelled）。

用法::

    python3 scripts/escrow_orphan_bindings.py                 # 清单（dry-run，默认）
    python3 scripts/escrow_orphan_bindings.py --task <task_id>
    python3 scripts/escrow_orphan_bindings.py --binding 92
    python3 scripts/escrow_orphan_bindings.py --apply         # 真收

注意：自动收尾还有一个总开关 ``ESCROW_ORPHAN_BINDING_CANCEL_ENABLED``（默认关）。
这个脚本是**显式人工动作**，不受那个开关限制。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from db.models.orm import EscrowBindingModel, SettlementModel
from db.session import AsyncSessionLocal


async def _eligible(db, *, task_id: str | None, binding_id: str | None) -> list[dict]:
    """够格自动收的孤儿绑定清单。判据与 ``reap_stranded`` 里那条路**共用**同一个纯函数。"""
    from services.chain import escrow_autosettle as autosettle
    from services.chain import escrow_settlement

    stmt = select(EscrowBindingModel).where(EscrowBindingModel.state == "active")
    if binding_id:
        stmt = stmt.where(EscrowBindingModel.binding_id == binding_id)
    if task_id:
        stmt = stmt.where(EscrowBindingModel.task_id == task_id)
    stmt = stmt.order_by(EscrowBindingModel.created_at)

    found: list[dict] = []
    for row in (await db.execute(stmt)).scalars().all():
        settlement = (
            await db.execute(
                select(SettlementModel).where(SettlementModel.task_id == row.task_id)
            )
        ).scalars().first()
        if settlement is None:
            continue
        status = (settlement.status or "").strip().lower()
        if not autosettle._orphan_cancel_allowed(status, settlement.onchain_status):
            continue
        newest = await escrow_settlement.newest_binding_for_task(db, task_id=row.task_id)
        found.append(
            {
                "binding_id": row.binding_id,
                "task_id": row.task_id,
                "amount_usdc": row.amount_usdc,
                "contract_address": row.contract_address,
                "settlement_status": status,
                "onchain_status": settlement.onchain_status,
                "newest_binding_id": None if newest is None else newest.binding_id,
                "is_orphan": newest is not None and newest.binding_id != row.binding_id,
            }
        )
    return found


async def _amain(args) -> int:
    async with AsyncSessionLocal() as db:
        rows = await _eligible(db, task_id=args.task, binding_id=args.binding)

    print("孤儿绑定清单（state=active 且该 task 的钱已有结论）")
    print("binding_id | task_id | amount | 结算 status/onchain | 最新绑定 | 是孤儿")
    if not rows:
        print("(空)")
        return 0
    for r in rows:
        flag = "是" if r["is_orphan"] else "否（就是最新那条，别用这个脚本收）"
        print(
            f"{r['binding_id']:<10} | {r['task_id']} | {r['amount_usdc']:<6} | "
            f"{r['settlement_status']} / {r['onchain_status']} | {r['newest_binding_id']} | {flag}"
        )

    targets = [r for r in rows if r["is_orphan"]]
    if not args.apply:
        print()
        print(f"dry-run：{len(targets)} 条可收。要真收加 --apply（链上会发 cancelBinding）。")
        return 0
    if not targets:
        print()
        print("没有够格的孤儿可收。")
        return 0

    from services.chain import escrow_settlement

    print()
    print("开始收尾（按 binding）…")
    failures = 0
    for r in targets:
        async with AsyncSessionLocal() as db:
            row = await db.get(EscrowBindingModel, r["binding_id"])
            if row is None:
                print(f"  {r['binding_id']}: 已不在（跳过）")
                continue
            try:
                out = await escrow_settlement.cancel_binding_row(
                    db, row=row, reason="ops-manual"
                )
            except Exception as exc:  # noqa: BLE001 - 一条失败不影响别的
                failures += 1
                print(f"  {r['binding_id']}: 失败 {exc}")
                await db.rollback()
                continue
            await db.commit()
            print(f"  {r['binding_id']}: {out}")
    print(f"完成：成功 {len(targets) - failures}，失败 {failures}。")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description="孤儿绑定清单 / 按 binding 收尾")
    p.add_argument("--task", default=None, help="只看这个 task_id")
    p.add_argument("--binding", default=None, help="只看这个 binding_id")
    p.add_argument("--apply", action="store_true", help="真的收（默认只打印清单）")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
