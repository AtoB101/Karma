"""Server-verified gates before task-scoped AI automation (OpenClaw / Runtime)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas import VoucherStatus
from db.models.orm import (
    ResponsibilityEdgeModel,
    RuntimeKeyModel,
    SettlementModel,
    TaskContractModel,
    VoucherModel,
)
from db.stores.settlement_store import PostgresSettlementStore
from services.agent_automation_policy import get_automation_policy, policy_summary_for_console
from services.openclaw_handoff_attestation import has_handoff_attestation
from services.openclaw_handoff_draft import build_handoff_draft

Role = Literal["buyer", "seller"]


async def resolve_task_id_for_voucher(db: AsyncSession, voucher_id: str) -> str | None:
    result = await db.execute(
        select(SettlementModel.task_id).where(SettlementModel.voucher_id == voucher_id)
    )
    return result.scalar_one_or_none()


async def infer_role_for_task(
    db: AsyncSession,
    *,
    task_id: str,
    karma_identity_id: str,
) -> Role:
    contract = await db.get(TaskContractModel, task_id)
    if contract and contract.worker_agent_id == karma_identity_id:
        return "seller"
    state = await PostgresSettlementStore(db).get(task_id)
    if state and (state.worker_agent_id or "") == karma_identity_id:
        return "seller"
    return "buyer"


async def assert_task_automation_ready(
    db: AsyncSession,
    *,
    task_id: str,
    karma_identity_id: str,
) -> None:
    """
    Raise 403 when ``RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS`` is on and task gates fail.

    Used by Runtime Gateway mutators (receipt, progress, settlement, check-voucher).
    """
    from config.settings import settings

    if not settings.runtime_require_task_automation_readiness:
        return
    role = await infer_role_for_task(db, task_id=task_id, karma_identity_id=karma_identity_id)
    report = await evaluate_automation_readiness(
        db,
        task_id=task_id,
        role=role,
        karma_identity_id=karma_identity_id,
    )
    if report.get("ready_for_task_automation"):
        from services.openclaw_handoff_attestation import assert_handoff_attested

        await assert_handoff_attested(db, task_id=task_id, karma_identity_id=karma_identity_id)
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": "automation_not_ready",
            "task_id": task_id,
            "karma_identity_id": karma_identity_id,
            "blockers": report.get("blockers") or [],
            "hint": "Complete Console authorization gate and GET /v1/openclaw/automation-readiness",
        },
    )


async def evaluate_automation_readiness(
    db: AsyncSession,
    *,
    task_id: str,
    role: Role = "buyer",
    karma_identity_id: str | None = None,
    require_attestation: bool | None = None,
) -> dict[str, Any]:
    """
    Return authoritative readiness for AI automation on a task.

    ``ready_for_task_automation`` requires: saved policy with auto_enabled, responsibility ack,
    active Runtime Key for the identity, voucher accepted, settlement exists, and responsibility edge.
    """
    draft = await build_handoff_draft(db, task_id=task_id)
    handoff = draft.get("handoff") or {}
    buyer_id = handoff.get("buyer_identity_id") or ""
    seller_id = handoff.get("seller_identity_id") or ""
    identity_id = (karma_identity_id or "").strip() or (buyer_id if role == "buyer" else seller_id)

    policy = await get_automation_policy(db, identity_id) if identity_id else None
    policy_blockers: list[str] = []
    if not policy:
        policy_blockers.append("未保存服务端自动授权策略（资金额度与权限）")
    else:
        if not policy.auto_enabled:
            policy_blockers.append("策略未开启 AI 自动执行（auto_enabled=false）")
        if not policy.responsibility_acknowledged:
            policy_blockers.append("未确认责任边界（responsibility_acknowledged）")

    runtime_key_ok = False
    runtime_key_permissions: list[str] = []
    if identity_id:
        now = datetime.utcnow()
        result = await db.execute(
            select(RuntimeKeyModel).where(
                RuntimeKeyModel.karma_identity_id == identity_id,
                RuntimeKeyModel.status == "active",
                RuntimeKeyModel.expire_at > now,
            )
        )
        keys = list(result.scalars().all())
        if keys:
            runtime_key_ok = True
            runtime_key_permissions = sorted(
                {p for k in keys for p in (k.permissions or [])}
            )

    voucher_row = None
    voucher_id = handoff.get("voucher_id")
    if voucher_id:
        voucher_row = await db.get(VoucherModel, voucher_id)
    voucher_accepted = bool(
        voucher_row and VoucherStatus(voucher_row.status) == VoucherStatus.ACCEPTED
    )

    settlement_state = await PostgresSettlementStore(db).get(task_id)
    settlement_created = settlement_state is not None

    responsibility_ok = False
    if voucher_id:
        edge = await db.execute(
            select(ResponsibilityEdgeModel).where(ResponsibilityEdgeModel.voucher_id == voucher_id)
        )
        responsibility_ok = edge.scalar_one_or_none() is not None

    contract_row = await db.get(TaskContractModel, task_id)

    handoff_attested = False
    if identity_id:
        handoff_attested = await has_handoff_attestation(
            db, task_id=task_id, karma_identity_id=identity_id
        )

    server_checks = {
        "policy_configured": policy is not None,
        "policy_auto_enabled": bool(policy and policy.auto_enabled),
        "responsibility_acknowledged": bool(policy and policy.responsibility_acknowledged),
        "runtime_key_active": runtime_key_ok,
        "voucher_accepted": voucher_accepted,
        "settlement_created": settlement_created,
        "responsibility_edge_recorded": responsibility_ok,
        "contract_exists": contract_row is not None,
        "handoff_attested": handoff_attested,
    }

    blockers: list[str] = list(policy_blockers)
    from config.settings import settings as _settings

    if require_attestation is None:
        require_attestation = _settings.runtime_require_handoff_attestation

    if require_attestation and not handoff_attested:
        blockers.append("未登记 Console handoff 确认（POST /v1/openclaw/handoff-confirm）")
    if not server_checks["runtime_key_active"]:
        blockers.append("无有效 Runtime Key（需钱包签名铸造，且未过期）")
    if not server_checks["voucher_accepted"]:
        blockers.append("Voucher 未 accepted（卖方须在 Console 接受）")
    if not server_checks["settlement_created"]:
        blockers.append("Settlement 未创建")
    if not server_checks["responsibility_edge_recorded"]:
        blockers.append("责任图谱未记录（通常在卖方 accept voucher 后写入）")

    for w in draft.get("warnings") or []:
        if w not in blockers:
            blockers.append(w)

    base_ready = (
        server_checks["policy_configured"]
        and server_checks["policy_auto_enabled"]
        and server_checks["responsibility_acknowledged"]
        and server_checks["runtime_key_active"]
        and server_checks["voucher_accepted"]
        and server_checks["settlement_created"]
        and server_checks["responsibility_edge_recorded"]
        and draft.get("validation_ok") is True
    )
    ready = base_ready and (handoff_attested or not require_attestation)

    return {
        "task_id": task_id,
        "role": role,
        "karma_identity_id": identity_id,
        "buyer_identity_id": buyer_id,
        "seller_identity_id": seller_id,
        "policy": policy_summary_for_console(policy),
        "fund_limits": {
            "policy_single_limit": policy.single_limit if policy else None,
            "policy_daily_limit": policy.daily_limit if policy else None,
        },
        "runtime_key_permissions": runtime_key_permissions,
        "server_checks": server_checks,
        "handoff_validation_ok": draft.get("validation_ok"),
        "handoff_inferred_steps": draft.get("inferred_steps"),
        "blockers": blockers,
        "ready_for_handoff_confirm": base_ready,
        "ready_for_task_automation": ready,
        "authorization_flow": [
            "1. 在 Console 设置资金额度、权限范围，并确认责任边界",
            "2. 保存服务端策略（PUT /v1/identities/{id}/automation-policy）",
            "3. 钱包签名铸造 Runtime Key（不得超过已保存策略）",
            "4. Console 完成 Voucher 创建/接受与 Settlement",
            "5. POST /v1/openclaw/handoff-confirm 登记服务端存证",
            "6. 导出 handoff JSON 交给 OpenClaw（MCP 将校验存证）",
        ],
    }
