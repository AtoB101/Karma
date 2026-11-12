"""结算回滚赔付台账（④-B2）—— 谁该退谁多少、由金库哪一路出账。

背景
----
链上没有「把钱倒回来」的原语（``docs/ARBITRATION_SETTLEMENT_REVERSAL.md`` §2.3）：
``SETTLED`` / ``REFUNDED`` 是**终局**。所以「裁决被推翻」这件事的后果不是「回滚」，
而是**一笔债**：欠受害方多少、这笔债由金库哪一路出账、已经真到账了多少。

三条硬规矩
----------
1. **推定受害方与欠款额**（``presume_victim``）：按案件的 ``decided_outcome`` 与链上
   绑定推出来，**不采信调用方口述** —— 否则谁都能把赔款指到自己钱包。
2. **没有链上 tx，就没有 ``settled``、``paid_amount`` 一个子儿都不动**
   （``credit_from_settled_slash``）—— 与 ``services/bond_slash.py`` 同一条硬规矩。
   账上的「已赔」必须对应一笔真的转账，而不是运维手拄的一个字符串。
3. **幂等**：按（案件, 受害方）唯一，重复 ``/overturn`` 不会重复计债。

出账口径（用户裁定 2026-10-15）
------------------------------
**一律由金库出账**，不记平台债：

* ``bench_bond``：金库内「被推翻那一庭的质押」先出 —— ④-B1 已经打通的真链通路
  （``bond_slashes`` → 治理账户 ``slash(verifier, victim, …)`` → 受害方拿
  ``victimShareBps``）；
* ``slash_pool``：该庭没有可罚质押时，记金库罚没池（同属金库；把池子钱转给指定
  受害方的那条原语还没有，归 ④-B3）；
* ``platform_debt``：本阶段**不写这个值**（用户裁定：由金库出账），保留在词汇表里
  只为如实描述历史数据。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decentralized_verifier.models import BondSlash, SettlementReversal
from services import bond_slash

logger = structlog.get_logger(__name__)

# ── 出账口径（用户裁定 2026-10-15：一律由金库出账） ─────────────────────────
FUNDING_BENCH_BOND = "bench_bond"
FUNDING_SLASH_POOL = "slash_pool"
FUNDING_PLATFORM_DEBT = "platform_debt"
FUNDING_SOURCES = (FUNDING_BENCH_BOND, FUNDING_SLASH_POOL, FUNDING_PLATFORM_DEBT)

# ── 状态机（与 bond_slashes 同名同义） ────────────────────────────────────
STATUS_PENDING = bond_slash.STATUS_PENDING
STATUS_SUBMITTED = bond_slash.STATUS_SUBMITTED
STATUS_SETTLED = bond_slash.STATUS_SETTLED
STATUS_FAILED = bond_slash.STATUS_FAILED

EPSILON = 1e-9

# ── 链上托管绑定状态（**与 services/chain/allowance_escrow.py::BINDING_STATE 同源**；
#    tests/unit/test_settlement_reversals.py 有一条守卫用例钉住两边不许漂移） ──
CHAIN_NONE = 0
CHAIN_ACTIVE = 1
CHAIN_FINALIZING = 2
CHAIN_SETTLED = 3
CHAIN_SLASHED = 4
CHAIN_CANCELLED = 5
CHAIN_DISPUTED = 6

#: 分档：钱动没动，决定要不要建赔付台账。
BUCKET_NOT_MOVED = "not_moved"  # active(1) / disputed(6)：钱没动 → 零成本回滚走 /appeal
BUCKET_IN_WINDOW = "in_window"  # finalizing(2)：钱在窗口里还没走 → 建台账、等落定
BUCKET_MOVED = "moved"          # settled(3) / slashed(4)：钱动了 → 进赔付通道
BUCKET_UNKNOWN = "unknown"      # 链上读不到 / 不认识的状态 → 默认拒绝

#: ``/overturn`` 响应里 ``settlement_reversal`` 的取值（契约见 docs §11.6）。
#: 老契约里的 ``not_performed`` **已随本阶段落地移除**：现在这条路上只有「建了账 / 没建账」两种如实回答。
REVERSAL_RECORDED = "recorded"
REVERSAL_NOT_MOVED = "not_moved"
REVERSAL_NO_BINDING = "no_binding"
REVERSAL_SELF_DEALING = "self_dealing"
REVERSAL_OUTCOMES = (
    REVERSAL_RECORDED,
    REVERSAL_NOT_MOVED,
    REVERSAL_NO_BINDING,
    REVERSAL_SELF_DEALING,
)

#: 判决口径（core.schemas.ArbitrationVoteDecision 的值，这里按字面量对齐）。
OUTCOME_BUYER_WINS = "buyer_wins"
OUTCOME_SELLER_WINS = "seller_wins"
OUTCOME_PARTIAL = "partial"


class SettlementReversalError(Exception):
    """带 HTTP 语义的领域错误（与 ``escrow_settlement.EscrowSettlementError`` 同形）。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class PresumedVictim:
    """从案件 + 链上绑定**推**出来的受害方与欠款额。"""

    identity_id: str | None
    owed_amount: float
    basis: str


