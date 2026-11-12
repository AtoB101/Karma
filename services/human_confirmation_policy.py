"""Human vs auto confirmation policy — real-world scene gates.

Agents should only bother the owner at OWNER_CONFIRM (or POLICY_AUTO when
policy is missing). After owner says yes, accept/execute may proceed.

Sessions persist to ``.karma_data/confirmation_sessions.json`` for single-node
scenario runs (multi-instance still needs Redis/DB).
"""
from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "human-confirmation-policy.v1.json"
)
_STORE_PATH = (
    Path(__file__).resolve().parents[1] / ".karma_data" / "confirmation_sessions.json"
)

_LOCK = threading.Lock()
_SESSIONS: dict[str, "ConfirmationSession"] = {}
_LOADED = False

# Session lifetime — PENDING/CONFIRMED expire; USED stays for audit of prior steps
SESSION_TTL_SECONDS = 30 * 60

# Reality: daily commerce folds select_offer into one checkout Yes/No.
# B2B / high-risk / lodging / tickets keep separate select → accept.
_MULTI_STEP_BUYER_SCENES = frozenset(
    {
        "b2b_procurement",
        "manufacturing",
        "financial_services",
        "healthcare_medical",
        "software_development",
        "design_creative",
        "consulting_advisory",
        "real_estate_services",
        "hotel_booking",
        "flight_booking",
    }
)


class ConfirmationPolicyError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_policy_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"confirmation policy missing: {CATALOG_PATH}")
    import json

    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-human-confirmation-v1":
        raise ConfirmationPolicyError("unsupported confirmation policy schema")
    return data


# Intent discovery task_type → confirmation scene_id
_TASK_TYPE_TO_SCENE: dict[str, str] = {
    "commerce.food": "food_delivery",
    "commerce.ride": "ride_hailing",
    "commerce.hotel": "hotel_booking",
    "commerce.flight": "flight_booking",
    "commerce.procurement": "b2b_procurement",
    "b2b.procurement": "b2b_procurement",
    "api.translate": "api_tool_call",
    "api.caption": "api_tool_call",
    "api.labeling": "api_tool_call",
    "api.generic": "api_tool_call",
    "api.data": "data_api_billing",
    "data.api": "data_api_billing",
    "logistics": "logistics_delivery",
    "software": "software_development",
    "design": "design_creative",
    "consulting": "consulting_advisory",
    "content": "content_creation",
    "manufacturing": "manufacturing",
    "real_estate": "real_estate_services",
    "finance": "financial_services",
    "financial": "financial_services",
    "marketing": "marketing_advertising",
    "education": "education_training",
    "healthcare": "healthcare_medical",
    "medical": "healthcare_medical",
}


def task_type_to_scene_id(task_type: str | None) -> str:
    """Map discovery task_type (e.g. commerce.food) to confirmation scene_id."""
    tt = (task_type or "").strip().lower()
    if not tt:
        return "api_tool_call"
    if tt in _TASK_TYPE_TO_SCENE:
        return _TASK_TYPE_TO_SCENE[tt]
    if tt.startswith("commerce.food") or "food" in tt:
        return "food_delivery"
    if tt.startswith("commerce.ride") or "ride" in tt:
        return "ride_hailing"
    if tt.startswith("commerce.hotel") or "hotel" in tt:
        return "hotel_booking"
    if tt.startswith("commerce.flight") or "flight" in tt:
        return "flight_booking"
    if "procure" in tt or "b2b" in tt:
        return "b2b_procurement"
    if "financ" in tt or "对账" in tt:
        return "financial_services"
    if "health" in tt or "medical" in tt or "陪诊" in tt:
        return "healthcare_medical"
    if "manufactur" in tt or "代工" in tt:
        return "manufacturing"
    if "real_estate" in tt or "房产" in tt:
        return "real_estate_services"
    if "consult" in tt:
        return "consulting_advisory"
    if "design" in tt or "创意" in tt:
        return "design_creative"
    if "market" in tt or "广告" in tt:
        return "marketing_advertising"
    if "educat" in tt or "培训" in tt:
        return "education_training"
    if "content" in tt or "内容" in tt:
        return "content_creation"
    if tt.startswith("api.") or "mcp" in tt or "tool" in tt:
        return "api_tool_call"
    if "data" in tt:
        return "data_api_billing"
    if "logistic" in tt or "delivery" in tt:
        return "logistics_delivery"
    if "software" in tt or "dev" in tt:
        return "software_development"
    # Known catalog scene id passthrough; unknown → api_tool_call (never invent high-risk)
    scenes = load_policy_catalog().get("scenes") or {}
    return tt if tt in scenes else "api_tool_call"


