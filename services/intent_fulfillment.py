"""End-to-end intent fulfillment: discover → negotiate → voucher → evidence → settle.

This is the assistant-facing spine that closes the gaps between discovery and
Karma delivery rails. Unlike trade preauth launch, it does NOT require Runtime Keys
or automation-policy — those remain optional enterprise gates on /v1/trade/*.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import (
    ExecutionReceipt,
    SettlementState,
    TaskContract,
    TaskStatus,
    ToolStatus,
    VoucherStatus,
)
from core.settlement.engine import canonical_task_status
from db.models.orm import AgentModel, CapacityModel, TaskContractModel, VoucherModel
from db.stores.settlement_store import PostgresSettlementStore
from services.agent_directory import agent_row_to_card, connect_agent, ensure_directory_merchants
from services.agent_trust import apply_trust_rerank, record_worker_settlement_outcome
from services.capacity_resolution import apply_capacity_resolution
from services.identity_agents import ensure_agent_for_identity
from services.agent_automation_policy import get_automation_policy
from services.human_confirmation_policy import (
    ConfirmationPolicyError,
    allow_demo_confirmation_bypass,
    assert_step_allowed,
    buyer_fulfill_confirm_steps,
    create_confirmation_session,
    get_confirmation_session,
    is_high_risk_scene,
    next_required_confirm_step,
    plan_confirmations,
    require_known_scene,
    seller_must_confirm_accept,
    step_already_satisfied,
    task_type_to_scene_id,
)
from services.important_fields_capture import (
    CaptureError,
    auto_triple_lock_fields,
    require_matched_capture,
    scene_requires_important_fields,
)
from services.important_fields_standard import example_for_scene
from services.intent_discovery import (
    build_discovery_plan,
    parse_intent_for_discovery,
    rank_candidates,
)
from services.settlement_cycle_guard import assert_lock_does_not_close_payment_cycle
from services.settlement_receipt_release_guard import (
    ensure_success_execution_receipt_before_seller_payout,
)
from services.settlement_transitions import apply_settlement_transition
from services.settlement_voucher import mark_voucher_used_if_linked
from services.signing import sha256_of, signing_service
from services.voucher_events import record_voucher_event
from services.voucher_lifecycle import accept_voucher_row

logger = logging.getLogger(__name__)

ORCH_ROUTE = "/internal/intent_fulfillment/v1"
ORCH_ACTOR = "intent_fulfillment_v1"


def _hash_hex(data: Any) -> str:
    raw = data if isinstance(data, str) else sha256_of(data)
    if isinstance(data, str):
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
    return raw


_DEMO_MERCHANTS = [
    {
        "agent_id": "merchant-food-demo",
        "name": "Demo Food Merchant",
        "capabilities": ["order_food", "karma_settle"],
        "endpoint": os.getenv("A2A_DEMO_FOOD_ENDPOINT", ""),
    },
    {
        "agent_id": "merchant-flight-demo",
        "name": "Demo Flight Merchant",
        "capabilities": ["book_flight", "karma_settle"],
        "endpoint": os.getenv("A2A_DEMO_FLIGHT_ENDPOINT", ""),
    },
    {
        "agent_id": "merchant-hotel-demo",
        "name": "Demo Hotel Merchant",
        "capabilities": ["book_hotel", "karma_settle"],
        "endpoint": os.getenv("A2A_DEMO_HOTEL_ENDPOINT", ""),
    },
    {
        "agent_id": "merchant-data-demo",
        "name": "Demo Data Worker",
        "capabilities": [
            "data_processing",
            "karma_settle",
            "api.translate",
            "api.caption",
            "api.labeling",
        ],
        "endpoint": "",
    },
]


async def _collect_candidate_cards(db: AsyncSession) -> list[dict[str, Any]]:
    """All Karma-connected directory agents (connect ⇒ discoverable)."""
    if os.getenv("INTENT_FULFILL_DISABLE_DEMO_MERCHANTS", "0") not in {"1", "true"}:
        await ensure_directory_merchants(db, _DEMO_MERCHANTS)

    cards: list[dict[str, Any]] = []
    result = await db.execute(select(AgentModel).where(AgentModel.is_active == True))  # noqa: E712
    for row in result.scalars().all():
        cards.append(agent_row_to_card(row))

    registry_url = os.getenv("A2A_REGISTRY_URL", "").strip()
    if registry_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{registry_url.rstrip('/')}/api/agents",
                    params={"limit": 50},
                )
                if resp.is_success:
                    data = resp.json()
                    remote = data if isinstance(data, list) else data.get("agents", [])
                    for c in remote:
                        c["_source"] = "a2a_registry"
                        # Also upsert into directory so future discovery is local-first
                        aid = str(c.get("agent_id") or "")
                        if aid:
                            await connect_agent(
                                db,
                                agent_id=aid,
                                name=str(c.get("name") or aid),
                                role="worker",
                                endpoint_url=c.get("endpoint") or c.get("endpoint_url"),
                                capabilities=list(c.get("capabilities") or []),
                            )
                        cards.append(c)
        except httpx.HTTPError:
            pass
    return cards


async def _ensure_capacity(db: AsyncSession, buyer_id: str, amount: float, *, auto_fund: bool) -> None:
    row = await db.get(CapacityModel, buyer_id)
    if not row:
        if not auto_fund:
            raise HTTPException(409, "buyer has no capacity; lock USDC first")
        row = CapacityModel(
            identity_id=buyer_id,
            total_locked_usdc=0.0,
            total_bill_credits=0.0,
            available_credits=0.0,
            reserved_credits=0.0,
            in_progress_credits=0.0,
            confirmed_progress_credits=0.0,
            disputed_credits=0.0,
            pending_settlement_credits=0.0,
            burned_credits=0.0,
            released_credits=0.0,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        await db.flush()

    need = amount - float(row.available_credits or 0.0)
    if need > 1e-9:
        if not auto_fund:
            raise HTTPException(409, "insufficient buyer available credits")
        row.total_locked_usdc = float(row.total_locked_usdc or 0.0) + need
        row.total_bill_credits = float(row.total_bill_credits or 0.0) + need
        row.available_credits = float(row.available_credits or 0.0) + need
        row.updated_at = datetime.utcnow()
        await db.flush()


async def _negotiate_a2a(
    *,
    endpoint: str,
    skill: str,
    params: dict[str, Any],
    buyer_id: str,
    amount: float,
) -> dict[str, Any]:
    """Best-effort A2A negotiate against merchant endpoint (EIP-712 if required)."""
    from eth_account import Account

    task_id = f"a2a-{uuid.uuid4().hex[:12]}"
    wallet = Account.create()
    base = endpoint.rstrip("/")

    import sys
    from pathlib import Path

    bridge = str(Path(__file__).resolve().parents[1] / "packages" / "karma-a2a-bridge")
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    from eip712_auth import OP_CONFIRM, OP_CREATE, OP_HANDOFF, OP_SUBMIT, sign_a2a_task_op  # type: ignore

    def make_auth(op: str, nonce: int, amount_micro: int = 0) -> dict[str, Any]:
        deadline = int(datetime.now(tz=timezone.utc).timestamp()) + 600
        sig = sign_a2a_task_op(
            private_key=wallet.key,
            task_id=task_id,
            op_type=op,
            agent=wallet.address,
            requester_id=buyer_id,
            amount_micro=amount_micro,
            nonce=nonce,
            deadline=deadline,
        )
        return {
            "agent": wallet.address,
            "signature": sig,
            "nonce": nonce,
            "deadline": deadline,
            "amount_micro": amount_micro,
            "requester_id": buyer_id,
        }

    stages: dict[str, Any] = {"task_id": task_id, "endpoint": base, "mode": "remote_a2a"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Probe if EIP-712 required
            create_body = {
                "task_id": task_id,
                "skill": skill,
                "params": params,
                "requester_id": buyer_id,
                "auth": make_auth(OP_CREATE, 1),
            }
            r = await client.post(f"{base}/a2a/task", json=create_body)
            if r.status_code == 401:
                # retry without if bridge allows — already signed; fail soft
                stages["create"] = {"status_code": r.status_code, "detail": r.text[:300]}
                stages["ok"] = False
                return stages
            if not r.is_success:
                stages["create"] = {"status_code": r.status_code, "detail": r.text[:300]}
                stages["ok"] = False
                return stages
            stages["create"] = r.json()

            micro = int(round(float(amount) * 1_000_000))
            conf = await client.post(
                f"{base}/a2a/task/{task_id}/confirm",
                json={
                    "seller_id": "",
                    "amount": amount,
                    "auth": make_auth(OP_CONFIRM, 2, amount_micro=micro),
                },
            )
            stages["confirm"] = conf.json() if conf.is_success else {"status_code": conf.status_code}
            if not conf.is_success:
                stages["ok"] = False
                return stages

            sub = await client.post(
                f"{base}/a2a/task/{task_id}/submit",
                json={
                    "result": {"delivered": True, "summary": "orchestrated delivery"},
                    "auth": make_auth(OP_SUBMIT, 3),
                },
            )
            stages["submit"] = sub.json() if sub.is_success else {"status_code": sub.status_code}

            hand = await client.post(
                f"{base}/a2a/task/{task_id}/handoff",
                json={
                    "buyer_id": buyer_id,
                    "seller_id": "",
                    "auth": make_auth(OP_HANDOFF, 4),
                },
            )
            stages["handoff"] = hand.json() if hand.is_success else {"status_code": hand.status_code}
            stages["ok"] = bool(conf.is_success)
            stages["voucher_id"] = (conf.json() or {}).get("voucher_id") if conf.is_success else None
            return stages
    except Exception as exc:  # noqa: BLE001 — soft-fail negotiate
        stages["ok"] = False
        stages["error"] = str(exc)
        return stages


async def fulfill_intent(
    db: AsyncSession,
    *,
    requirement_text: str,
    buyer_identity_id: str,
    amount: float | None = None,
    seller_identity_id: str | None = None,
    auto_fund_capacity: bool = True,
    negotiate_a2a: bool = True,
    auto_complete: bool = False,
    buyer_signature: str = "0xintent_fulfillment",
    require_owner_confirmation: bool = True,
    confirmation_session_id: str | None = None,
    seller_confirmation_session_id: str | None = None,
    policy_auto_allowed: bool = False,
    scene_id: str | None = None,
    confirmation_context: dict[str, Any] | None = None,
    require_important_fields_match: bool | None = None,
    important_fields_capture_id: str | None = None,
    important_fields: dict[str, Any] | None = None,
    auto_lock_important_fields: bool = False,
) -> dict[str, Any]:
    """
    Run discover → buyer confirm(s) → Important Fields → seller confirm (when
    required) → negotiate → voucher → settlement (+ optional full settle).

    Real-world gates (P4):
    - buyer steps from scene policy (daily: accept_order; B2B/high-risk:
      select_offer → accept_order) → ``awaiting_owner_confirmation``
    - seller OWNER_CONFIRM scenes → ``awaiting_seller_confirmation``
    - commerce/B2B/high-risk IF triple MATCHED →
      ``awaiting_important_fields_match`` (or auto-lock in demo envs)
    """
    timeline: list[dict[str, Any]] = []
    query = parse_intent_for_discovery(requirement_text, amount=amount)
    pay_amount = float(amount if amount is not None else (query.amount or 10.0))
    if pay_amount <= 0:
        raise HTTPException(400, "amount must be > 0")

    cards = await _collect_candidate_cards(db)
    ranked = rank_candidates(cards, query, limit=30)
    ranked = await apply_trust_rerank(
        db,
        ranked,
        limit=10,
        scene_id=query.scene_id,
        task_type=query.task_type,
        # Soft prefer at fulfill discover; hard P2 seller verify still runs below
        drop_ineligible=False,
        enforce_scene_policy=False,
    )
    plan = build_discovery_plan(query=query, candidates=ranked, buyer_identity_id=buyer_identity_id)
    timeline.append({
        "stage": "discover",
        "ok": True,
        "candidates": len(ranked),
        "ranking": "priority+capability+trust",
        "scene_id": query.scene_id,
        "top_trust": (ranked[0].get("trust") if ranked else None),
        "top_priority": (ranked[0].get("priority") if ranked else None),
    })

    seller_id = seller_identity_id or (plan["recommended"]["agent_id"] if plan["recommended"] else None)
    if not seller_id:
        raise HTTPException(404, "no matching agent/merchant found for this intent")
    recommended = plan["recommended"] or {"agent_id": seller_id}
    skill = (query.skills[0] if query.skills else "generic_task")

    # Scene is derived from intent — clients cannot loosen confirmation via scene_id
    inferred_scene = task_type_to_scene_id(query.task_type)
    requested_scene = (scene_id or "").strip()
    if requested_scene and requested_scene != inferred_scene:
        raise HTTPException(
            400,
            f"scene_id '{requested_scene}' does not match intent-inferred scene '{inferred_scene}'",
        )
    resolved_scene = inferred_scene
    try:
        require_known_scene(resolved_scene)
    except ConfirmationPolicyError as exc:
        raise HTTPException(400, str(exc)) from exc

    # P2 seller boundary gate — security before efficiency
    from services.agent_boundary import get_agent_boundary
    from services.agent_boundary_verify import (
        BoundaryVerifyError,
        assert_seller_boundary_for_fulfill,
    )

    seller_row = await db.get(AgentModel, seller_id)
    seller_boundary = get_agent_boundary(seller_id)
    try:
        seller_verify = assert_seller_boundary_for_fulfill(
            boundary=seller_boundary,
            scene_id=resolved_scene,
            identity_class=getattr(seller_row, "identity_class", None) if seller_row else None,
            p1_ready=bool(getattr(seller_row, "p1_ready", False)) if seller_row else False,
            stored_boundary_hash=getattr(seller_row, "boundary_hash", None) if seller_row else None,
        )
        timeline.append({
            "stage": "seller_boundary_verify",
            "ok": True,
            "scene_id": resolved_scene,
            "p1_ready": bool(getattr(seller_row, "p1_ready", False)) if seller_row else False,
            "gaps": seller_verify.get("gaps") or [],
        })
    except BoundaryVerifyError as exc:
        timeline.append({
            "stage": "seller_boundary_verify",
            "ok": False,
            "scene_id": resolved_scene,
            "gaps": exc.gaps,
            "error": str(exc),
        })
        raise HTTPException(
            403,
            {
                "error": "seller_boundary_verify_failed",
                "detail": str(exc),
                "gaps": exc.gaps,
                "scene_id": resolved_scene,
                "seller_identity_id": seller_id,
                "security_note_zh": (
                    "卖方边界未通过 P2 核验：未声明场景、确认策略被放宽、或 P1 未就绪。"
                    "安全优先，拒绝履约。"
                ),
                "next_steps": [
                    f"GET /v1/agents/{seller_id}/boundary/verify?scene_id={resolved_scene}",
                    f"GET /v1/agents/{seller_id}/p1-status",
                    "商家需 connect-from-template + responsibility_ack 后重试",
                ],
            },
        ) from exc

    high_risk = is_high_risk_scene(resolved_scene)
    if not require_owner_confirmation:
        if high_risk or not allow_demo_confirmation_bypass():
            raise HTTPException(
                403,
                "require_owner_confirmation=false is forbidden for high-risk scenes "
                "and outside development/test environments",
            )

    # POLICY_AUTO only when a saved automation-policy covers this amount (ignore client bool)
    # High-risk scenes never get POLICY_AUTO shortcuts
    effective_policy_auto = False
    _ = policy_auto_allowed
    if require_owner_confirmation and not high_risk:
        saved_policy = await get_automation_policy(db, buyer_identity_id)
        if (
            saved_policy is not None
            and bool(getattr(saved_policy, "responsibility_acknowledged", False))
            and (
                bool(getattr(saved_policy, "auto_enabled", False))
                or bool(getattr(saved_policy, "preauth_enabled", False))
            )
            and float(pay_amount) <= float(getattr(saved_policy, "single_limit", 0) or 0) + 1e-9
        ):
            effective_policy_auto = True

    interaction_ref = f"fulfill:{buyer_identity_id}:{seller_id}"
    confirm_ctx = {
        "amount": pay_amount,
        "currency": "USDC",
        "merchant": recommended.get("name") or seller_id,
        "seller": recommended.get("name") or seller_id,
        **(confirmation_context or {}),
    }
    confirm_ctx["amount"] = pay_amount
    buyer_steps = buyer_fulfill_confirm_steps(resolved_scene)
    deferred_accept_session: str | None = None

    # P4 buyer multi-step confirmation (reality-tuned per scene)
    if require_owner_confirmation:
        for step in buyer_steps:
            if step_already_satisfied(
                scene_id=resolved_scene,
                role="buyer",
                step=step,
                owner_agent_id=buyer_identity_id,
                interaction_ref=interaction_ref,
                policy_auto_allowed=effective_policy_auto,
            ):
                timeline.append({
                    "stage": "owner_confirmation",
                    "ok": True,
                    "scene_id": resolved_scene,
                    "step": step,
                    "reason": "already_confirmed_or_auto",
                })
                continue

            applied = False
            if confirmation_session_id:
                try:
                    pub = get_confirmation_session(confirmation_session_id)
                    if pub.get("step") == step and pub.get("status") == "CONFIRMED":
                        # Final money step: defer consume until IF passes
                        consume_now = step != "accept_order"
                        gate_ok = assert_step_allowed(
                            scene_id=resolved_scene,
                            role="buyer",
                            step=step,
                            confirmation_session_id=confirmation_session_id,
                            policy_auto_allowed=effective_policy_auto,
                            expected_owner_agent_id=buyer_identity_id,
                            amount=pay_amount,
                            consume=consume_now,
                            expected_interaction_ref=interaction_ref,
                        )
                        if step == "accept_order":
                            deferred_accept_session = confirmation_session_id
                        timeline.append({
                            "stage": "owner_confirmation",
                            "ok": True,
                            "scene_id": resolved_scene,
                            "step": step,
                            "reason": gate_ok.get("reason"),
                            "policy_auto": effective_policy_auto,
                        })
                        applied = True
                except ConfirmationPolicyError:
                    applied = False

            if applied:
                continue

            sess = create_confirmation_session(
                scene_id=resolved_scene,
                role="buyer",
                step=step,
                owner_agent_id=buyer_identity_id,
                context=confirm_ctx,
                interaction_ref=interaction_ref,
                policy_auto_allowed=effective_policy_auto,
            )
            if sess.get("skipped"):
                timeline.append({
                    "stage": "owner_confirmation",
                    "ok": True,
                    "scene_id": resolved_scene,
                    "step": step,
                    "reason": "auto",
                })
                continue
            conf_plan = plan_confirmations(
                scene_id=resolved_scene,
                role="buyer",
                policy_auto_allowed=effective_policy_auto,
                context=confirm_ctx,
            )
            next_step = next_required_confirm_step(
                scene_id=resolved_scene,
                role="buyer",
                steps=buyer_steps,
                owner_agent_id=buyer_identity_id,
                interaction_ref=interaction_ref,
                policy_auto_allowed=effective_policy_auto,
            )
            timeline.append({
                "stage": "owner_confirmation",
                "ok": False,
                "scene_id": resolved_scene,
                "step": step,
                "awaiting": True,
            })
            return {
                "status": "awaiting_owner_confirmation",
                "flow": (
                    "intent → discover → buyer Yes/No (per scene) → IF lock → "
                    "seller Yes/No (when required) → voucher → settle"
                ),
                "scene_id": resolved_scene,
                "high_risk": high_risk,
                "intent": query.to_dict(),
                "discovery": {
                    "recommended": recommended,
                    "candidates": ranked,
                },
                "buyer_identity_id": buyer_identity_id,
                "seller_identity_id": seller_id,
                "amount": pay_amount,
                "confirmation": sess,
                "confirmation_plan": {
                    "must_confirm_steps": [x["step"] for x in conf_plan["must_confirm"]],
                    "auto_ok_steps": [x["step"] for x in conf_plan["auto_ok"]],
                    "buyer_fulfill_steps": buyer_steps,
                    "next_required_step": next_step or step,
                    "summary_zh": conf_plan["summary_zh"],
                    "agent_ux_zh": conf_plan["agent_ux_zh"],
                },
                "owner_prompt_zh": sess.get("prompt_zh"),
                "timeline": timeline,
                "next_steps": [
                    "show owner_prompt_zh to owner (Yes/No only)",
                    f"POST /v1/confirmations/sessions/{sess.get('session_id')}/decide "
                    '{"confirm": true, "actor_agent_id": "<buyer_identity_id>"}',
                    "POST /v1/orchestration/fulfill-intent again with "
                    "confirmation_session_id",
                ],
            }

    # Important Fields triple-match gate (real commerce / B2B / high-risk)
    must_if = (
        scene_requires_important_fields(resolved_scene)
        if require_important_fields_match is None
        else bool(require_important_fields_match)
    )
    if high_risk:
        must_if = True
    fields_lock: dict[str, Any] | None = None
    if must_if:
        try:
            if important_fields_capture_id:
                fields_lock = require_matched_capture(
                    capture_id=important_fields_capture_id,
                    scene_id=resolved_scene,
                    interaction_ref=interaction_ref,
                    expected_amount=pay_amount,
                )
            elif (
                auto_lock_important_fields
                and allow_demo_confirmation_bypass()
                and not high_risk
            ):
                fields = dict(important_fields or example_for_scene(resolved_scene)["fields"])
                if "amount" in fields:
                    fields["amount"] = f"{pay_amount:.2f}"
                fields_lock = auto_triple_lock_fields(
                    scene_id=resolved_scene,
                    fields=fields,
                    interaction_ref=interaction_ref,
                    buyer_agent_id=buyer_identity_id or "demo-buyer",
                    seller_agent_id=seller_id or "demo-seller",
                )
            else:
                raise CaptureError("MATCHED important_fields_capture_id required")
            timeline.append({
                "stage": "important_fields_lock",
                "ok": True,
                "capture_id": fields_lock.get("capture_id"),
                "fields_hash": fields_lock.get("protocol_fields_hash")
                or fields_lock.get("fields_hash"),
                "status": fields_lock.get("status"),
            })
        except (CaptureError, Exception) as exc:  # noqa: BLE001
            example = None
            try:
                example = example_for_scene(resolved_scene)
            except Exception:  # noqa: BLE001
                example = None
            timeline.append({
                "stage": "important_fields_lock",
                "ok": False,
                "awaiting": True,
                "error": str(exc),
            })
            return {
                "status": "awaiting_important_fields_match",
                "flow": "intent → discover → owner confirm → IF triple-match → voucher → settle",
                "scene_id": resolved_scene,
                "high_risk": high_risk,
                "intent": query.to_dict(),
                "discovery": {"recommended": recommended, "candidates": ranked},
                "buyer_identity_id": buyer_identity_id,
                "seller_identity_id": seller_id,
                "amount": pay_amount,
                "confirmation_session_id": confirmation_session_id,
                "important_fields_example": example,
                "timeline": timeline,
                "next_steps": [
                    "POST /v1/standards/important-fields/captures with extracted fields "
                    "(bind buyer_agent_id + seller_agent_id)",
                    "GET …/session-key?role=buyer|seller (TLS+auth)",
                    "buyer+seller POST …/submit-encrypted (karma2. ciphertext + submitter_agent_id)",
                    "POST …/match-secure → status MATCHED (sealed)",
                    "retry fulfill-intent with important_fields_capture_id "
                    "(or auto_lock_important_fields=true in development, non-high-risk)",
                ],
                "detail": str(exc),
            }

    # Consume final buyer accept_order only after IF gate passes
    if require_owner_confirmation and deferred_accept_session:
        assert_step_allowed(
            scene_id=resolved_scene,
            role="buyer",
            step="accept_order",
            confirmation_session_id=deferred_accept_session,
            policy_auto_allowed=effective_policy_auto,
            expected_owner_agent_id=buyer_identity_id,
            amount=pay_amount,
            consume=True,
            expected_interaction_ref=interaction_ref,
        )

    # P4 seller accept_order — OWNER_CONFIRM scenes (B2B / finance / healthcare / …)
    if require_owner_confirmation and seller_must_confirm_accept(resolved_scene):
        seller_policy_auto = False
        if not high_risk:
            seller_saved = await get_automation_policy(db, seller_id)
            if (
                seller_saved is not None
                and bool(getattr(seller_saved, "responsibility_acknowledged", False))
                and (
                    bool(getattr(seller_saved, "auto_enabled", False))
                    or bool(getattr(seller_saved, "preauth_enabled", False))
                )
                and float(pay_amount) <= float(getattr(seller_saved, "single_limit", 0) or 0) + 1e-9
            ):
                seller_policy_auto = True
        if not step_already_satisfied(
            scene_id=resolved_scene,
            role="seller",
            step="accept_order",
            owner_agent_id=seller_id,
            interaction_ref=interaction_ref,
            policy_auto_allowed=seller_policy_auto,
        ):
            applied_seller = False
            if seller_confirmation_session_id:
                try:
                    assert_step_allowed(
                        scene_id=resolved_scene,
                        role="seller",
                        step="accept_order",
                        confirmation_session_id=seller_confirmation_session_id,
                        policy_auto_allowed=seller_policy_auto,
                        expected_owner_agent_id=seller_id,
                        amount=pay_amount,
                        consume=True,
                        expected_interaction_ref=interaction_ref,
                    )
                    timeline.append({
                        "stage": "seller_confirmation",
                        "ok": True,
                        "scene_id": resolved_scene,
                        "step": "accept_order",
                    })
                    applied_seller = True
                except ConfirmationPolicyError:
                    applied_seller = False
            if not applied_seller:
                seller_sess = create_confirmation_session(
                    scene_id=resolved_scene,
                    role="seller",
                    step="accept_order",
                    owner_agent_id=seller_id,
                    context=confirm_ctx,
                    interaction_ref=interaction_ref,
                    policy_auto_allowed=seller_policy_auto,
                )
                if not seller_sess.get("skipped"):
                    timeline.append({
                        "stage": "seller_confirmation",
                        "ok": False,
                        "scene_id": resolved_scene,
                        "step": "accept_order",
                        "awaiting": True,
                    })
                    return {
                        "status": "awaiting_seller_confirmation",
                        "flow": (
                            "intent → buyer confirm → IF → seller Yes/No → voucher → settle"
                        ),
                        "scene_id": resolved_scene,
                        "high_risk": high_risk,
                        "intent": query.to_dict(),
                        "discovery": {"recommended": recommended, "candidates": ranked},
                        "buyer_identity_id": buyer_identity_id,
                        "seller_identity_id": seller_id,
                        "amount": pay_amount,
                        "confirmation": seller_sess,
                        "confirmation_session_id": confirmation_session_id,
                        "important_fields_capture_id": (
                            (fields_lock or {}).get("capture_id")
                            if fields_lock
                            else important_fields_capture_id
                        ),
                        "owner_prompt_zh": seller_sess.get("prompt_zh"),
                        "timeline": timeline,
                        "next_steps": [
                            "show owner_prompt_zh to seller owner (Yes/No only)",
                            f"POST /v1/confirmations/sessions/{seller_sess.get('session_id')}/decide "
                            '{"confirm": true, "actor_agent_id": "<seller_identity_id>"}',
                            "POST /v1/orchestration/fulfill-intent again with "
                            "seller_confirmation_session_id",
                        ],
                    }
                timeline.append({
                    "stage": "seller_confirmation",
                    "ok": True,
                    "scene_id": resolved_scene,
                    "step": "accept_order",
                    "reason": "auto",
                })
        else:
            timeline.append({
                "stage": "seller_confirmation",
                "ok": True,
                "scene_id": resolved_scene,
                "step": "accept_order",
                "reason": "already_confirmed_or_auto",
            })

    # Ensure agents exist for contract/settlement IDs
    await ensure_agent_for_identity(db, buyer_identity_id, role="buyer")
    await ensure_agent_for_identity(db, seller_id, role="seller", name=recommended.get("name"))
    # Stamp discovery capabilities onto seller agent for future searches
    seller_row = await db.get(AgentModel, seller_id)
    if seller_row is not None:
        caps = list(seller_row.capabilities or [])
        for c in query.capabilities:
            if c not in caps:
                caps.append(c)
        seller_row.capabilities = caps
        if recommended.get("endpoint") and not seller_row.endpoint_url:
            seller_row.endpoint_url = recommended["endpoint"]

    await _ensure_capacity(db, buyer_identity_id, pay_amount, auto_fund=auto_fund_capacity)
    timeline.append({"stage": "capacity", "ok": True, "amount": pay_amount})

    negotiation: dict[str, Any]
    endpoint = (recommended.get("endpoint") or "").strip()
    if negotiate_a2a and endpoint:
        negotiation = await _negotiate_a2a(
            endpoint=endpoint,
            skill=skill,
            params={"requirement": requirement_text},
            buyer_id=buyer_identity_id,
            amount=pay_amount,
        )
        timeline.append({
            "stage": "negotiate",
            "ok": bool(negotiation.get("ok")),
            "mode": negotiation.get("mode"),
            "a2a_task_id": negotiation.get("task_id"),
            "detail": negotiation.get("error") or negotiation.get("create"),
        })
    else:
        negotiation = {
            "ok": True,
            "mode": "inline_synthetic",
            "task_id": f"inline-{uuid.uuid4().hex[:12]}",
            "skill": skill,
        }
        timeline.append({"stage": "negotiate", "ok": True, "mode": "inline_synthetic"})

    task_id = str(uuid.uuid4())
    deadline = datetime.utcnow() + timedelta(days=7)
    title = requirement_text.split("\n")[0][:120]
    progress_spec = {
        "source": "intent_fulfillment",
        "discovery_skills": query.skills,
        "scene_id": resolved_scene,
        "a2a_negotiation": {
            "mode": negotiation.get("mode"),
            "task_id": negotiation.get("task_id"),
            "ok": negotiation.get("ok"),
        },
        "important_fields": {
            "capture_id": (fields_lock or {}).get("capture_id"),
            "fields_hash": (fields_lock or {}).get("protocol_fields_hash")
            or (fields_lock or {}).get("fields_hash"),
            "status": (fields_lock or {}).get("status"),
            "required": must_if,
        },
    }
    contract = TaskContract(
        task_id=task_id,
        client_agent_id=buyer_identity_id,
        title=title,
        description=requirement_text[:8000],
        expected_output_schema={"type": "object", "properties": {"deliverable_hash": {"type": "string"}}},
        expected_step_count=2,
        escrow_amount=pay_amount,
        currency="USD",
        deadline_at=deadline,
    )
    contract.contract_hash = sha256_of(contract.model_dump(exclude={"contract_hash"}))
    db.add(
        TaskContractModel(
            task_id=contract.task_id,
            client_agent_id=contract.client_agent_id,
            worker_agent_id=seller_id,
            title=contract.title,
            description=contract.description,
            expected_output_schema=contract.expected_output_schema,
            expected_step_count=contract.expected_step_count,
            escrow_amount=contract.escrow_amount,
            currency=contract.currency,
            deadline_at=contract.deadline_at,
            contract_hash=contract.contract_hash,
        )
    )
    await db.flush()
    timeline.append({"stage": "contract", "ok": True, "task_id": task_id})

    req_hash = hashlib.sha256(requirement_text.encode("utf-8")).hexdigest()
    voucher = VoucherModel(
        voucher_id=str(uuid.uuid4()),
        buyer_identity_id=buyer_identity_id,
        seller_identity_id=seller_id,
        amount=pay_amount,
        currency="USDC",
        bill_credit_amount=pay_amount,
        task_type=query.task_type,
        task_description_hash=req_hash,
        progress_rule_hash=sha256_of(progress_spec),
        evidence_requirement_hash=sha256_of({"task_id": task_id}),
        expiry_time=datetime.utcnow() + timedelta(days=7),
        nonce=secrets.token_hex(16),
        buyer_signature=buyer_signature,
        status=VoucherStatus.CREATED.value,
        task_id=task_id,
        payment_mode="intent",
        progress_rule_spec=progress_spec,
    )
    db.add(voucher)
    await db.flush()
    await record_voucher_event(
        db,
        voucher_id=voucher.voucher_id,
        event_type="voucher.created",
        actor_identity_id=buyer_identity_id,
        target_identity_id=seller_id,
        payload={"task_id": task_id, "source": "intent_fulfillment"},
    )
    timeline.append({"stage": "voucher_created", "ok": True, "voucher_id": voucher.voucher_id})

    await accept_voucher_row(db, voucher, seller_identity_id=seller_id, actor=ORCH_ACTOR)
    timeline.append({"stage": "voucher_accepted", "ok": True, "voucher_id": voucher.voucher_id})

    store = PostgresSettlementStore(db)
    state = SettlementState(
        task_id=task_id,
        escrow_amount=pay_amount,
        currency="USD",
        client_agent_id=buyer_identity_id,
        status=TaskStatus.DRAFT,
        settlement_mode=settings.settlement_mode,
        voucher_id=voucher.voucher_id,
        progress_rule_spec=progress_spec,
    )
    await store.save(state)
    state = await store.get(task_id)
    assert state

    await assert_lock_does_not_close_payment_cycle(
        db, task_id=task_id, buyer_id=buyer_identity_id, worker_id=seller_id
    )
    if canonical_task_status(state.status) == TaskStatus.DRAFT:
        state = await apply_settlement_transition(
            db=db, store=store, state=state, target_status=TaskStatus.PENDING,
            reason="intent fulfillment: pending", route_path=ORCH_ROUTE, actor_id=ORCH_ACTOR,
        )
    state.worker_agent_id = seller_id
    state = await apply_settlement_transition(
        db=db, store=store, state=state, target_status=TaskStatus.ACCEPTED,
        reason="intent fulfillment: worker locked", route_path=ORCH_ROUTE, actor_id=ORCH_ACTOR,
    )
    state = await apply_settlement_transition(
        db=db, store=store, state=state, target_status=TaskStatus.IN_PROGRESS,
        reason="intent fulfillment: execution started", route_path=ORCH_ROUTE, actor_id=ORCH_ACTOR,
    )
    timeline.append({"stage": "settlement_in_progress", "ok": True, "task_id": task_id})

    final_status = "in_progress"
    receipt_id = None
    if auto_complete:
        state = await apply_settlement_transition(
            db=db, store=store, state=state, target_status=TaskStatus.DELIVERED,
            reason="intent fulfillment: auto delivery", route_path=ORCH_ROUTE, actor_id=ORCH_ACTOR,
        )
        timeline.append({"stage": "delivered", "ok": True})

        now = datetime.utcnow()
        receipt = ExecutionReceipt(
            task_id=task_id,
            agent_id=seller_id,
            step_index=1,
            tool_name=f"a2a.{skill}",
            input_hash=_hash_hex(requirement_text),
            output_hash=_hash_hex({"ok": True, "task_id": task_id}),
            started_at=now,
            ended_at=now + timedelta(milliseconds=50),
            duration_ms=50,
            status=ToolStatus.SUCCESS,
        )
        receipt.signature = signing_service.sign_receipt(receipt)
        from db.stores.receipt_store import PostgresReceiptStore

        await PostgresReceiptStore(db).save(receipt)
        receipt_id = receipt.receipt_id
        timeline.append({"stage": "evidence_receipt", "ok": True, "receipt_id": receipt_id})

        await ensure_success_execution_receipt_before_seller_payout(
            db, task_id, settled_amount=float(pay_amount)
        )
        state.released_amount = round(pay_amount, 2)
        state.refunded_amount = 0.0
        state.arbitration_notes = "intent fulfillment auto-complete — buyer accept"
        state.released_at = datetime.utcnow()
        state = await apply_settlement_transition(
            db=db, store=store, state=state, target_status=TaskStatus.SETTLED,
            reason="intent fulfillment: settled", route_path=ORCH_ROUTE, actor_id=ORCH_ACTOR,
        )
        await apply_capacity_resolution(
            db=db,
            buyer_identity_id=buyer_identity_id,
            escrow_amount=pay_amount,
            settled_amount=pay_amount,
            refunded_amount=0.0,
        )
        await mark_voucher_used_if_linked(db, task_id=task_id)
        await record_worker_settlement_outcome(
            db,
            worker_agent_id=seller_id,
            success=True,
            volume=pay_amount,
        )
        timeline.append({"stage": "settled", "ok": True, "reputation_updated": True})
        final_status = "settled"

    return {
        "status": final_status,
        "flow": "intent → discover → owner confirm → IF lock → negotiate → voucher → evidence → settle",
        "scene_id": resolved_scene,
        "intent": query.to_dict(),
        "discovery": {
            "recommended": recommended,
            "candidates": ranked,
        },
        "negotiation": negotiation,
        "buyer_identity_id": buyer_identity_id,
        "seller_identity_id": seller_id,
        "task_id": task_id,
        "voucher_id": voucher.voucher_id,
        "receipt_id": receipt_id,
        "amount": pay_amount,
        "confirmation_session_id": confirmation_session_id,
        "important_fields_capture_id": (fields_lock or {}).get("capture_id"),
        "important_fields_hash": (fields_lock or {}).get("protocol_fields_hash")
        or (fields_lock or {}).get("fields_hash"),
        "timeline": timeline,
        "next_steps": (
            []
            if auto_complete
            else [
                "seller_submits_delivery",
                "POST /v1/settlement/{task_id}/submit",
                "POST /v1/receipts (SUCCESS)",
                "POST /v1/settlement/{task_id}/buyer-accept",
            ]
        ),
    }