def chain_state_int(state: Any) -> int | None:
    """把链上状态读成 int；读不到 / 读不出一个整数 → ``None``（调用方一律默认拒绝）。"""
    try:
        return int(state)
    except (TypeError, ValueError):
        return None


def bucket_of_chain_state(state: Any) -> str:
    """把链上状态映射到分档。读不到（``None``）/ 不认识 → ``unknown``（默认拒绝）。"""
    value = chain_state_int(state)
    if value is None:
        return BUCKET_UNKNOWN
    if value in (CHAIN_ACTIVE, CHAIN_DISPUTED):
        return BUCKET_NOT_MOVED
    if value == CHAIN_FINALIZING:
        return BUCKET_IN_WINDOW
    if value in (CHAIN_SETTLED, CHAIN_SLASHED):
        return BUCKET_MOVED
    return BUCKET_UNKNOWN


def presume_victim(
    *, decided_outcome: str | None, binding: Any, chain_state: Any = None
) -> PresumedVictim:
    """推定受害方与欠款额（**纯函数**，不碰库不碰链）。

    方向
    ----
    ``/overturn`` 推翻的是**已经生效的那个判决**，所以要赔的是「被这个错判害了的人」：

    * ``buyer_wins`` → 货款没付给卖方、而且卖方质押被划 → **受害方 = 卖方**；
    * ``seller_wins`` → 货款已经放给卖方 → **受害方 = 买方**；
    * ``partial`` → **一律 409**（用户裁定：细则未定期间不猜比例）。

    金额
    ----
    ``owed = 货物金额 + 被误划的质押``（用户裁定 2026-10-15：全额口径，由金库承担）。
    质押只在**链上确实被划**（``slashed``）时计入 —— 没划就不算欠款，不虚报。
    """
    outcome = (decided_outcome or "").strip()
    if outcome == OUTCOME_PARTIAL:
        raise SettlementReversalError(
            409,
            "partial 判决的结算回滚细则未定：本阶段一律拒绝，不猜一个比例出来"
            "（见 docs/ARBITRATION_SETTLEMENT_REVERSAL.md §11.7）",
        )
    if outcome not in (OUTCOME_BUYER_WINS, OUTCOME_SELLER_WINS):
        raise SettlementReversalError(
            409,
            f"无法从判决 {outcome!r} 推定受害方：只认 buyer_wins / seller_wins，"
            "其余一律拒绝，不编一个收款人",
        )

    if outcome == OUTCOME_BUYER_WINS:
        victim_identity = _clean(getattr(binding, "seller_identity_id", None))
        stakes_lost = True
    else:
        victim_identity = _clean(getattr(binding, "buyer_identity_id", None))
        stakes_lost = False

    amount = max(0.0, float(getattr(binding, "amount_usdc", 0.0) or 0.0))
    stake = max(0.0, float(getattr(binding, "stake_usdc", 0.0) or 0.0))
    slashed = chain_state_int(chain_state) == CHAIN_SLASHED
    owed = round(amount + (stake if (stakes_lost and slashed) else 0.0), 8)

    parts = [f"判决 {outcome} 被推翻", f"货物金额 {amount:g}"]
    if stakes_lost and slashed:
        parts.append(f"加被误划的质押 {stake:g}（链上已 slashed）")
    elif stakes_lost:
        parts.append("质押未被划走，不计入欠款")
    basis = "；".join(parts)
    return PresumedVictim(identity_id=victim_identity, owed_amount=owed, basis=basis)


def default_funding_source(*, bench_bonded: bool) -> str:
    """出账口径：金库内先出被推翻那一庭的质押，没有可罚质押时记金库罚没池。

    两者**都属于金库**（用户裁定：由金库出账，不记平台债 ``platform_debt``）。
    """
    return FUNDING_BENCH_BOND if bench_bonded else FUNDING_SLASH_POOL


def _clean(value: Any) -> str | None:
    text = (str(value) if value is not None else "").strip()
    return text or None


def credited_tx_set(row: SettlementReversal) -> set[str]:
    """这台账已经记进 ``paid_amount`` 的那些 tx（小写）。"""
    return {
        part.strip().lower()
        for part in (row.credited_txs or "").split("\n")
        if part.strip()
    }


def _mark_credited(row: SettlementReversal, tx_hash: str) -> None:
    seen = credited_tx_set(row)
    seen.add(tx_hash.strip().lower())
    row.credited_txs = "\n".join(sorted(seen))