def is_high_risk_scene(scene_id: str | None) -> bool:
    if not scene_id:
        return False
    scene = (load_policy_catalog().get("scenes") or {}).get(scene_id) or {}
    return bool(scene.get("high_risk"))


def require_known_scene(scene_id: str) -> dict[str, Any]:
    """Return scene policy or raise — no silent global fallback for unknown ids."""
    cat = load_policy_catalog()
    scene = (cat.get("scenes") or {}).get(scene_id)
    if not scene:
        raise ConfirmationPolicyError(
            f"unknown confirmation scene_id '{scene_id}' — refuse silent global fallback"
        )
    return {"scene_id": scene_id, **scene, "fallback": False}


def buyer_fulfill_confirm_steps(scene_id: str) -> list[str]:
    """Buyer steps that fulfill must gate, in order (reality-tuned)."""
    if scene_id in _MULTI_STEP_BUYER_SCENES or is_high_risk_scene(scene_id):
        return ["select_offer", "accept_order"]
    return ["accept_order"]


def seller_must_confirm_accept(scene_id: str) -> bool:
    """True when seller accept_order is OWNER_CONFIRM (not POLICY_AUTO/AUTO)."""
    gate = resolve_gate(scene_id=scene_id, role="seller", step="accept_order")
    return gate.get("mode") == "OWNER_CONFIRM"


def list_policy_scenes() -> list[dict[str, Any]]:
    cat = load_policy_catalog()
    out = []
    for sid, body in (cat.get("scenes") or {}).items():
        out.append(
            {
                "scene_id": sid,
                "title_zh": body.get("title_zh"),
                "reality_note_zh": body.get("reality_note_zh"),
                "auto_ok_examples_zh": body.get("auto_ok_examples_zh") or [],
            }
        )
    return out


def get_scene_policy(scene_id: str, *, allow_fallback: bool = True) -> dict[str, Any]:
    cat = load_policy_catalog()
    scene = (cat.get("scenes") or {}).get(scene_id)
    if not scene:
        if not allow_fallback:
            raise ConfirmationPolicyError(
                f"unknown confirmation scene_id '{scene_id}' — refuse silent global fallback"
            )
        # Soft fallback only for planning/display of typos — fulfill uses require_known_scene
        return {
            "scene_id": scene_id,
            "title_zh": scene_id,
            "reality_note_zh": "使用全局默认确认策略（未知 scene，勿用于高风险成交）",
            "buyer": (cat.get("global_defaults") or {}).get("buyer") or {},
            "seller": (cat.get("global_defaults") or {}).get("seller") or {},
            "owner_prompt_templates_zh": {},
            "auto_ok_examples_zh": [],
            "fallback": True,
        }
    return {"scene_id": scene_id, **scene, "fallback": False}


