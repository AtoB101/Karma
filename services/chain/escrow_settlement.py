"""Karma — 把「任务结算」接到非托管授权托管（allowance escrow）上。

背景：``/v1/settlement/*`` 这条业务流原先只改数据库 —— 接单写 ACCEPTED、验收写
SETTLED，链上一分钱没动。于是「已锁仓额度」只是台账里的一个数字，卖家拿到的
「结算完成」在链上不存在。

这个模块把它接到已经跑通的 v2 allowance escrow 上，链路是：

接单（→ ACCEPTED）   买方账单 + 卖方质押账单 ``bind`` 成一个 binding。钱还在买方
                     自己的钱包里，只是被「承诺」占住了 —— 没有人托管。
验收（→ SETTLED）    ``submitSettlement`` 打开挑战期。挑战期一过，API 进程内的
                     escrow autosettle 循环执行 ``finalizeSettlement``，钱从买方
                     钱包直接划到卖方钱包。
退款 / 取消           ``cancelBinding``，把买方被占住的授权原样放回去，钱不动。

门槛：买方和卖方都必须**先在链上锁过仓**。没有真账单就不 bind —— 接单直接 409，
并把缺多少说清楚。额度从此不是可以凭空记的数字。

这一层只写「钱的事实」：它不做金额裁决，也不替任何人签名。operator 只能 bind /
submit，划款与否由买方自己的 ERC-20 授权额决定，买方随时可以 revoke。

钱只被「账上已经落定的验证结论」推动。合约（v3 起）里的 ``submitSettlement`` 是
resolver-only —— 开窗这件事只由平台决定；而窗口一开，保护期到点后
``finalizeSettlement`` 对**任何人**都放行（autosettle 正是靠这个自动放款，见
services/chain/escrow_autosettle.py）。所以「验证到底过没过」链上问不出来，
必须在开窗之前问账本：``assert_release_verified`` 就是那道闸。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AllowanceCommitModel, EscrowBindingModel, SettlementModel
from services import seller_stake
from services.chain import allowance_escrow as escrow
from services.settlement_amounts import from_minor_units, to_minor_units

logger = structlog.get_logger(__name__)

#: 台账口径：binding 的本地状态
ACTIVE = "active"          # 已 bind，挑战期还没开（钱没动）
FINALIZING = "finalizing"  # 已 submit，等 autosettle 划款
SETTLED = "settled"        # 链上已经划完
CANCELLED = "cancelled"    # 授权已放回
SLASHED = "slashed"        # 卖方质押被划给买方
BREACHING = "breaching"    # 已裁定违约，等争议窗口到点后罚没（此刻钱还没动）

_DONE_STATES = (SETTLED, CANCELLED, SLASHED)

#: 合约自己记的 binding 状态（见 allowance_escrow.BINDING_STATE）
_CHAIN_FINAL = {3: SETTLED, 4: SLASHED, 5: CANCELLED}

#: 钱往哪边走：放款给卖方 / 罚没卖方质押
PAY = "pay"
SLASH = "slash"

#: 账上必须落成哪个结论，链上才允许开结算窗口
_DECIDED_STATUS = {PAY: "settled", SLASH: "refunded"}


class EscrowSettlementError(Exception):
    """带 HTTP 状态的领域错误，路由层直接翻译成人话。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def enabled() -> bool:
    """这个部署真的配了托管合约 + operator key 吗。"""
    return bool(escrow.escrow_enabled())


async def assert_receipt_path_exists(db: AsyncSession, *, task_id: str) -> None:
    """锁真钱之前先问一句：这一单的执行回执，将来真的写得进来吗。

    生产配置下回执必须由 Runtime 网关代签（``RECEIPT_REQUIRE_SIGNATURE=true``），
    而网关要求这一单挂着卖方已接受的授权凭证（Voucher）。没有凭证的结算单一辈子
    写不进回执 —— 于是买方验收被「至少要有一条成功回执」永久挡住，链上那笔预留
    谁也解不开：买方拿不回额度，卖方也收不到钱。

    钱锁进这种单子里是纯粹的损失，所以宁可现在就拒。非生产配置（回执可以不验签）
    不受影响：那种环境下回执本来就写得进来。
    """
    if not (
        settings.runtime_require_task_automation_readiness
        and settings.receipt_require_signature
    ):
        return
    row = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().first()
    if row is None or (row.voucher_id or "").strip():
        return
    raise EscrowSettlementError(
        409,
        "这一单没有授权凭证（Voucher），钱不能锁：生产配置下执行回执必须由 Runtime "
        "网关代签，而网关要求先有卖方已接受的凭证。没有凭证，回执永远写不进来，"
        "买方验收会被「至少要有一条成功回执」挡住，这笔预留谁都解不开。"
        "请先在操作台开一张授权凭证并让卖方接受，再指派卖方。",
    )