async def find_reversal(
    db: AsyncSession, *, case_id: str, victim_identity_id: str | None
) -> SettlementReversal | None:
    """按（案件, 受害方）取账 —— ``victim_identity_id`` 为空时按 ``IS NULL`` 比（进程内自洽）。"""
    q = select(SettlementReversal).where(SettlementReversal.case_id == case_id)
    if victim_identity_id is None:
        q = q.where(SettlementReversal.victim_identity_id.is_(None))
    else:
        q = q.where(SettlementReversal.victim_identity_id == victim_identity_id)
    return (await db.execute(q)).scalars().first()


async def record_reversal(
    db: AsyncSession,
    *,
    case_id: str,
    task_id: str,
    binding_id: str | None,
    victim_identity_id: str | None,
    victim_wallet: str | None,
    owed_amount: float,
    funding_source: str,
    note: str | None = None,
    now: datetime | None = None,
) -> tuple[SettlementReversal, bool]:
    """记一笔「欠受害方多少」。返回 ``(台账行, 是否新建)``。

    幂等：同一（案件, 受害方）重复调用只写一次，第二次原样返回已有行 ——
    重复 ``/overturn`` 不会重复计债。
    """
    if funding_source not in FUNDING_SOURCES:
        raise SettlementReversalError(500, f"unknown funding source: {funding_source!r}")

    existing = await find_reversal(db, case_id=case_id, victim_identity_id=victim_identity_id)
    if existing is not None:
        return existing, False

    moment = now or datetime.utcnow()
    row = SettlementReversal(
        case_id=case_id,
        task_id=task_id,
        binding_id=_clean(binding_id),
        victim_identity_id=_clean(victim_identity_id),
        victim_wallet=_clean(victim_wallet),
        owed_amount=round(max(0.0, float(owed_amount or 0.0)), 8),
        paid_amount=0.0,
        funding_source=funding_source,
        status=STATUS_PENDING,
        attempts=0,
        note=_clean(note),
        created_at=moment,
        updated_at=moment,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "settlement_reversal_recorded",
        reversal_id=row.reversal_id,
        case_id=case_id,
        victim_identity_id=row.victim_identity_id,
        victim_wallet=row.victim_wallet,
        owed_amount=row.owed_amount,
        funding_source=funding_source,
    )
    return row, True