def resolve_gate(
    *,
    scene_id: str,
    role: str,
    step: str,
    policy_auto_allowed: bool = False,
) -> dict[str, Any]:
    """Resolve gate mode for one step. role: buyer|seller."""
    role = role.lower().strip()
    if role not in {"buyer", "seller"}:
        raise ConfirmationPolicyError("role must be buyer or seller")
    cat = load_policy_catalog()
    scene = get_scene_policy(scene_id)
    role_map = dict(scene.get(role) or {})
    defaults = ((cat.get("global_defaults") or {}).get(role)) or {}
    mode = role_map.get(step) or defaults.get(step) or "OWNER_CONFIRM"

    effective = mode
    needs_owner = False
    if mode == "AUTO":
        needs_owner = False
    elif mode == "OWNER_CONFIRM":
        needs_owner = True
    elif mode == "POLICY_AUTO":
        if policy_auto_allowed:
            effective = "AUTO"
            needs_owner = False
        else:
            effective = "OWNER_CONFIRM"
            needs_owner = True
    elif mode == "COUNTERPARTY_OR_OWNER":
        needs_owner = True
        effective = "OWNER_CONFIRM"
    else:
        needs_owner = True
        effective = "OWNER_CONFIRM"

    templates = scene.get("owner_prompt_templates_zh") or {}
    return {
        "scene_id": scene_id,
        "role": role,
        "step": step,
        "mode": mode,
        "effective_mode": effective,
        "needs_owner_confirmation": needs_owner,
        "policy_auto_allowed": policy_auto_allowed,
        "owner_prompt_template_zh": templates.get(step),
        "reality_note_zh": scene.get("reality_note_zh"),
    }


