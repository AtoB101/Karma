"""罚没台账与出账状态机（G12）—— 先落账，后出账。

为什么拆成两件事
----------------
判负那一刻必须立刻有后果：**停用 + 记台账 + 扣声誉**。而**钱**的移动是另一件事 ——
它要经过链上金库合约（``KarmaVerifierBond``），可能因为金库没部署、RPC 不可用、
治理账户还没签而延后。把两件事塞进一个事务里，只会得到一个二选一：要么判负不生效，
要么在没有链上 tx 的情况下谎报「已出账」。

所以：

* 台账（``bond_slashes``）**当场写**，按（主体, 来源）唯一 —— 重复裁决是幂等 no-op；
* 状态机 ``pending -> submitted -> settled | failed``，失败可重试（``attempts`` 记账）；
* **金库没配**（``VERIFIER_BOND_VAULT_ADDRESS`` 为空）时停在 ``pending``，
  绝不写 ``settled`` —— 没有链上 tx 的「已出账」就是撒谎；
* 判负同时**当场停用主体**（节点 ``is_active=False`` / 仲裁岗质押额下调到下限之下），
  所以不存在「还没出账就先跑掉」的窗口：钱在链上的金库里锁着，动不了。

分账 80 / 20
------------
``victim_amount = amount * victim_share_bps / 10000``，余下进罚没池。
**没有可指认的受害方时（victim 钱包为空）**，本该给受害方的 80% 也进池 ——
宁可留在池里等治理认领，也不凭空指一个收款人。
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decentralized_verifier.models import BondSlash
from services import verifier_bond

logger = structlog.get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_SUBMITTED = "submitted"
STATUS_SETTLED = "settled"
STATUS_FAILED = "failed"

SETTLEABLE_STATUSES = (STATUS_SUBMITTED, STATUS_SETTLED, STATUS_FAILED)

SUBJECT_VERIFIER_NODE = "verifier_node"
SUBJECT_ARBITRATOR_ROLE = "arbitrator_role"

SOURCE_CHALLENGE = "challenge"
SOURCE_ARBITRATION_OVERTURN = "arbitration_overturn"

EPSILON = 1e-9


def _split(amount: float, *, has_victim: bool) -> tuple[float, float, int, int]:
    """把罚没额拆成（给受害方, 进池, 受害方bps, 池bps）。

    没有受害方时，本该给受害方的部分也进池 —— 池子账目永远等于罚没总额。
    """
    total = max(0.0, float(amount or 0.0))
    victim_bps = verifier_bond.victim_share_bps()
    pool_bps = verifier_bond.pool_share_bps()
    if not has_victim:
        return 0.0, total, victim_bps, pool_bps
    victim_amount = round(total * victim_bps / 10_000.0, 8)
    if victim_amount > total:
        victim_amount = total
    return victim_amount, round(total - victim_amount, 8), victim_bps, pool_bps


async def find_slash(
    db: AsyncSession, *, subject_kind: str, subject_id: str, source_kind: str, source_id: str
) -> BondSlash | None:
    q = select(BondSlash).where(
        BondSlash.subject_kind == subject_kind,
        BondSlash.subject_id == subject_id,
        BondSlash.source_kind == source_kind,
        BondSlash.source_id == source_id,
    )
    return (await db.execute(q)).scalars().first()


async def record_slash(
    db: AsyncSession,
    *,
    subject_kind: str,
    subject_id: str,
    wallet_address: str | None,
    victim_wallet_address: str | None = None,
    victim_identity_id: str | None = None,
    source_kind: str,
    source_id: str,
    amount: float,
    reason: str | None = None,
    now: datetime | None = None,
) -> tuple[BondSlash, bool]:
    """记一笔罚没。返回 ``(台账行, 是否新建)``。

    幂等：同一（主体, 来源）重复调用只写一次，第二次原样返回已有行（``created=False``）——
    重复裁决不会重复扣款，也不会重复停用。
    """
    existing = await find_slash(
        db,
        subject_kind=subject_kind,
        subject_id=subject_id,
        source_kind=source_kind,
        source_id=source_id,
    )
    if existing is not None:
        return existing, False

    cleaned_victim_wallet = (victim_wallet_address or "").strip() or None
    victim_amount, pool_amount, victim_bps, pool_bps = _split(
        amount, has_victim=bool(cleaned_victim_wallet)
    )
    row = BondSlash(
        subject_kind=subject_kind,
        subject_id=subject_id,
        wallet_address=(wallet_address or "").strip() or None,
        victim_wallet_address=cleaned_victim_wallet,
        victim_identity_id=(victim_identity_id or "").strip() or None,
        source_kind=source_kind,
        source_id=source_id,
        amount=round(max(0.0, float(amount or 0.0)), 8),
        victim_amount=victim_amount,
        pool_amount=pool_amount,
        victim_share_bps=victim_bps,
        pool_share_bps=pool_bps,
        reason=(reason or "").strip() or None,
        status=STATUS_PENDING,
        attempts=0,
        created_at=now or datetime.utcnow(),
        updated_at=now or datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    logger.info(
        "bond_slash_recorded",
        subject_kind=subject_kind,
        subject_id=subject_id,
        amount=row.amount,
        victim_amount=row.victim_amount,
        pool_amount=row.pool_amount,
        source=f"{source_kind}:{source_id}",
        status=row.status,
    )
    return row, True


async def settle_slash(
    db: AsyncSession,
    *,
    slash_id: str,
    status: str,
    tx_hash: str | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> BondSlash:
    """推进出账状态。只认 ``submitted`` / ``settled`` / ``failed``。

    ``settled`` 必须带 tx hash —— 这是本模块唯一的硬规矩：**没有 tx 就没有 settled。**
    """
    if status not in SETTLEABLE_STATUSES:
        raise ValueError(f"unsupported bond slash status: {status!r}")
    row = await db.get(BondSlash, slash_id)
    if row is None:
        raise ValueError(f"bond slash not found: {slash_id}")
    if status == STATUS_SETTLED and not (tx_hash or "").strip():
        raise ValueError("cannot mark a bond slash settled without a tx hash")

    moment = now or datetime.utcnow()
    row.status = status
    row.attempts = int(row.attempts or 0) + 1
    row.updated_at = moment
    if (tx_hash or "").strip():
        row.tx_hash = tx_hash.strip()
    row.last_error = (error or "").strip() or None
    if status == STATUS_SETTLED:
        row.settled_at = moment
    await db.flush()
    return row


async def list_slashes(
    db: AsyncSession,
    *,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[BondSlash]:
    q = select(BondSlash).order_by(BondSlash.created_at.desc())
    if subject_kind:
        q = q.where(BondSlash.subject_kind == subject_kind)
    if subject_id:
        q = q.where(BondSlash.subject_id == subject_id)
    if status:
        q = q.where(BondSlash.status == status)
    return list((await db.execute(q.limit(max(1, min(limit, 500))))).scalars().all())


async def pool_total(db: AsyncSession) -> float:
    """罚没池余额（已落账、还没分配出去的池子部分）。"""
    total = await db.scalar(
        select(func.coalesce(func.sum(BondSlash.pool_amount), 0.0)).where(
            BondSlash.status != STATUS_FAILED
        )
    )
    return round(float(total or 0.0), 8)


def slash_instructions(rows: Iterable[BondSlash]) -> list[dict[str, Any]]:
    """把待出账的台账翻成链上调用说明（供治理账户签发的 ops 脚本消费）。

    这里只产出**说明**，不签名、不发交易 —— Karma 后端不持有热钱包私钥。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.status not in (STATUS_PENDING, STATUS_FAILED):
            continue
        out.append(
            {
                "slash_id": row.id,
                "subject_kind": row.subject_kind,
                "subject_id": row.subject_id,
                "verifier": row.wallet_address,
                "victim": row.victim_wallet_address,
                "amount_usdc": row.amount,
                "victim_amount_usdc": row.victim_amount,
                "pool_amount_usdc": row.pool_amount,
                "reason": row.reason,
                "source": f"{row.source_kind}:{row.source_id}",
                "vault": verifier_bond.vault_address() or None,
            }
        )
    return out
