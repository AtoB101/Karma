"""Karma Identity Card & Trust State API —— 身份底座 v1

对外暴露：
- 凭证生命周期：签发 / 验证 / 拒绝 / 吊销（全部经状态机校验）
- Karma Identity Card 聚合视图（最小披露）
- 信任台账（hash 链，可审计）
- 异常告警流（风险预警 + 根因回溯）
- 环境健康自检 + 台账完整性校验（反篡改）
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from services.identity_gateway import state_machine, store
from services.identity_reputation import attach_card_reputation

router = APIRouter()

_ID_RE = re.compile(r"\Akid_[A-Za-z0-9_-]{4,64}\Z")
_CRED_RE = re.compile(r"\Acred_[A-Za-z0-9]{6,40}\Z")


def _check_identity_id(identity_id: str) -> None:
    if not _ID_RE.fullmatch(identity_id):
        raise HTTPException(400, "invalid identity_id format")


def _check_credential_id(credential_id: str) -> None:
    if not _CRED_RE.fullmatch(credential_id):
        raise HTTPException(400, "invalid credential_id format")


class IssueCredentialBody(BaseModel):
    type: str = Field(..., min_length=2, max_length=32)
    issuer: str = Field(default="karma", max_length=64)
    ttl_seconds: int = Field(default=0, ge=0, le=315_360_000)
    # auto_verify 仅限内部信任通道（bind_by_2fa）；公开 API 永不自动验证
    auto_verify: bool = False


class RevokeBody(BaseModel):
    reason: str = Field(..., min_length=2, max_length=256)


class RejectBody(BaseModel):
    reason: str = Field(default="", max_length=256)


class SetClassBody(BaseModel):
    identity_class: str = Field(..., pattern="^(user|business|agent)$")


# ── 凭证生命周期 ────────────────────────────────────────────

@router.post("/v1/identity/{identity_id}/credentials")
def issue_credential_route(identity_id: str, body: IssueCredentialBody):
    _check_identity_id(identity_id)
    try:
        # 公开 API 禁止 auto_verify：必须经独立验证材料核验
        cred = store.issue_credential(
            identity_id, body.type,
            issuer=body.issuer, ttl_seconds=body.ttl_seconds,
            actor="api", auto_verify=False,
        )
        return {"credential": cred}
    except state_machine.IllegalTransitionError as exc:
        raise HTTPException(409, f"illegal transition: {exc}")
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/v1/identity/{identity_id}/credentials/{credential_id}/verify")
def verify_credential_route(identity_id: str, credential_id: str):
    _check_identity_id(identity_id)
    _check_credential_id(credential_id)
    try:
        return {"credential": store.verify_credential(identity_id, credential_id, actor="api")}
    except state_machine.IllegalTransitionError as exc:
        raise HTTPException(409, f"illegal transition: {exc}")
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/v1/identity/{identity_id}/credentials/{credential_id}/reject")
def reject_credential_route(identity_id: str, credential_id: str, body: RejectBody):
    _check_identity_id(identity_id)
    _check_credential_id(credential_id)
    try:
        return {"credential": store.reject_credential(identity_id, credential_id, actor="api", reason=body.reason)}
    except state_machine.IllegalTransitionError as exc:
        raise HTTPException(409, f"illegal transition: {exc}")
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.post("/v1/identity/{identity_id}/credentials/{credential_id}/revoke")
def revoke_credential_route(identity_id: str, credential_id: str, body: RevokeBody):
    _check_identity_id(identity_id)
    _check_credential_id(credential_id)
    try:
        return {"credential": store.revoke_credential(identity_id, credential_id, actor="api", reason=body.reason)}
    except state_machine.IllegalTransitionError as exc:
        raise HTTPException(409, f"illegal transition: {exc}")
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ── Karma Identity Card ────────────────────────────────────

@router.get("/v1/identity/{identity_id}/card")
async def get_card_route(
    identity_id: str,
    scope: str = Query(default="basic", pattern="^(basic|full)$"),
    audience: str = Query(default="agent", max_length=64),
    db: AsyncSession = Depends(get_db),
):
    _check_identity_id(identity_id)
    try:
        card = store.identity_card(identity_id, audience=audience, scope=scope)
    except KeyError:
        raise HTTPException(404, "identity not found")
    main_id = card.get("identity_id") or identity_id
    return await attach_card_reputation(
        db,
        card,
        identity_id=main_id,
        identity_class=card.get("identity_class"),
    )


@router.put("/v1/identity/{identity_id}/class")
async def set_class_route(
    identity_id: str,
    body: SetClassBody,
    db: AsyncSession = Depends(get_db),
):
    _check_identity_id(identity_id)
    try:
        store.set_identity_class(identity_id, body.identity_class, actor="api")
        ident = store.get_by_id(identity_id)
        from services.identity_reputation import open_identity_ledger

        await open_identity_ledger(db, identity_id, identity_class=body.identity_class)
        # 脱敏返回：不含 twofa_code / 完整 wallet / payment_policy
        return {
            "identity_id": ident.identity_id,
            "identity_class": ident.identity_class,
            "verification_status": ident.verification_status,
            "status": ident.status,
        }
    except KeyError:
        raise HTTPException(404, "identity not found")


# ── 信任台账 / 告警 / 健康（审计面） ─────────────────────

@router.get("/v1/trust/ledger")
def trust_ledger_route(
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    return {"entries": state_machine.get_ledger(entity_id=entity_id, limit=limit)}


@router.get("/v1/trust/alerts")
def trust_alerts_route(
    severity: str | None = Query(default=None, pattern="^(info|warn|critical)$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    return {"alerts": state_machine.get_alerts(severity=severity, limit=limit)}


@router.get("/v1/trust/health")
def trust_health_route():
    return state_machine.health_report()


@router.post("/v1/trust/verify-integrity")
def trust_verify_integrity_route():
    """反篡改校验：全链 hash 校验，发现破损播报 critical。"""
    return state_machine.verify_ledger_integrity()