def _minor(amount_usdc: float | None) -> int:
    """金额一律先落到链上最小单位（整数）再比较 —— 服务端记的是 float。

    实测（2026-09-20）：账上用 float 反推、再拿 EPSILON 比「少了没有」，12.345 这类
    金额会在两个口径之间漂 —— 链上是整数，账上是浮点，对不上的那一分钱就是「账实不符」。
    链上最小单位是唯一口径（见 services/settlement_amounts.py）。
    """
    return to_minor_units(float(amount_usdc or 0.0))


def _proof(task_id: str, amount_minor: int) -> str:
    """这一单的凭证摘要：跟着任务和实际释放金额走，改一个字节就对不上。"""
    return f"karma-settlement:{task_id}:{from_minor_units(int(amount_minor)):.6f}"


async def _find_binding(db: AsyncSession, *, task_id: str) -> EscrowBindingModel | None:
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.task_id == task_id)
        .order_by(EscrowBindingModel.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


def chain_binding_id(binding: Any) -> int:
    """账上主键 → 链上 binding id。

    本地主键**通常**就是链上 id，但换过合约之后不一定：链上 id 是每台合约各自
    计数的（v2 用到 58，v3 从 1 重开），跨合约会重号 —— 重号的那条本地主键会被
    写成 ``<合约地址>:<链上 id>``（见 ``local_binding_id``）。所以解析一律走这里，
    别直接 ``int(row.binding_id)``：碰到带前缀的那几条会抛 ValueError，
    而它通常发生在 autosettle 的某一轮里，一抛就是一整轮的钱都不动。
    """
    raw = getattr(binding, "binding_id", binding)
    return int(str(raw).rsplit(":", 1)[-1])


async def local_binding_id(
    db: AsyncSession, *, chain_id: int, contract: str, exclude: str | None = None
) -> str:
    """给这一条绑定挑一个**跨合约唯一**的账上主键。

    链上的 binding id 只在**一台合约内**唯一。换合约（v2 → v3）之后两边必然重号：
    2026-09-21 实测 v3 的第 9 条撞上 v2 的第 9 条 —— 链上 ``bind`` 已经成功（买方
    账单被占住 0.2），账上 INSERT 被主键唯一约束打回，``/v1/settlement/{task}/lock``
    直接 500，链上留下一条谁也不认的绑定。

    规则：裸 id 没被占就用裸的（``9`` 比 ``0x32b3…:9`` 好看，也顺手）；
    被别的合约占了才加合约地址前缀。这样以后**任何一次合约升级**都不会再撞上
    历史主键 —— 不需要每次升级都记得去改一次数据。
    """
    plain = str(chain_id)
    if exclude is not None and plain == exclude:
        return plain
    if await db.get(EscrowBindingModel, plain) is None:
        return plain
    return f"{contract}:{chain_id}"


async def find_binding(db: AsyncSession, binding_id: str) -> EscrowBindingModel | None:
    """按账上主键取一条绑定，兼容改名前的历史引用。

    退役合约的历史行主键带上了合约前缀，而老链接 / 老外部引用里存的还是裸 id，
    直接 ``db.get`` 会取不到（调用方多半当成 404 或 None 崩掉）。先按原样查，
    再按「后缀匹配」兜一次。
    """
    row = await db.get(EscrowBindingModel, binding_id)
    if row is not None:
        return row
    stmt = (
        select(EscrowBindingModel)
        .where(EscrowBindingModel.binding_id.like("%:" + str(binding_id)))
        .order_by(EscrowBindingModel.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def _live_bills(db: AsyncSession, identity_id: str) -> list[AllowanceCommitModel]:
    rows = await escrow.list_commits(db, identity_id)
    return [r for r in rows if r.state == escrow.IDLE]


async def _pick_bill(db: AsyncSession, *, identity_id: str, role: str, need_usdc: float) -> str:
    """挑一张**真划得动**的账单。

    台账上「剩余额度够」不等于「链上划得动」：同一个钱包的多张账单共用一条 ERC-20
    授权额，先到先得（见 ``backing_report``）。所以这里两个口径都要过。

    只认**当前**托管合约上的账单：合约换过地址（v2 → v3）之后，旧账单在新合约里
    根本不存在 —— 拿旧 bill id 去 ``available()`` 会 revert（实测就是它把
    ``/lock`` 打成 500 的）。而且新单也只能开在当前合约上：旧合约没有「验证通过
    才开窗」这道闸（``submitSettlement`` 谁都能调），开上去等于把 F9-1 的洞重新
    打开。旧合约上的锁仓不是消失了，用户在操作台重新锁一次即可 —— 这句话必须
    说到用户耳朵里，所以下面把它单独报出来。
    """
    need = max(0.0, float(need_usdc or 0.0))
    need_minor = _minor(need)
    live = await _live_bills(db, identity_id)
    if not live:
        raise EscrowSettlementError(
            409,
            f"{role}还没有链上锁仓额度。请在操作台「资金」里锁仓 USDC —— "
            f"授权额就是这一单能动的上限，钱始终留在自己的钱包里",
        )
    spendable = [r for r in live if escrow.bill_is_spendable(r)]
    if not spendable:
        stale = sorted({escrow.bill_contract(r) for r in live})
        raise EscrowSettlementError(
            409,
            f"{role}的锁仓账单在**旧**托管合约上（{', '.join(stale)}）：当前合约"
            f"（{escrow.configured_address()}）划不动它们。请在操作台重新锁仓 USDC "
            f"到当前合约，再接单",
        )
    report = await escrow.backing_report(db, identity_id)
    if not report.get("chain_checked"):
        raise EscrowSettlementError(
            503, f"读不到{role}的链上授权额（RPC 抖动）。没有链上事实就不该动钱，请稍后重试"
        )
    secured_by_bill = report.get("bills") or {}
    best: tuple[int, str] | None = None
    candidates: list[int] = []
    for row in spendable:
        free_minor = (
            _minor(row.amount_usdc) - _minor(row.spent_usdc) - _minor(row.reserved_usdc)
        )
        secured_minor = _minor(
            (secured_by_bill.get(str(row.bill_id)) or {}).get("secured_usdc")
        )
        if free_minor < need_minor or secured_minor < need_minor:
            candidates.append(min(free_minor, secured_minor))
            continue
        # 台账只在链上确认之后才更新，两个结算挨得近时它会高估。以合约自己记的
        # 「还剩多少」为准：挑中的账单必须真的 Bind 得动，不能拿台账去赌。
        onchain = await asyncio.to_thread(
            escrow.bill_available,
            bill_id=int(row.bill_id),
            contract_address=escrow.bill_contract(row),
        )
        if onchain is None:
            continue
        onchain_minor = _minor(onchain)
        candidates.append(min(free_minor, secured_minor, onchain_minor))
        if onchain_minor < need_minor:
            continue
        if best is None or min(free_minor, onchain_minor) > best[0]:
            best = (min(free_minor, onchain_minor), str(row.bill_id))
    if best is None:
        have_minor = max(candidates) if candidates else 0
        raise EscrowSettlementError(
            409,
            f"{role}的可用锁仓额度不足：这一单需要 {from_minor_units(need_minor)} USDC，"
            f"链上真正划得动的只有 {from_minor_units(max(0, have_minor))} USDC。"
            f"请先在操作台补足锁仓（或提高对该托管合约的 USDC 授权额）再重试",
        )
    return best[1]


async def _reflect(
    db: AsyncSession,
    *,
    task_id: str,
    binding: EscrowBindingModel,
    onchain_status: str,
    tx_hash: str | None = None,
) -> None:
    """把链上的事实写回结算单（操作台读的就是这一行）。"""
    stmt = select(SettlementModel).where(SettlementModel.task_id == task_id)
    model = (await db.execute(stmt)).scalars().first()
    if model is None:
        return
    model.settlement_mode = "escrow_allowance"
    model.chain_id = int(settings.testnet_chain_id or 0) or None
    # 记的是**这条绑定自己**那台合约，不是「当前配置」：合约换过地址之后，
    # 操作台读这一行要能分辨它是新合约还是旧合约上的单子。
    model.contract_address = escrow.binding_contract(binding) or None
    try:
        model.onchain_binding_id = int(binding.binding_id)
    except (TypeError, ValueError):
        pass
    for attr, raw in (
        ("onchain_buyer_bill_id", binding.buyer_bill_id),
        ("onchain_agent_bill_id", binding.seller_bill_id),
    ):
        try:
            setattr(model, attr, int(raw))
        except (TypeError, ValueError):
            pass
    model.onchain_status = onchain_status
    if tx_hash:
        model.tx_hash = tx_hash
    model.updated_at = datetime.utcnow()


async def reflect_final(
    db: AsyncSession,
    *,
    task_id: str,
    binding: EscrowBindingModel,
    onchain_status: str,
    tx_hash: str | None = None,
) -> None:
    """把链上已经落定的事实写回结算单（autosettle 推完单子后调用）。

    ``escrow_autosettle._record_final`` 过去只改 ``escrow_bindings.state``，而操作台
    读的是 ``settlements.onchain_status`` —— 链上钱都划完了，页面还停在 finalizing /
    breaching。状态机两边必须一起往前走（F10-2）。
    """
    if not task_id:
        return
    await _reflect(db, task_id=task_id, binding=binding, onchain_status=onchain_status,
                   tx_hash=tx_hash)


async def bind_for_task(
    db: AsyncSession,
    *,
    task_id: str,
    buyer_identity_id: str,
    seller_identity_id: str | None,
    amount_usdc: float,
) -> dict[str, Any]:
    """接单时把买方承诺和卖方质押绑在一起（钱还没动）。"""
    if not enabled():
        return {"status": "disabled"}
    await assert_receipt_path_exists(db, task_id=task_id)
    amount = float(amount_usdc or 0.0)
    if amount <= 0:
        return {"status": "skipped", "reason": "settlement has no escrow amount"}
    if not seller_identity_id:
        raise EscrowSettlementError(409, "接单前必须先有 worker_agent_id —— 没有收款方就没有结算")

    existing = await _find_binding(db, task_id=task_id)
    if existing is not None and existing.state not in ("cancelled",):
        return {"status": "already_bound", "binding_id": existing.binding_id, "state": existing.state}

    stake = seller_stake.required_stake_usdc(amount)
    buyer_bill = await _pick_bill(db, identity_id=buyer_identity_id, role="付款方", need_usdc=amount)
    seller_bill = await _pick_bill(db, identity_id=seller_identity_id, role="提供方", need_usdc=stake)

    # 新单一律开在当前合约上（``_pick_bill`` 已经保证挑出来的账单属于它）。
    # 记下这一条，之后所有链上动作都打向**它自己那台**合约，升级换地址也不会
    # 让这笔钱收不了尾。
    contract = escrow.configured_address()
    scope = f"{settings.settlement_scope}:task"
    try:
        bound = await asyncio.to_thread(
            escrow.open_order,
            buyer_bill_id=buyer_bill,
            seller_bill_id=seller_bill,
            amount_usdc=amount,
            stake_usdc=stake,
            scope=scope,
            task_id=task_id,
            contract_address=contract,
        )
    except Exception as exc:  # 链上没绑上，业务状态就不该往前走
        logger.warning("escrow_settlement_bind_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上锁定失败：{exc}") from exc

    local_id = await local_binding_id(
        db, chain_id=int(bound["binding_id"]), contract=contract
    )
    row = EscrowBindingModel(
        binding_id=local_id,
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_identity_id,
        buyer_bill_id=str(buyer_bill),
        seller_bill_id=str(seller_bill),
        contract_address=contract,
        scope_hash=str(bound.get("scope_hash") or ""),
        task_id=task_id,
        amount_usdc=amount,
        stake_usdc=stake,
        state=ACTIVE,
        bind_tx_hash=str(bound.get("bind_tx_hash") or "") or None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    await _reflect(db, task_id=task_id, binding=row, onchain_status="bound", tx_hash=row.bind_tx_hash)
    logger.info(
        "escrow_settlement_bound",
        task_id=task_id,
        binding_id=row.binding_id,
        amount_usdc=amount,
        stake_usdc=stake,
        tx=row.bind_tx_hash,
    )
    return {
        "status": "bound",
        "binding_id": row.binding_id,
        "bind_tx_hash": row.bind_tx_hash,
        "amount_usdc": amount,
        "stake_usdc": stake,
    }


async def _rebind_partial(
    db: AsyncSession, *, row: EscrowBindingModel, task_id: str, amount_usdc: float
) -> None:
    """部分结算：原绑定锁的是全额，链上没有「少划一点」的入口 —— 撤掉重绑。"""
    contract = escrow.binding_contract(row)
    await asyncio.to_thread(
        escrow.cancel_binding, binding_id=chain_binding_id(row), contract_address=contract
    )
    stake = seller_stake.required_stake_usdc(amount_usdc)
    buyer_bill = await _pick_bill(
        db, identity_id=row.buyer_identity_id, role="付款方", need_usdc=amount_usdc
    )
    seller_bill = await _pick_bill(
        db, identity_id=str(row.seller_identity_id), role="提供方", need_usdc=stake
    )
    bound = await asyncio.to_thread(
        escrow.open_order,
        buyer_bill_id=buyer_bill,
        seller_bill_id=seller_bill,
        amount_usdc=amount_usdc,
        stake_usdc=stake,
        scope=f"{settings.settlement_scope}:task",
        task_id=task_id,
        contract_address=contract,
    )
    # 重绑会换一个新的链上 id：本地主键跟着换，且必须仍然跨合约唯一。
    row.binding_id = await local_binding_id(
        db, chain_id=int(bound["binding_id"]), contract=contract, exclude=row.binding_id
    )
    row.buyer_bill_id = str(buyer_bill)
    row.seller_bill_id = str(seller_bill)
    row.scope_hash = str(bound.get("scope_hash") or "")
    row.amount_usdc = amount_usdc
    row.stake_usdc = stake
    row.bind_tx_hash = str(bound.get("bind_tx_hash") or "") or None
    row.updated_at = datetime.utcnow()
    await db.flush()


async def assert_release_verified(
    db: AsyncSession, *, task_id: str, mode: str = PAY
) -> SettlementModel:
    """动钱之前先把「账上到底有没有一个验证结论」问清楚。

    合约（v3 起）里的 ``submitSettlement`` 是 resolver-only：开窗这件事只由平台决定，
    链上问不出「验证过没过」。而窗一开，保护期到点后 ``finalizeSettlement`` 对**任何人**
    都放行（autosettle 就靠这个自动放款）。所以真正的门必须在这里 —— 账上没有结论，
    链上就不许开窗：

    * 放款（``PAY``）：账上必须是 ``settled``，交付验证必须 VERIFIED，且至少有一条成功执行回执；
    * 罚没（``SLASH``）：账上必须是 ``refunded``（这次交付被裁定为一文不值）。

    任何一条不满足都直接拒绝，并且**不做任何链上动作**：钱还在买方自己的钱包里，
    买方随时可以 revoke，不需要经过我们。
    """
    row = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().first()
    if row is None:
        raise EscrowSettlementError(
            409, "这一单在账上没有结算记录：验证结论不存在，链上不能开结算窗口"
        )
    status = (row.status or "").strip().lower()
    wanted = _DECIDED_STATUS.get(mode)
    if wanted is None:
        raise EscrowSettlementError(500, f"未知的结算动作：{mode}")
    if status != wanted:
        raise EscrowSettlementError(
            409,
            f"这一单账上还停在 {status or '未知'}，不是 {wanted}：验证结论没落定，"
            f"链上不能开结算窗口（窗口一开，保护期一过钱就自动划走，谁也拿不回来）",
        )
    if mode == SLASH:
        return row
    _assert_delivery_verified(row)
    await _assert_success_receipt(
        db, task_id=task_id, amount_usdc=float(row.escrow_amount or 0.0)
    )
    return row


def _assert_delivery_verified(row: SettlementModel) -> None:
    """有交付验证会话（或有场景策略）的单子必须是 VERIFIED —— 路由层 P7 门禁的镜像。"""
    from services.delivery_verification import (
        DeliveryVerificationError,
        get_verification_for_task,
        require_verified_for_settle,
        scene_policy,
    )

    spec = row.progress_rule_spec if isinstance(row.progress_rule_spec, dict) else {}
    raw_scene = spec.get("scene_id")
    scene_id = raw_scene.strip() if isinstance(raw_scene, str) and raw_scene.strip() else None
    session = get_verification_for_task(row.task_id)
    if session is None and not scene_id:
        return
    mode = (session or {}).get("mode") or scene_policy(scene_id or "api_tool_call").get("mode")
    if session is None and mode in {"digital_light", "ride_track"}:
        return
    try:
        require_verified_for_settle(
            task_id=row.task_id, scene_id=scene_id, allow_missing_session_for_digital=True
        )
    except DeliveryVerificationError as exc:
        raise EscrowSettlementError(409, f"交付验证没有完全通过：{exc}") from exc


async def _assert_success_receipt(
    db: AsyncSession, *, task_id: str, amount_usdc: float
) -> None:
    """放款必须有至少一条成功执行回执 —— 路由层同一道门禁在钱这一步的镜像。"""
    from fastapi import HTTPException

    from services.settlement_receipt_release_guard import (
        ensure_success_execution_receipt_before_seller_payout,
    )

    try:
        await ensure_success_execution_receipt_before_seller_payout(
            db, task_id, settled_amount=amount_usdc
        )
    except HTTPException as exc:
        raise EscrowSettlementError(409, f"没有成功执行回执，钱不划：{exc.detail}") from exc


async def _released_amount_on_the_books(db: AsyncSession, *, task_id: str) -> float | None:
    """账上这一单准备结给卖方的金额（``settlements.released_amount``）。

    全额结清会写成托管全额，部分结算写的是实际放行的那一部分。调用方没给金额时
    以账上为准 —— 否则自动补锅的那条路（escrow_autosettle.reap_stranded）会按
    binding 的全额把钱划走，而账上只打算付一部分。
    """
    row = (
        await db.execute(select(SettlementModel).where(SettlementModel.task_id == task_id))
    ).scalars().first()
    if row is None or row.released_amount is None:
        return None
    return float(row.released_amount)


async def submit_for_task(
    db: AsyncSession, *, task_id: str, released_amount: float | None = None
) -> dict[str, Any]:
    """验收通过：把 binding 交上去，打开挑战期，等 autosettle 真划款。

    开窗前先过 ``assert_release_verified``：**账上没有验证结论就不开窗**。
    """
    if not enabled():
        return {"status": "disabled"}
    row = await _find_binding(db, task_id=task_id)
    if row is None:
        return {"status": "unbound"}
    if row.state in _DONE_STATES:
        return {"status": row.state, "binding_id": row.binding_id}
    if row.state != ACTIVE:
        return {"status": row.state, "binding_id": row.binding_id}

    await assert_release_verified(db, task_id=task_id, mode=PAY)
    if released_amount is None:
        released_amount = await _released_amount_on_the_books(db, task_id=task_id)
    target_minor = _minor(row.amount_usdc)
    if released_amount is not None:
        settled_minor = _minor(released_amount)
        if settled_minor < target_minor:
            target_minor = max(0, settled_minor)
    if target_minor <= 0:
        await cancel_for_task(db, task_id=task_id)
        return {"status": "cancelled", "reason": "nothing to release"}
    if target_minor != _minor(row.amount_usdc):
        await _rebind_partial(
            db, row=row, task_id=task_id, amount_usdc=from_minor_units(target_minor)
        )

    try:
        submitted = await asyncio.to_thread(
            escrow.submit_settlement,
            binding_id=chain_binding_id(row),
            proof=_proof(task_id, target_minor),
            contract_address=escrow.binding_contract(row),
        )
    except Exception as exc:
        logger.warning("escrow_settlement_submit_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上结算提交失败：{exc}") from exc

    row.state = FINALIZING
    row.submit_tx_hash = str(submitted.get("submit_tx_hash") or "") or None
    row.proof_hash = str(submitted.get("proof_hash") or "") or None
    row.pull_after = int(submitted.get("pull_after") or 0) or None
    row.updated_at = datetime.utcnow()
    await db.flush()
    await _reflect(
        db, task_id=task_id, binding=row, onchain_status=FINALIZING, tx_hash=row.submit_tx_hash
    )
    logger.info(
        "escrow_settlement_submitted",
        task_id=task_id,
        binding_id=row.binding_id,
        amount_usdc=from_minor_units(target_minor),
        pull_after=row.pull_after,
        tx=row.submit_tx_hash,
    )
    return {
        "status": FINALIZING,
        "binding_id": row.binding_id,
        "submit_tx_hash": row.submit_tx_hash,
        "pull_after": row.pull_after,
    }


def _breach_proof(task_id: str) -> str:
    """罚没这一单的凭证摘要。最终划多少由合约里的 stakeAmount 决定，摘要只留痕。"""
    return f"karma-breach:{task_id}"


async def slash_for_task(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    """判卖方违约：卖方质押划给买方（``finalizeBreach``，卖方钱包 → 买方钱包）。

    「全额退款（REFUNDED）」的含义是「这次交付被裁定为一文不值」，所以卖方要付代价：
    质押划给买方。链上没有一步到位的入口 —— ``finalizeBreach`` 只认 FINALIZING，
    而且必须等争议窗口到点。所以这里先把 binding 交上去打开窗口，再由
    ``escrow_autosettle`` 在窗口到点后真正执行罚没。

    窗口开启后 binding 记成 ``breaching``：正常结算通道只看 ``finalizing``，
    所以这一单绝不会被误当成「该付卖方」而把货款划出去。
    """
    if not enabled():
        return {"status": "disabled"}
    row = await _find_binding(db, task_id=task_id)
    if row is None:
        return {"status": "unbound"}
    if row.state in _DONE_STATES or row.state == BREACHING:
        return {"status": row.state, "binding_id": row.binding_id}
    # 罚没也是「动钱」：账上必须已经把这一单裁定成 REFUNDED，才允许打开结算窗口。
    await assert_release_verified(db, task_id=task_id, mode=SLASH)
    if row.state == FINALIZING:
        # 窗口本来就开着（例如先被冻结过）：直接改判罚没，不重复 submit。
        row.state = BREACHING
        row.updated_at = datetime.utcnow()
        await db.flush()
        await _reflect(
            db, task_id=task_id, binding=row, onchain_status=BREACHING, tx_hash=row.submit_tx_hash
        )
        logger.info("escrow_settlement_breach_rearmed", task_id=task_id, binding_id=row.binding_id)
        return {"status": BREACHING, "binding_id": row.binding_id, "pull_after": row.pull_after}
    if row.state != ACTIVE:
        return {"status": row.state, "binding_id": row.binding_id}

    try:
        submitted = await asyncio.to_thread(
            escrow.submit_settlement,
            binding_id=chain_binding_id(row),
            proof=_breach_proof(task_id),
            contract_address=escrow.binding_contract(row),
        )
    except Exception as exc:
        logger.warning("escrow_settlement_breach_submit_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上罚没提交失败：{exc}") from exc

    row.state = BREACHING
    row.submit_tx_hash = str(submitted.get("submit_tx_hash") or "") or None
    row.proof_hash = str(submitted.get("proof_hash") or "") or None
    row.pull_after = int(submitted.get("pull_after") or 0) or None
    row.updated_at = datetime.utcnow()
    await db.flush()
    await _reflect(
        db, task_id=task_id, binding=row, onchain_status=BREACHING, tx_hash=row.submit_tx_hash
    )
    logger.info(
        "escrow_settlement_breach_armed",
        task_id=task_id,
        binding_id=row.binding_id,
        stake_usdc=row.stake_usdc,
        pull_after=row.pull_after,
        tx=row.submit_tx_hash,
    )
    return {
        "status": BREACHING,
        "binding_id": row.binding_id,
        "submit_tx_hash": row.submit_tx_hash,
        "pull_after": row.pull_after,
    }


async def cancel_for_task(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    """取消：把买方被占住的授权放回去，钱一步都没动过。"""

    if not enabled():
        return {"status": "disabled"}
    row = await _find_binding(db, task_id=task_id)
    if row is None or row.state in _DONE_STATES or row.state != ACTIVE:
        return {"status": row.state if row is not None else "unbound"}
    try:
        await asyncio.to_thread(
            escrow.cancel_binding,
            binding_id=chain_binding_id(row),
            contract_address=escrow.binding_contract(row),
        )
    except Exception as exc:
        logger.warning("escrow_settlement_cancel_failed", task_id=task_id, error=str(exc))
        raise EscrowSettlementError(409, f"链上撤销锁定失败：{exc}") from exc
    row.state = CANCELLED
    row.updated_at = datetime.utcnow()
    await db.flush()
    await _reflect(db, task_id=task_id, binding=row, onchain_status=CANCELLED)
    # 链上把买方的授权放开了，账上的「可用额度」也得跟着放开（F10-1）：一张没人推进的
    # 授权码会在买方账上占着 reserved，过去只有等它自己过期（默认 7 天）才回来。
    out: dict[str, Any] = {"status": CANCELLED, "binding_id": row.binding_id}
    voucher = await _release_linked_voucher(db, task_id=task_id)
    if voucher is not None:
        out["voucher"] = voucher
    return out


async def _release_linked_voucher(db: AsyncSession, *, task_id: str) -> dict[str, Any] | None:
    """取消这一单时，把它挂着的授权码占的额度立刻放回「可用」。"""
    from services.settlement_voucher import cancel_voucher_reservation_for_task

    try:
        return await cancel_voucher_reservation_for_task(db, task_id=task_id)
    except Exception as exc:  # noqa: BLE001 - 台账动作，不能把链上已完成的撤销判成失败
        logger.warning(
            "escrow_settlement_voucher_release_failed", task_id=task_id, error=str(exc)
        )
        return None


async def reconcile_task(db: AsyncSession, *, task_id: str) -> dict[str, Any] | None:
    """把结算单和链上对齐。

    只在台账停在 ``finalizing`` 时才去问链（正常路径由 autosettle 自己回写），
    所以这个调用对绝大多数结算单是纯读库。
    """
    if not enabled():
        return None
    row = await _find_binding(db, task_id=task_id)
    if row is None:
        return None
    if row.state in _DONE_STATES:
        await _reflect(
            db,
            task_id=task_id,
            binding=row,
            onchain_status=row.state,
            tx_hash=row.finalize_tx_hash or row.submit_tx_hash or row.bind_tx_hash,
        )
        return {"status": row.state, "binding_id": row.binding_id, "tx_hash": row.finalize_tx_hash}
    if row.state not in (FINALIZING, BREACHING):
        return None
    try:
        chain_state = await asyncio.to_thread(
            escrow.binding_state,
            binding_id=chain_binding_id(row),
            contract_address=escrow.binding_contract(row),
        )
    except Exception as exc:  # RPC 抖动：保持现状，下次再对
        logger.warning("escrow_settlement_state_read_failed", task_id=task_id, error=str(exc))
        return None
    mapped = _CHAIN_FINAL.get(chain_state) if chain_state is not None else None
    if mapped is None:
        return None
    row.state = mapped
    row.updated_at = datetime.utcnow()
    await db.flush()
    tx = row.finalize_tx_hash or row.submit_tx_hash
    await _reflect(db, task_id=task_id, binding=row, onchain_status=mapped, tx_hash=tx)
    logger.info("escrow_settlement_reconciled", task_id=task_id, binding_id=row.binding_id, state=mapped)
    return {"status": mapped, "binding_id": row.binding_id, "tx_hash": tx}
