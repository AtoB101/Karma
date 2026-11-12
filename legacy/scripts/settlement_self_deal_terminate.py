#!/usr/bin/env python3
"""自成交脏单：先出清单，再走审计过的状态机把它取消。

自成交的单**永远绑不上**（链上 ``SameOwner()`` 只看钱包地址，是决定性的，不是抖动）。
接单那一刻的硬闸（``assert_parties_not_self_dealing``）现在已经挡住了新的；但历史遗留的
那张（settlement ``97f0dc0e``，2026-10-13）还卡在 ``in_progress``：它每一格出口都要补绑，
补绑必 409，于是永久没有出口。详见
``security/audit/2026-10-14-self-deal-settlement-recovery-plan.md``。

这个脚本把「能合法走到取消、且判定为自成交」的单列出来；``--apply`` 才真的取消 ——
走的是和 agent 下单同一条 ``apply_settlement_transition``（写 ``settlement_transition_audits``，
链上一笔都不发：这种单从未绑过，``cancel_for_task`` 对它返回 ``unbound``）。

用法::

    python3 scripts/settlement_self_deal_terminate.py                    # 清单（dry-run，默认）
    python3 scripts/settlement_self_deal_terminate.py --settlement 97f0dc0e-…   # 只看这一单
    python3 scripts/settlement_self_deal_terminate.py --apply            # 真取消

注意：这里只取消**判定为自成交**的单，别的单一张都不碰。
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

from core.schemas import TaskStatus
from core.settlement.engine import can_transition, canonical_task_status
from db.models.orm import SettlementModel
from db.session import AsyncSessionLocal
from db.stores.settlement_store import PostgresSettlementStore

_ROUTE = "/ops/self-deal-terminate"
_ACTOR = "ops-self-deal-terminate"


async def _eligible(db, *, settlement_id: str | None) -> list[dict]:
    """能合法走到取消、且判定为自成交的结算单。"""
    from services.chain import escrow_settlement

    stmt = select(SettlementModel)
    if settlement_id:
        stmt = stmt.where(SettlementModel.settlement_id == settlement_id)
    stmt = stmt.order_by(SettlementModel.created_at)

    found: list[dict] = []
    for row in (await db.execute(stmt)).scalars().all():
        status = canonical_task_status(row.status)
        if not can_transition(status, TaskStatus.CANCELLED):
            continue
        hit = await escrow_settlement.detect_self_dealing(
            db,
            buyer_identity_id=row.client_agent_id,
            seller_identity_id=row.worker_agent_id,
        )
        if hit is None:
            continue
        found.append(
            {
                "settlement_id": row.settlement_id,
                "task_id": row.task_id,
                "status": status.value,
                "onchain_status": row.onchain_status,
                "amount": row.escrow_amount,
                "reason": hit[0],
                "detail": hit[1],
            }
        )
    return found


async def _amain(args) -> int:
    async with AsyncSessionLocal() as db:
        rows = await _eligible(db, settlement_id=args.settlement)

    print("自成交脏单清单（能合法取消 + 判定为自成交）")
    print("settlement_id | task_id | status | onchain_status | amount | 判定")
    if not rows:
        print("(空)")
        return 0
    for r in rows:
        print(
            f"{r['settlement_id']} | {r['task_id']} | {r['status']} | "
            f"{r['onchain_status']} | {r['amount']} | {r['reason']}={r['detail']}"
        )

    if not args.apply:
        print()
        print(f"dry-run：{len(rows)} 条可取消。要真取消加 --apply。")
        return 0

    from services.settlement_transitions import apply_settlement_transition

    print()
    print("开始取消（走 apply_settlement_transition）…")
    failures = 0
    for r in rows:
        async with AsyncSessionLocal() as db:
            store = PostgresSettlementStore(db)
            state = await store.get(r["task_id"])
            if state is None:
                print(f"  {r['settlement_id']}: 台账里已不在（跳过）")
                continue
            try:
                state = await apply_settlement_transition(
                    db=db,
                    store=store,
                    state=state,
                    target_status=TaskStatus.CANCELLED,
                    reason="ops: self-deal settlement terminated (can never bind on-chain)",
                    route_path=_ROUTE,
                    actor_id=_ACTOR,
                )
            except Exception as exc:  # noqa: BLE001 - 一条失败不影响别的
                failures += 1
                print(f"  {r['settlement_id']}: 失败 {exc}")
                await db.rollback()
                continue
            await db.commit()
            print(f"  {r['settlement_id']}: -> {canonical_task_status(state.status).value}")
    print(f"完成：成功 {len(rows) - failures}，失败 {failures}。")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description="自成交脏单清单 / 取消")
    p.add_argument("--settlement", default=None, help="只看这个 settlement_id")
    p.add_argument("--apply", action="store_true", help="真的取消（默认只打印清单）")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
