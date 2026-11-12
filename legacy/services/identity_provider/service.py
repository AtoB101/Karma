"""
Karma — 实名 / 活体核验的编排：开会话 → 收回调（验签）→ 走主身份认证状态机。

三条纪律：

1. **只听签名**。回调来自服务商的服务器，没有 Karma 令牌；验签不过就 401，且一条记录都不写。
2. **只认自己开出去的那次会话**。回调里的会话号必须对得上我们签发的那一次，
   对不上就是 409 —— 否则谁都能拿一段别人的会话号来给任意身份盖章。
3. **置位走既有状态机**，不另开一条捷径：服务商判定通过时，行先由 none/rejected → pending
   （证据已到、进入判定），再 pending → verified，和人工复核走过的是同一组合法迁移；
   只不过盖章人写的是 ``platform:identity-provider:<name>``，审计上一眼看得出是服务商判的。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models.orm import IdentityVerificationModel
from services.identity_provider.base import (
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
    OUTCOME_VERIFIED,
    ProviderDecision,
    ProviderError,
    ProviderNotConfigured,
)
from services.identity_provider.registry import configured_name, resolve_provider
from services.identity_provider.signature import sign_timestamped_hmac
from services.identity_verification import (
    IdentityVerificationError,
    assert_can_submit,
    mark_verified,
)

SESSION_TTL_SECONDS = 1800
#: 盖章人前缀：一眼看出这条核验是服务商判的，不是人工复核的。
PROVIDER_REVIEWER_PREFIX = "platform:identity-provider:"
#: 每个身份最多留多少条核验事件（够回溯就行，不让 JSON 无界膨胀）。
MAX_EVENTS = 20


def _now() -> datetime:
    return datetime.utcnow()


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _state_of(row: Any) -> dict[str, Any]:
    state = getattr(row, "provider", None)
    if not isinstance(state, dict):
        state = {}
    active = state.get("active")
    events = state.get("events")
    return {
        "active": dict(active) if isinstance(active, dict) else {},
        "events": list(events) if isinstance(events, list) else [],
    }


def _write_state(row: Any, state: dict[str, Any]) -> None:
    """整块替换（不原地改）：JSON 列的变更必须由赋值动作带出去。"""
    row.provider = {
        "active": dict(state.get("active") or {}),
        "events": list(state.get("events") or [])[-MAX_EVENTS:],
    }


def record_event(row: Any, event: str, *, applied: bool = False, **detail: Any) -> None:
    """往审计里加一条。detail 只放白名单字段：会话号、结论、原因码 —— 不放报文原文。"""
    state = _state_of(row)
    clean = {key: value for key, value in detail.items() if value not in (None, "", [], {})}
    state["events"] = state["events"] + [
        {"at": _iso(_now()), "event": event, "applied": bool(applied), "detail": clean}
    ]
    _write_state(row, state)


def callback_url_for(identity_id: str, provider_name: str) -> str:
    base = (getattr(get_settings(), "identity_provider_public_base_url", "") or "").strip().rstrip("/")
    if not base:
        raise ProviderNotConfigured(
            503,
            "IDENTITY_PROVIDER_PUBLIC_BASE_URL must be set to the public origin of this API "
            "so the provider can call us back",
        )
    return (
        f"{base}/v1/identity/{identity_id}/verification/provider-callback/{provider_name}"
    )


async def _load_row(db: AsyncSession, identity_id: str) -> IdentityVerificationModel:
    row = await db.get(IdentityVerificationModel, identity_id)
    if row is None:
        row = IdentityVerificationModel(identity_id=identity_id)
        db.add(row)
    return row


async def start_session(
    db: AsyncSession, *, identity_id: str, return_url: str | None = None
) -> dict[str, Any]:
    """开一次核验：拿到「浏览器该打开哪儿」，会话号记在本地行上。"""
    provider = resolve_provider()
    settings = get_settings()
    row = await _load_row(db, identity_id)
    session_id = uuid.uuid4().hex
    callback_url = callback_url_for(identity_id, provider.name)

    created = await provider.create_session(
        identity_id=identity_id,
        session_id=session_id,
        callback_url=callback_url,
        return_url=return_url,
    )

    state = _state_of(row)
    state["active"] = {
        "name": provider.name,
        "session_id": session_id,
        "provider_session_id": created.get("provider_session_id"),
        "mode": created.get("mode"),
        "created_at": _iso(_now()),
        "expires_at": _iso(
            _now()
            + timedelta(
                seconds=int(created.get("expires_in_seconds") or SESSION_TTL_SECONDS)
            )
        ),
        "return_url": return_url,
    }
    _write_state(row, state)
    record_event(
        row,
        "session_created",
        provider=provider.name,
        session_id=session_id,
        provider_session_id=created.get("provider_session_id"),
    )
    row.updated_at = _now()
    await db.flush()
    await db.commit()

    # 交给浏览器的东西：只有会话号 + 服务商入口，没有任何我们的密钥。
    return {
        "identity_id": identity_id,
        "status": row.status,
        "session_id": session_id,
        **{key: value for key, value in created.items() if key != "session_id"},
        "callback_url": callback_url,
        "tolerance_seconds": int(
            getattr(settings, "identity_provider_callback_tolerance_seconds", 300) or 300
        ),
    }


def _bind_decision(row: Any, decision: ProviderDecision, provider_name: str) -> str:
    """把判定绑回我们开出去的那次会话。绑不上就是 409 —— 绝不给任意身份盖章。"""
    state = _state_of(row)
    active = state.get("active") or {}
    if not active or not active.get("session_id"):
        raise ProviderError(409, "no identity verification session is waiting for this identity")
    if str(active.get("name") or "") != provider_name:
        raise ProviderError(
            409,
            "this identity verification session belongs to a different provider",
        )
    expires_at = active.get("expires_at")
    if expires_at:
        try:
            if _now() > datetime.fromisoformat(expires_at):
                raise ProviderError(409, "this identity verification session has expired")
        except ValueError:
            pass
    if decision.session_id and decision.session_id != active.get("session_id"):
        raise ProviderError(409, "callback references an unknown verification session")
    if decision.provider_session_id and active.get("provider_session_id"):
        if decision.provider_session_id != active.get("provider_session_id"):
            raise ProviderError(409, "callback references a different provider session")
    if not decision.session_id and not decision.provider_session_id:
        raise ProviderError(409, "callback does not reference any verification session")
    return str(active.get("session_id"))


def _apply(row: Any, *, provider_name: str, decision: ProviderDecision, session_id: str) -> dict[str, Any]:
    """把归一化后的判定落到主身份认证状态机上。"""
    note_bits = [f"provider={provider_name}", f"session={session_id}"]
    if decision.reason_code:
        note_bits.append(f"reason={decision.reason_code}")
    if decision.risk_level:
        note_bits.append(f"risk={decision.risk_level}")
    note = "第三方实名/活体核验：" + " ".join(note_bits)

    if row.status == "verified":
        record_event(
            row,
            "decision_ignored",
            provider=provider_name,
            session_id=session_id,
            outcome=decision.outcome,
            reason="already_verified",
        )
        return {"applied": False, "reason": "already_verified"}

    if decision.outcome == OUTCOME_PENDING:
        record_event(
            row,
            "decision_pending",
            provider=provider_name,
            session_id=session_id,
            outcome=decision.outcome,
        )
        return {"applied": False, "reason": "provider_still_processing"}

    # none / rejected → pending 是合法迁移（证据已到，进入判定）；再 pending → 结论。
    try:
        assert_can_submit(row.status)
    except IdentityVerificationError as exc:
        return {"applied": False, "reason": exc.message}
    row.status = "pending"
    row.updated_at = _now()

    if decision.outcome == OUTCOME_VERIFIED:
        mark_verified(
            row,
            reviewer_identity_id=PROVIDER_REVIEWER_PREFIX + provider_name,
            note=note,
        )
    else:
        row.status = "rejected"
        row.reviewer_identity_id = PROVIDER_REVIEWER_PREFIX + provider_name
        row.review_note = note[:2000]
        row.verified_at = None
    row.updated_at = _now()

    record_event(
        row,
        "decision_applied",
        applied=True,
        provider=provider_name,
        session_id=session_id,
        outcome=decision.outcome,
        reason_code=decision.reason_code,
        raw_digest=decision.raw_digest,
    )
    return {"applied": True, "reason": decision.outcome}


def _finish_session(row: Any, *, outcome: str, provider_session_id: str | None) -> None:
    state = _state_of(row)
    active = state.get("active") or {}
    if active:
        active = dict(active)
        active["status"] = "completed" if outcome == OUTCOME_VERIFIED else (outcome or "closed")
        active["closed_at"] = _iso(_now())
        if provider_session_id:
            active["provider_session_id"] = provider_session_id
    state["active"] = active
    _write_state(row, state)


async def apply_callback(
    db: AsyncSession, *, identity_id: str, provider_name: str, headers: Any, raw_body: bytes
) -> dict[str, Any]:
    """服务商回调入口。验签 → 绑定 → 必要时回查 → 置位。"""
    provider = resolve_provider(provider_name)
    decision = (await provider.parse_callback(headers=headers, raw_body=raw_body)).normalized()

    row = await db.get(IdentityVerificationModel, identity_id)
    if row is None:
        raise ProviderError(404, "this identity has no verification record")

    session_id = _bind_decision(row, decision, provider_name)

    if decision.requires_pull and decision.provider_session_id:
        # pull 型服务商：回调只当作「去查一下」的信号，判定权在回查那一侧。
        decision = (
            await provider.fetch_result(provider_session_id=decision.provider_session_id)
        ).normalized()

    result = _apply(row, provider_name=provider_name, decision=decision, session_id=session_id)
    if result["applied"]:
        _finish_session(
            row, outcome=decision.outcome, provider_session_id=decision.provider_session_id
        )
    await db.flush()
    await db.commit()
    return {
        "identity_id": identity_id,
        "provider": provider_name,
        "session_id": session_id,
        "outcome": decision.outcome,
        "applied": result["applied"],
        "reason": result["reason"],
        "status": row.status,
        "verified_at": _iso(row.verified_at),
    }


async def sync_active_session(db: AsyncSession, *, identity_id: str) -> dict[str, Any]:
    """操作台主动回查一次（pull 型服务商：用户做完核验，前端轮询这个接口拿结论）。"""
    provider = resolve_provider()
    row = await db.get(IdentityVerificationModel, identity_id)
    if row is None:
        raise ProviderError(404, "this identity has no verification record")
    state = _state_of(row)
    active = state.get("active") or {}
    provider_session_id = active.get("provider_session_id")
    session_id = active.get("session_id")
    if not session_id or not provider_session_id:
        raise ProviderError(409, "no identity verification session is waiting for this identity")
    if str(active.get("name") or "") != provider.name:
        raise ProviderError(409, "the waiting session belongs to a different provider")
    if not provider.supports_pull():
        raise ProviderError(409, f"provider {provider.name} does not support result lookups")
    try:
        assert_can_submit(row.status)
    except IdentityVerificationError as exc:
        raise ProviderError(409, exc.message) from exc

    decision = (await provider.fetch_result(provider_session_id=provider_session_id)).normalized()
    result = _apply(row, provider_name=provider.name, decision=decision, session_id=session_id)
    if result["applied"]:
        _finish_session(row, outcome=decision.outcome, provider_session_id=provider_session_id)
    await db.flush()
    await db.commit()
    return {
        "identity_id": identity_id,
        "provider": provider.name,
        "session_id": session_id,
        "outcome": decision.outcome,
        "applied": result["applied"],
        "reason": result["reason"],
        "status": row.status,
        "verified_at": _iso(row.verified_at),
    }


def provider_view(row: Any) -> dict[str, Any]:
    """给操作台看的核验现状（不含任何密钥，也不含服务商链接里的令牌）。"""
    state = _state_of(row)
    active = state.get("active") or {}
    events = state.get("events") or []
    return {
        "active": {
            "name": active.get("name"),
            "session_id": active.get("session_id"),
            "status": active.get("status") or ("waiting" if active else None),
            "created_at": active.get("created_at"),
            "expires_at": active.get("expires_at"),
        }
        if active
        else None,
        "last_event": events[-1] if events else None,
        "events": events[-5:],
    }


def build_mock_push(
    *, identity_id: str, session_id: str, outcome: str, reason_code: str | None = None
) -> tuple[bytes, str]:
    """本地模拟服务商推一条回调（**和真回调走完全相同的验签路径**）。

    只在 IDENTITY_PROVIDER=mock 且非生产环境可用；见 api/routes/identity_verification.py。
    """
    settings = get_settings()
    secret = (getattr(settings, "identity_provider_callback_secret", "") or "").strip()
    if not secret:
        raise ProviderNotConfigured(503, "IDENTITY_PROVIDER_CALLBACK_SECRET is not set")
    body = json.dumps(
        {
            "session_id": session_id,
            "identity_id": identity_id,
            "provider_session_id": "mock-" + session_id,
            "outcome": outcome,
            "reason_code": reason_code,
            "occurred_at": _iso(_now()),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return body, sign_timestamped_hmac(secret=secret, raw_body=body)


__all__ = [
    "MAX_EVENTS",
    "PROVIDER_REVIEWER_PREFIX",
    "SESSION_TTL_SECONDS",
    "apply_callback",
    "build_mock_push",
    "callback_url_for",
    "configured_name",
    "provider_view",
    "record_event",
    "start_session",
    "sync_active_session",
]