async def settle_reversal(
    db: AsyncSession,
    *,
    reversal_id: str,
    status: str,
    tx_hash: str | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> SettlementReversal:
    """推进出账状态。只认 ``submitted`` / ``settled`` / ``failed``。

    ``settled`` 必须带 tx hash —— **没有 tx 就没有 settled。**
    """
    if status not in bond_slash.SETTLEABLE_STATUSES:
        raise SettlementReversalError(400, f"unsupported settlement reversal status: {status!r}")
    row = await db.get(SettlementReversal, reversal_id)
    if row is None:
        raise SettlementReversalError(404, f"settlement reversal not found: {reversal_id}")
    if status == STATUS_SETTLED and not _clean(tx_hash):
        raise SettlementReversalError(
            409, "cannot mark a settlement reversal settled without a tx hash"
        )

    moment = now or datetime.utcnow()
    row.status = status
    row.attempts = int(row.attempts or 0) + 1
    row.updated_at = moment
    if _clean(tx_hash):
        row.tx_hash = _clean(tx_hash)
    row.last_error = _clean(error)
    if status == STATUS_SETTLED:
        row.settled_at = moment
    await db.flush()
    return row


async def credit_from_settled_slash(
    db: AsyncSession, *, slash: BondSlash, chain_proof: dict[str, Any], now: datetime | None = None
) -> SettlementReversal | None:
    """一笔**已 settled 且回链核过**的罚没 → 记成对应台账的实付。

    这是 ``paid_amount`` **唯一**的增加入口，两条都要满足，缺一不可（见 §11.5）：

    * 该案 ``bond_slashes`` 行已经 ``settled``（有链上 tx）；
    * 那条 tx **回链核过**（``chain_proof`` 来自 ``verify_slash_tx``：被罚钱包 / 受害方 /
      金额逐项对得上）。

    返回更新后的台账行；这笔罚没与任何台账无关（不是推翻来源 / 找不到受害方那一行 /
    受害方份额为 0）时返回 ``None`` —— 不凭空给谁记一笔已赔。
    """
    if (slash.source_kind or "") != bond_slash.SOURCE_ARBITRATION_OVERTURN:
        return None
    if (slash.status or "") != bond_slash.STATUS_SETTLED:
        raise SettlementReversalError(
            409,
            f"cannot credit a reversal from a bond slash that is not settled: {slash.status!r}",
        )
    tx_hash = _clean(slash.tx_hash)
    if not tx_hash:
        raise SettlementReversalError(
            409, "cannot credit a reversal from a settled bond slash with no tx hash"
        )
    if not chain_proof:
        raise SettlementReversalError(
            409, "cannot credit a reversal without re-verifying the tx on-chain"
        )

    row = await find_reversal(
        db, case_id=str(slash.source_id or ""), victim_identity_id=slash.victim_identity_id
    )
    if row is None and _clean(slash.victim_wallet_address):
        # 受害方身份没落上（历史行），退一步按钱包找 —— 找不到就如实停住。
        q = select(SettlementReversal).where(
            SettlementReversal.case_id == str(slash.source_id or ""),
            func.lower(SettlementReversal.victim_wallet) == slash.victim_wallet_address.lower(),
        )
        row = (await db.execute(q)).scalars().first()
    if row is None:
        return None

    proof_tx = str(chain_proof.get("tx_hash") or "").strip().lower()
    if proof_tx and proof_tx != tx_hash.lower():
        raise SettlementReversalError(
            409,
            f"on-chain proof is for tx {proof_tx}, not for the settled tx {tx_hash.lower()}",
        )
    proof_victim = str(chain_proof.get("victim") or "").strip().lower()
    ledger_victim = (row.victim_wallet or "").strip().lower()
    if proof_victim and ledger_victim and proof_victim != ledger_victim:
        raise SettlementReversalError(
            409,
            f"the on-chain tx paid {proof_victim}, not the victim on this ledger row "
            f"({ledger_victim})",
        )
    expected = float(slash.amount or 0.0)
    got = float(chain_proof.get("amount_usdc") or 0.0)
    if abs(got - expected) > 1e-6:
        raise SettlementReversalError(
            409,
            f"the on-chain tx slashed {got:g}, but the ledger row says {expected:g}",
        )

    if tx_hash.lower() in credited_tx_set(row):
        # 同一笔 tx 重复回写（例如把已 settled 的行再 POST 一次）：**不再记一次**。
        logger.info(
            "settlement_reversal_credit_replayed",
            reversal_id=row.reversal_id,
            tx_hash=tx_hash,
        )
        return row

    owed = float(row.owed_amount or 0.0)
    paid = float(row.paid_amount or 0.0)
    share = max(0.0, float(slash.victim_amount or 0.0))
    delta = round(max(0.0, min(share, owed - paid)), 8)

    moment = now or datetime.utcnow()
    if delta > EPSILON:
        row.paid_amount = round(paid + delta, 8)
        row.attempts = int(row.attempts or 0) + 1
        row.tx_hash = tx_hash
        _mark_credited(row, tx_hash)
        row.status = (
            STATUS_SETTLED
            if row.paid_amount + EPSILON >= owed
            else STATUS_SUBMITTED
        )
        if row.status == STATUS_SETTLED:
            row.settled_at = moment
        row.updated_at = moment
        await db.flush()
        logger.info(
            "settlement_reversal_credited",
            reversal_id=row.reversal_id,
            case_id=row.case_id,
            paid_amount=row.paid_amount,
            owed_amount=owed,
            tx_hash=tx_hash,
            status=row.status,
        )
    return row


async def list_reversals(
    db: AsyncSession,
    *,
    case_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[SettlementReversal]:
    q = select(SettlementReversal).order_by(SettlementReversal.created_at.desc())
    if case_id:
        q = q.where(SettlementReversal.case_id == case_id)
    if status:
        q = q.where(SettlementReversal.status == status)
    return list((await db.execute(q.limit(max(1, min(limit, 500))))).scalars().all())


async def case_has_bench_slashes(db: AsyncSession, *, case_id: str) -> bool:
    """这个案件有没有「被推翻那一庭」的罚没行 —— 决定出账口径是 ``bench_bond`` 还是 ``slash_pool``。

    读的是**台账**而不是本次调用新写了什么：重复 ``/overturn`` 时第二次不会再写罚没行，
    但答案必须与第一次一致（否则同一条账两次调用会记两个出资口径）。
    """
    total = await db.scalar(
        select(func.count())
        .select_from(BondSlash)
        .where(
            BondSlash.source_kind == bond_slash.SOURCE_ARBITRATION_OVERTURN,
            BondSlash.source_id == case_id,
        )
    )
    return bool(total)


async def outstanding_total(db: AsyncSession) -> float:
    """还没赔完的欠款合计（``owed - paid``，只算没失败的）。"""
    rows = await list_reversals(db, limit=500)
    total = 0.0
    for row in rows:
        if (row.status or "") == STATUS_FAILED:
            continue
        total += max(0.0, float(row.owed_amount or 0.0) - float(row.paid_amount or 0.0))
    return round(total, 8)