def plan_confirmations(
    *,
    scene_id: str,
    role: str,
    steps: list[str] | None = None,
    policy_auto_allowed: bool = False,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cat = load_policy_catalog()
    lifecycle = list(cat.get("lifecycle_steps") or [])
    use_steps = list(steps) if steps else lifecycle
    ctx = context or {}
    must: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []
    for step in use_steps:
        gate = resolve_gate(
            scene_id=scene_id,
            role=role,
            step=step,
            policy_auto_allowed=policy_auto_allowed,
        )
        prompt = gate.get("owner_prompt_template_zh")
        if prompt and ctx:
            try:
                prompt = str(prompt).format(**ctx)
            except Exception:  # noqa: BLE001
                pass
        item = {**gate, "owner_prompt_zh": prompt}
        if gate["needs_owner_confirmation"]:
            must.append(item)
        else:
            auto.append(item)
    scene = get_scene_policy(scene_id)
    return {
        "schema_version": "karma-human-confirmation-v1",
        "scene_id": scene_id,
        "role": role,
        "title_zh": scene.get("title_zh"),
        "reality_note_zh": scene.get("reality_note_zh"),
        "must_confirm": must,
        "auto_ok": auto,
        "auto_ok_examples_zh": scene.get("auto_ok_examples_zh") or [],
        "agent_ux_zh": (cat.get("agent_ux_zh") or {}),
        "summary_zh": (
            f"需主人确认 {len(must)} 步；可自动 {len(auto)} 步。"
            "Agent 只需在必须确认点询问是否确认。"
        ),
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def allow_demo_confirmation_bypass() -> bool:
    """Demo-only flags (require_owner_confirmation=false) allowed in local/test envs."""
    try:
        from config.settings import settings

        return (settings.app_env or "").lower() in ("development", "dev", "local", "test")
    except Exception:  # noqa: BLE001
        return False


@dataclass
class ConfirmationSession:
    session_id: str
    scene_id: str
    role: str
    step: str
    owner_agent_id: str
    prompt_zh: str
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"  # PENDING | CONFIRMED | REJECTED | USED | EXPIRED
    created_at: str = ""
    expires_at: str | None = None
    decided_at: str | None = None
    decision_note: str | None = None
    interaction_ref: str | None = None
    max_amount: float | None = None
    cancel_reason: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "scene_id": self.scene_id,
            "role": self.role,
            "step": self.step,
            "owner_agent_id": self.owner_agent_id,
            "prompt_zh": self.prompt_zh,
            "context": self.context,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
            "decision_note": self.decision_note,
            "interaction_ref": self.interaction_ref,
            "max_amount": self.max_amount,
            "cancel_reason": self.cancel_reason,
            "can_proceed": self.status == "CONFIRMED",
        }


def _ensure_sessions_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for sid, body in raw.items():
                        if not isinstance(body, dict):
                            continue
                        _SESSIONS[str(sid)] = ConfirmationSession(
                            session_id=str(body.get("session_id") or sid),
                            scene_id=str(body.get("scene_id") or ""),
                            role=str(body.get("role") or "buyer"),
                            step=str(body.get("step") or ""),
                            owner_agent_id=str(body.get("owner_agent_id") or ""),
                            prompt_zh=str(body.get("prompt_zh") or ""),
                            context=dict(body.get("context") or {}),
                            status=str(body.get("status") or "PENDING"),
                            created_at=str(body.get("created_at") or ""),
                            expires_at=body.get("expires_at"),
                            decided_at=body.get("decided_at"),
                            decision_note=body.get("decision_note"),
                            interaction_ref=body.get("interaction_ref"),
                            max_amount=(
                                float(body["max_amount"])
                                if body.get("max_amount") is not None
                                else None
                            ),
                            cancel_reason=body.get("cancel_reason"),
                        )
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_sessions_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {sid: asdict(sess) for sid, sess in _SESSIONS.items()}
    _STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reset_confirmation_sessions() -> None:
    global _LOADED
    with _LOCK:
        _SESSIONS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _expire_if_needed_unlocked(sess: ConfirmationSession) -> bool:
    """Mark PENDING/CONFIRMED expired when past TTL. Returns True if now EXPIRED."""
    if sess.status not in {"PENDING", "CONFIRMED"}:
        return sess.status == "EXPIRED"
    exp = _parse_iso(sess.expires_at)
    if exp is None and sess.created_at:
        created = _parse_iso(sess.created_at)
        if created:
            exp = created + timedelta(seconds=SESSION_TTL_SECONDS)
    if exp is None:
        return False
    now = datetime.now(timezone.utc)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now > exp:
        sess.status = "EXPIRED"
        return True
    return False


def create_confirmation_session(
    *,
    scene_id: str,
    role: str,
    step: str,
    owner_agent_id: str,
    context: dict[str, Any] | None = None,
    interaction_ref: str | None = None,
    policy_auto_allowed: bool = False,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    # Refuse unknown scene ids — no silent global fallback (security)
    if scene_id not in (load_policy_catalog().get("scenes") or {}):
        raise ConfirmationPolicyError(
            f"unknown confirmation scene_id '{scene_id}' — refuse silent global fallback"
        )

    gate = resolve_gate(
        scene_id=scene_id,
        role=role,
        step=step,
        policy_auto_allowed=policy_auto_allowed,
    )
    if not gate["needs_owner_confirmation"]:
        return {
            "skipped": True,
            "reason": "step is AUTO under current policy",
            "gate": gate,
            "can_proceed": True,
            "status": "AUTO_APPROVED",
        }
    ctx = dict(context or {})
    prompt = gate.get("owner_prompt_template_zh") or f"是否确认执行 {step}？"
    try:
        prompt = str(prompt).format(**ctx)
    except Exception:  # noqa: BLE001
        pass
    max_amount = None
    if "amount" in ctx and ctx.get("amount") is not None:
        try:
            max_amount = float(ctx["amount"])
        except (TypeError, ValueError):
            max_amount = None
    sid = "cfm_" + secrets.token_hex(12)
    created = _iso_now()
    ttl = int(ttl_seconds) if ttl_seconds is not None else SESSION_TTL_SECONDS
    ttl = max(60, min(ttl, 7 * 24 * 3600))
    expires = (
        datetime.now(timezone.utc) + timedelta(seconds=ttl)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sess = ConfirmationSession(
        session_id=sid,
        scene_id=scene_id,
        role=role.lower(),
        step=step,
        owner_agent_id=owner_agent_id,
        prompt_zh=prompt,
        context=ctx,
        status="PENDING",
        created_at=created,
        expires_at=expires,
        interaction_ref=interaction_ref,
        max_amount=max_amount,
    )
    _ensure_sessions_loaded()
    with _LOCK:
        _SESSIONS[sid] = sess
        _persist_sessions_unlocked()
    return {
        "skipped": False,
        **sess.public(),
        "gate": gate,
        "ttl_seconds": ttl,
    }


def get_confirmation_session(session_id: str) -> dict[str, Any]:
    _ensure_sessions_loaded()
    with _LOCK:
        sess = _SESSIONS.get(session_id)
        if not sess:
            raise ConfirmationPolicyError(f"unknown confirmation session: {session_id}")
        if _expire_if_needed_unlocked(sess):
            _persist_sessions_unlocked()
        return sess.public()


def list_pending_seller_accept_sessions(*, limit: int = 100) -> list[dict[str, Any]]:
    """PENDING (or just-expired) seller accept_order sessions for P6 sweep."""
    _ensure_sessions_loaded()
    out: list[dict[str, Any]] = []
    with _LOCK:
        for sess in _SESSIONS.values():
            if sess.role != "seller" or sess.step != "accept_order":
                continue
            if sess.status not in {"PENDING", "EXPIRED"}:
                continue
            _expire_if_needed_unlocked(sess)
            if sess.status in {"PENDING", "EXPIRED"}:
                out.append(sess.public())
            if len(out) >= limit:
                break
        _persist_sessions_unlocked()
    return out


def mark_session_expired_cancelled(
    session_id: str,
    *,
    reason: str = "seller_accept_timeout",
) -> dict[str, Any]:
    """Annotate an EXPIRED seller accept session as cancelled (P6 timeout path)."""
    _ensure_sessions_loaded()
    with _LOCK:
        sess = _SESSIONS.get(session_id)
        if not sess:
            raise ConfirmationPolicyError(f"unknown confirmation session: {session_id}")
        _expire_if_needed_unlocked(sess)
        if sess.status not in {"EXPIRED", "CANCELLED"}:
            # Force-expire if still pending past deadline
            if sess.status == "PENDING":
                sess.status = "EXPIRED"
            else:
                raise ConfirmationPolicyError(
                    f"session status {sess.status} cannot mark timeout cancel"
                )
        sess.status = "CANCELLED"
        sess.cancel_reason = reason
        sess.decision_note = sess.decision_note or reason
        sess.decided_at = sess.decided_at or _iso_now()
        _persist_sessions_unlocked()
        return sess.public()


def decide_confirmation_session(
    session_id: str,
    *,
    confirm: bool,
    note: str | None = None,
    actor_agent_id: str | None = None,
) -> dict[str, Any]:
    if not actor_agent_id or not str(actor_agent_id).strip():
        raise ConfirmationPolicyError("actor_agent_id is required to decide a confirmation session")
    _ensure_sessions_loaded()
    with _LOCK:
        sess = _SESSIONS.get(session_id)
        if not sess:
            raise ConfirmationPolicyError(f"unknown confirmation session: {session_id}")
        if _expire_if_needed_unlocked(sess):
            _persist_sessions_unlocked()
            raise ConfirmationPolicyError("confirmation session EXPIRED")
        if sess.status != "PENDING":
            raise ConfirmationPolicyError(f"session already {sess.status}")
        if actor_agent_id != sess.owner_agent_id:
            raise ConfirmationPolicyError("only the owner_agent_id may decide this session")
        sess.status = "CONFIRMED" if confirm else "REJECTED"
        sess.decided_at = _iso_now()
        sess.decision_note = note
        _persist_sessions_unlocked()
        out = sess.public()
    out["next_zh"] = (
        "主人已确认，Agent 可继续接单/锁字段/执行/结算"
        if confirm
        else "主人已拒绝，停止该步，不接单、不锁款"
    )
    return out


def assert_step_allowed(
    *,
    scene_id: str,
    role: str,
    step: str,
    confirmation_session_id: str | None = None,
    policy_auto_allowed: bool = False,
    expected_owner_agent_id: str | None = None,
    amount: float | None = None,
    consume: bool = True,
    expected_interaction_ref: str | None = None,
) -> dict[str, Any]:
    """Gate helper for orchestration: AUTO ok; OWNER_CONFIRM requires CONFIRMED session.

    Binds owner + amount + optional interaction_ref; consumes session (USED) so it
    cannot be replayed. Expires PENDING/CONFIRMED past TTL.
    """
    _ensure_sessions_loaded()
    gate = resolve_gate(
        scene_id=scene_id,
        role=role,
        step=step,
        policy_auto_allowed=policy_auto_allowed,
    )
    if not gate["needs_owner_confirmation"]:
        return {"allowed": True, "gate": gate, "reason": "auto"}
    if not confirmation_session_id:
        raise ConfirmationPolicyError(
            f"step {step} requires owner confirmation session for scene {scene_id}"
        )
    with _LOCK:
        sess_obj = _SESSIONS.get(confirmation_session_id)
        if not sess_obj:
            raise ConfirmationPolicyError(f"unknown confirmation session: {confirmation_session_id}")
        if _expire_if_needed_unlocked(sess_obj):
            _persist_sessions_unlocked()
            raise ConfirmationPolicyError("confirmation session EXPIRED")
        if sess_obj.status != "CONFIRMED":
            raise ConfirmationPolicyError(
                f"confirmation session status is {sess_obj.status}, need CONFIRMED"
            )
        if (
            sess_obj.scene_id != scene_id
            or sess_obj.step != step
            or sess_obj.role != role.lower()
        ):
            raise ConfirmationPolicyError("confirmation session does not match scene/role/step")
        if expected_owner_agent_id and sess_obj.owner_agent_id != expected_owner_agent_id:
            raise ConfirmationPolicyError("confirmation session owner does not match buyer")
        if (
            expected_interaction_ref
            and sess_obj.interaction_ref
            and sess_obj.interaction_ref != expected_interaction_ref
        ):
            raise ConfirmationPolicyError("confirmation session interaction_ref mismatch")
        if amount is not None and sess_obj.max_amount is not None:
            if float(amount) > float(sess_obj.max_amount) + 1e-6:
                raise ConfirmationPolicyError(
                    f"amount {amount} exceeds confirmed max_amount {sess_obj.max_amount}"
                )
        if consume:
            sess_obj.status = "USED"
            sess_obj.decided_at = sess_obj.decided_at or _iso_now()
            _persist_sessions_unlocked()
        out_sess = sess_obj.public()
    return {
        "allowed": True,
        "gate": gate,
        "reason": "owner_confirmed",
        "session": out_sess,
        "consumed": bool(consume),
    }


def step_already_satisfied(
    *,
    scene_id: str,
    role: str,
    step: str,
    owner_agent_id: str,
    interaction_ref: str | None = None,
    policy_auto_allowed: bool = False,
) -> bool:
    """True if step is AUTO under policy or a USED session already covered it.

    CONFIRMED (not yet consumed) does **not** count — caller must assert/consume
    to prevent replay across fulfill resumes.
    """
    gate = resolve_gate(
        scene_id=scene_id,
        role=role,
        step=step,
        policy_auto_allowed=policy_auto_allowed,
    )
    if not gate["needs_owner_confirmation"]:
        return True
    _ensure_sessions_loaded()
    with _LOCK:
        for sess in _SESSIONS.values():
            if _expire_if_needed_unlocked(sess):
                continue
            if (
                sess.scene_id == scene_id
                and sess.role == role.lower()
                and sess.step == step
                and sess.owner_agent_id == owner_agent_id
                and sess.status == "USED"
            ):
                if interaction_ref and sess.interaction_ref and sess.interaction_ref != interaction_ref:
                    continue
                return True
    return False


def next_required_confirm_step(
    *,
    scene_id: str,
    role: str,
    steps: list[str],
    owner_agent_id: str,
    interaction_ref: str | None = None,
    policy_auto_allowed: bool = False,
) -> str | None:
    """First step in ``steps`` that still needs a fresh owner Yes."""
    for step in steps:
        if not step_already_satisfied(
            scene_id=scene_id,
            role=role,
            step=step,
            owner_agent_id=owner_agent_id,
            interaction_ref=interaction_ref,
            policy_auto_allowed=policy_auto_allowed,
        ):
            return step
    return None
