"""P6 Accept & Fulfillment — seller accept TTL, non-confirm ledger, post-confirm liability.

Security / reality model
------------------------
1. Seller accept_order sessions use scene-tuned TTL; expiry → intent cancel + event.
2. Timeout / reject increments non_confirm_count (persisted); thresholds raise
   verification_tier and bond_multiplier.
3. Slight reputation delta on each non-confirm (not a hard ban).
4. After seller confirms (or policy-auto accept), breach liability is armed —
   compensation bps × amount × bond_multiplier.
5. Elevated sellers may be forced to OWNER_CONFIRM even on POLICY_AUTO scenes.
"""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.human_confirmation_policy import (
    ConfirmationPolicyError,
    get_confirmation_session,
    list_pending_seller_accept_sessions,
    mark_session_expired_cancelled,
)

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "accept-fulfillment.v1.json"
)
_STORE_PATH = (
    Path(__file__).resolve().parents[1] / ".karma_data" / "seller_accept_ledger.json"
)

_LOCK = threading.Lock()
_LEDGER: dict[str, Any] = {"sellers": {}, "events": []}
_LOADED = False

_TIER_RANK = {"normal": 3, "elevated": 2, "strict": 1, "restricted": 0}


class AcceptFulfillmentError(ValueError):
    pass


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def load_accept_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"accept-fulfillment catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "karma-accept-fulfillment-v1":
        raise AcceptFulfillmentError("unsupported accept-fulfillment schema_version")
    return data


def list_accept_scenes() -> list[dict[str, Any]]:
    cat = load_accept_catalog()
    out = []
    for sid, body in (cat.get("scenes") or {}).items():
        out.append(
            {
                "scene_id": sid,
                "group": body.get("group"),
                "seller_accept_ttl_seconds": scene_accept_ttl_seconds(sid),
                "on_timeout": scene_policy(sid).get("on_timeout"),
                "high_risk": bool(body.get("high_risk")),
                "reality_note_zh": body.get("reality_note_zh"),
            }
        )
    return out


def scene_policy(scene_id: str) -> dict[str, Any]:
    cat = load_accept_catalog()
    defaults = deepcopy(cat.get("global_defaults") or {})
    scene = deepcopy((cat.get("scenes") or {}).get(scene_id) or {})
    if scene_id not in (cat.get("scenes") or {}):
        # Unknown scene → defaults only (still enforceable)
        scene = {"scene_id": scene_id, "unknown_scene": True}
    merged = {**defaults, **scene}
    # Nested merge for post_confirm_breach
    base_breach = deepcopy(defaults.get("post_confirm_breach") or {})
    scene_breach = deepcopy(scene.get("post_confirm_breach") or {})
    merged["post_confirm_breach"] = {**base_breach, **scene_breach}
    merged["non_confirm_thresholds"] = list(
        scene.get("non_confirm_thresholds") or defaults.get("non_confirm_thresholds") or []
    )
    merged["scene_id"] = scene_id
    return merged


def scene_accept_ttl_seconds(scene_id: str, *, seller_id: str | None = None) -> int:
    pol = scene_policy(scene_id)
    ttl = int(pol.get("seller_accept_ttl_seconds") or 1800)
    if seller_id:
        profile = seller_risk_profile(seller_id, scene_id=scene_id)
        scale = float(profile.get("ttl_scale") or 1.0)
        ttl = max(60, int(ttl * scale))
    return ttl


def _ensure_loaded() -> None:
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
                    _LEDGER["sellers"] = dict(raw.get("sellers") or {})
                    _LEDGER["events"] = list(raw.get("events") or [])
            except Exception:  # noqa: BLE001
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(_LEDGER, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def reset_accept_ledger() -> None:
    global _LOADED
    with _LOCK:
        _LEDGER["sellers"] = {}
        _LEDGER["events"] = []
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def _seller_entry(seller_id: str) -> dict[str, Any]:
    _ensure_loaded()
    sid = (seller_id or "").strip()
    if not sid:
        raise AcceptFulfillmentError("seller_id required")
    with _LOCK:
        entry = _LEDGER["sellers"].get(sid)
        if not entry:
            entry = {
                "seller_id": sid,
                "non_confirm_count": 0,
                "timeout_count": 0,
                "reject_count": 0,
                "confirm_count": 0,
                "reputation_delta_total": 0.0,
                "last_event_at": None,
                "by_scene": {},
            }
            _LEDGER["sellers"][sid] = entry
        return entry


def _threshold_for_count(count: int, scene_id: str) -> dict[str, Any]:
    pol = scene_policy(scene_id)
    thresholds = sorted(
        pol.get("non_confirm_thresholds") or [],
        key=lambda t: int(t.get("count") or 0),
    )
    active: dict[str, Any] = {
        "verification_tier": "normal",
        "bond_multiplier": 1.0,
        "force_owner_confirm": bool(pol.get("force_owner_confirm")),
        "ttl_scale": 1.0,
        "discovery_demote": False,
        "threshold_count": 0,
    }
    for t in thresholds:
        if count >= int(t.get("count") or 0):
            active = {
                "verification_tier": t.get("verification_tier") or "elevated",
                "bond_multiplier": float(t.get("bond_multiplier") or 1.0),
                "force_owner_confirm": bool(
                    t.get("force_owner_confirm") or pol.get("force_owner_confirm")
                ),
                "ttl_scale": float(t.get("ttl_scale") or 1.0),
                "discovery_demote": bool(t.get("discovery_demote")),
                "threshold_count": int(t.get("count") or 0),
                "note_zh": t.get("note_zh"),
            }
    # High-risk scenes always force owner confirm
    if pol.get("high_risk") or pol.get("force_owner_confirm"):
        active["force_owner_confirm"] = True
    return active


def seller_risk_profile(seller_id: str, *, scene_id: str = "api_tool_call") -> dict[str, Any]:
    entry = _seller_entry(seller_id)
    count = int(entry.get("non_confirm_count") or 0)
    thr = _threshold_for_count(count, scene_id)
    tier = thr["verification_tier"]
    return {
        "seller_id": seller_id,
        "scene_id": scene_id,
        "non_confirm_count": count,
        "timeout_count": int(entry.get("timeout_count") or 0),
        "reject_count": int(entry.get("reject_count") or 0),
        "confirm_count": int(entry.get("confirm_count") or 0),
        "verification_tier": tier,
        "verification_tier_rank": _TIER_RANK.get(str(tier), 3),
        "bond_multiplier": float(thr.get("bond_multiplier") or 1.0),
        "force_owner_confirm": bool(thr.get("force_owner_confirm")),
        "ttl_scale": float(thr.get("ttl_scale") or 1.0),
        "discovery_demote": bool(thr.get("discovery_demote")),
        "reputation_delta_total": float(entry.get("reputation_delta_total") or 0.0),
        "threshold": thr,
        "last_event_at": entry.get("last_event_at"),
    }


def seller_requires_forced_confirm(seller_id: str, scene_id: str) -> bool:
    return bool(seller_risk_profile(seller_id, scene_id=scene_id).get("force_owner_confirm"))


def record_seller_non_confirm(
    *,
    seller_id: str,
    scene_id: str,
    interaction_ref: str | None,
    reason: str,
    session_id: str | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Record timeout/reject. Idempotent per session_id+reason."""
    if reason not in {"timeout", "reject"}:
        raise AcceptFulfillmentError("reason must be timeout|reject")
    pol = scene_policy(scene_id)
    max_hit = float(pol.get("max_reputation_hit_per_event") or 5.0)
    if reason == "timeout":
        delta = float(pol.get("reputation_delta_on_timeout") or -2.0)
    else:
        delta = float(pol.get("reputation_delta_on_reject") or -3.0)
    delta = max(-max_hit, min(0.0, delta))

    _ensure_loaded()
    idempotent_event: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    with _LOCK:
        if session_id:
            for ev in _LEDGER["events"]:
                if (
                    ev.get("session_id") == session_id
                    and ev.get("reason") == reason
                    and ev.get("outcome") == "non_confirm"
                ):
                    idempotent_event = dict(ev)
                    break
        if idempotent_event is None:
            entry = _LEDGER["sellers"].get(seller_id) or {
                "seller_id": seller_id,
                "non_confirm_count": 0,
                "timeout_count": 0,
                "reject_count": 0,
                "confirm_count": 0,
                "reputation_delta_total": 0.0,
                "last_event_at": None,
                "by_scene": {},
            }
            entry["non_confirm_count"] = int(entry.get("non_confirm_count") or 0) + 1
            if reason == "timeout":
                entry["timeout_count"] = int(entry.get("timeout_count") or 0) + 1
            else:
                entry["reject_count"] = int(entry.get("reject_count") or 0) + 1
            entry["reputation_delta_total"] = float(entry.get("reputation_delta_total") or 0.0) + delta
            entry["last_event_at"] = _utcnow_iso()
            by_scene = dict(entry.get("by_scene") or {})
            sc = dict(
                by_scene.get(scene_id)
                or {"non_confirm_count": 0, "timeout_count": 0, "reject_count": 0}
            )
            sc["non_confirm_count"] = int(sc.get("non_confirm_count") or 0) + 1
            sc[f"{reason}_count"] = int(sc.get(f"{reason}_count") or 0) + 1
            by_scene[scene_id] = sc
            entry["by_scene"] = by_scene
            _LEDGER["sellers"][seller_id] = entry

            event = {
                "event_id": f"sae_{len(_LEDGER['events']) + 1:06d}",
                "outcome": "non_confirm",
                "reason": reason,
                "seller_id": seller_id,
                "scene_id": scene_id,
                "interaction_ref": interaction_ref,
                "session_id": session_id,
                "amount": amount,
                "reputation_delta": delta,
                "created_at": _utcnow_iso(),
                "non_confirm_count_after": entry["non_confirm_count"],
            }
            _LEDGER["events"].append(event)
            if len(_LEDGER["events"]) > 5000:
                _LEDGER["events"] = _LEDGER["events"][-4000:]
            _persist_unlocked()

    profile = seller_risk_profile(seller_id, scene_id=scene_id)
    if idempotent_event is not None:
        return {
            "idempotent": True,
            "event": idempotent_event,
            "profile": profile,
            "reputation_delta": float(idempotent_event.get("reputation_delta") or delta),
        }
    return {
        "idempotent": False,
        "event": event,
        "profile": profile,
        "reputation_delta": delta,
    }


def record_seller_confirm(
    *,
    seller_id: str,
    scene_id: str,
    interaction_ref: str | None,
    session_id: str | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Record successful accept; arms liability separately via arm_post_confirm_liability."""
    _ensure_loaded()
    idempotent_event: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    with _LOCK:
        if session_id:
            for ev in _LEDGER["events"]:
                if ev.get("session_id") == session_id and ev.get("outcome") == "confirmed":
                    idempotent_event = dict(ev)
                    break
        if idempotent_event is None:
            entry = _LEDGER["sellers"].get(seller_id) or {
                "seller_id": seller_id,
                "non_confirm_count": 0,
                "timeout_count": 0,
                "reject_count": 0,
                "confirm_count": 0,
                "reputation_delta_total": 0.0,
                "last_event_at": None,
                "by_scene": {},
            }
            entry["confirm_count"] = int(entry.get("confirm_count") or 0) + 1
            entry["last_event_at"] = _utcnow_iso()
            _LEDGER["sellers"][seller_id] = entry
            event = {
                "event_id": f"sae_{len(_LEDGER['events']) + 1:06d}",
                "outcome": "confirmed",
                "reason": "accept",
                "seller_id": seller_id,
                "scene_id": scene_id,
                "interaction_ref": interaction_ref,
                "session_id": session_id,
                "amount": amount,
                "created_at": _utcnow_iso(),
            }
            _LEDGER["events"].append(event)
            _persist_unlocked()

    liability = arm_post_confirm_liability(
        seller_id=seller_id,
        scene_id=scene_id,
        amount=float(amount or 0),
        interaction_ref=interaction_ref,
        session_id=session_id,
    )
    profile = seller_risk_profile(seller_id, scene_id=scene_id)
    if idempotent_event is not None:
        return {
            "idempotent": True,
            "event": idempotent_event,
            "profile": profile,
            "breach_liability": liability,
        }
    return {
        "idempotent": False,
        "event": event,
        "profile": profile,
        "breach_liability": liability,
    }


def arm_post_confirm_liability(
    *,
    seller_id: str,
    scene_id: str,
    amount: float,
    interaction_ref: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """After seller confirms, breach compensation rules become active."""
    pol = scene_policy(scene_id)
    breach = dict(pol.get("post_confirm_breach") or {})
    profile = seller_risk_profile(seller_id, scene_id=scene_id)
    mult = float(profile.get("bond_multiplier") or 1.0)
    base_bps = int(breach.get("base_bond_bps") or 500)
    comp_bps = int(breach.get("compensation_bps_of_amount") or 1000)
    effective_bond_bps = int(round(base_bps * mult))
    effective_comp_bps = int(round(comp_bps * mult))
    amt = max(0.0, float(amount or 0))
    bond_amount = round(amt * effective_bond_bps / 10_000.0, 6)
    compensation_amount = round(amt * effective_comp_bps / 10_000.0, 6)
    return {
        "liability_armed": bool(breach.get("liability_armed", True)),
        "seller_id": seller_id,
        "scene_id": scene_id,
        "interaction_ref": interaction_ref,
        "session_id": session_id,
        "amount": amt,
        "verification_tier": profile.get("verification_tier"),
        "bond_multiplier": mult,
        "base_bond_bps": base_bps,
        "effective_bond_bps": effective_bond_bps,
        "bond_amount": bond_amount,
        "compensation_bps_of_amount": effective_comp_bps,
        "compensation_amount": compensation_amount,
        "cure_period_seconds": int(breach.get("cure_period_seconds") or 0),
        "armed_at": _utcnow_iso(),
        "note_zh": (
            "卖方确认接单后违约赔偿责任生效；"
            f"责任金 {effective_bond_bps} bps，补偿 {effective_comp_bps} bps"
            + (f"（未确认档位乘数 ×{mult}）" if mult > 1 else "")
        ),
    }


def compute_breach_compensation(
    *,
    seller_id: str,
    scene_id: str,
    amount: float,
    breach_fraction: float = 1.0,
) -> dict[str, Any]:
    """Compute payable compensation for a post-confirm breach (0..1 severity)."""
    liability = arm_post_confirm_liability(
        seller_id=seller_id, scene_id=scene_id, amount=amount
    )
    frac = max(0.0, min(1.0, float(breach_fraction)))
    due = round(float(liability["compensation_amount"]) * frac, 6)
    return {
        **liability,
        "breach_fraction": frac,
        "compensation_due": due,
    }


def process_expired_seller_session(
    session_id: str,
    *,
    apply_cancel: bool = True,
) -> dict[str, Any] | None:
    """If seller accept session is EXPIRED/CANCELLED-timeout, record (idempotent) and cancel."""
    try:
        pub = get_confirmation_session(session_id)
    except ConfirmationPolicyError:
        return None
    if pub.get("role") != "seller" or pub.get("step") != "accept_order":
        return None
    # First pass: EXPIRED. Idempotent re-entry after mark: CANCELLED + timeout reason.
    if pub.get("status") == "CANCELLED" and pub.get("cancel_reason") == "seller_accept_timeout":
        recorded = record_seller_non_confirm(
            seller_id=str(pub.get("owner_agent_id") or ""),
            scene_id=str(pub.get("scene_id") or "api_tool_call"),
            interaction_ref=pub.get("interaction_ref"),
            reason="timeout",
            session_id=session_id,
            amount=float(pub["max_amount"]) if pub.get("max_amount") is not None else None,
        )
        pol = scene_policy(str(pub.get("scene_id") or "api_tool_call"))
        return {
            "status": "cancelled_seller_timeout",
            "session_id": session_id,
            "seller_id": pub.get("owner_agent_id"),
            "scene_id": pub.get("scene_id"),
            "interaction_ref": pub.get("interaction_ref"),
            "on_timeout": pol.get("on_timeout") or "cancel_intent",
            "recorded": recorded,
            "cancel": pub,
            "profile": recorded.get("profile"),
            "idempotent": True,
            "next_steps_zh": (
                ["可重新发现匹配其他商家"]
                if pol.get("on_timeout") == "cancel_and_rediscover"
                else ["本次意向已取消；请重新发起"]
            ),
        }
    if pub.get("status") != "EXPIRED":
        return None
    seller_id = str(pub.get("owner_agent_id") or "")
    scene_id = str(pub.get("scene_id") or "api_tool_call")
    interaction_ref = pub.get("interaction_ref")
    amount = pub.get("max_amount")
    recorded = record_seller_non_confirm(
        seller_id=seller_id,
        scene_id=scene_id,
        interaction_ref=interaction_ref,
        reason="timeout",
        session_id=session_id,
        amount=float(amount) if amount is not None else None,
    )
    cancel_meta = None
    if apply_cancel:
        cancel_meta = mark_session_expired_cancelled(
            session_id,
            reason="seller_accept_timeout",
        )
    pol = scene_policy(scene_id)
    return {
        "status": "cancelled_seller_timeout",
        "session_id": session_id,
        "seller_id": seller_id,
        "scene_id": scene_id,
        "interaction_ref": interaction_ref,
        "on_timeout": pol.get("on_timeout") or "cancel_intent",
        "recorded": recorded,
        "cancel": cancel_meta,
        "profile": recorded.get("profile"),
        "next_steps_zh": (
            ["可重新发现匹配其他商家"]
            if pol.get("on_timeout") == "cancel_and_rediscover"
            else ["本次意向已取消；请重新发起"]
        ),
    }


def expire_pending_seller_accepts(*, limit: int = 100) -> dict[str, Any]:
    """Sweep PENDING seller accept sessions past TTL → EXPIRED → cancel+record."""
    pending = list_pending_seller_accept_sessions(limit=limit)
    results = []
    for sess in pending:
        sid = sess.get("session_id")
        if not sid:
            continue
        # Force expire check via get
        try:
            pub = get_confirmation_session(sid)
        except ConfirmationPolicyError:
            continue
        if pub.get("status") == "EXPIRED":
            out = process_expired_seller_session(sid)
            if out:
                results.append(out)
    return {
        "swept": len(results),
        "cancelled": results,
    }


def check_interaction_seller_timeout(
    *,
    seller_id: str,
    interaction_ref: str | None,
    scene_id: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Called from fulfill: if the seller accept for this deal timed out, return cancel payload."""
    if session_id:
        out = process_expired_seller_session(session_id)
        if out:
            return out
    if not interaction_ref:
        return None
    # Scan recent events for this interaction already cancelled
    _ensure_loaded()
    prior_event: dict[str, Any] | None = None
    with _LOCK:
        for ev in reversed(_LEDGER["events"]):
            if (
                ev.get("seller_id") == seller_id
                and ev.get("interaction_ref") == interaction_ref
                and ev.get("reason") == "timeout"
                and ev.get("outcome") == "non_confirm"
            ):
                prior_event = dict(ev)
                break
    if prior_event is not None:
        return {
            "status": "cancelled_seller_timeout",
            "seller_id": seller_id,
            "scene_id": scene_id,
            "interaction_ref": interaction_ref,
            "already_recorded": True,
            "event": prior_event,
            "profile": seller_risk_profile(seller_id, scene_id=scene_id),
            "next_steps_zh": ["本次意向已因卖方超时取消；请重新发现匹配"],
        }
    # Also expire any pending sessions matching interaction
    for sess in list_pending_seller_accept_sessions(limit=200):
        if sess.get("owner_agent_id") != seller_id:
            continue
        if sess.get("interaction_ref") != interaction_ref:
            continue
        sid = sess.get("session_id")
        if not sid:
            continue
        try:
            pub = get_confirmation_session(sid)
        except ConfirmationPolicyError:
            continue
        if pub.get("status") == "EXPIRED":
            return process_expired_seller_session(sid)
    return None


def accept_enrichment_for_discovery(seller_id: str, scene_id: str) -> dict[str, Any]:
    """Compact risk fields for P3 sort demotion."""
    p = seller_risk_profile(seller_id, scene_id=scene_id)
    return {
        "non_confirm_count": p["non_confirm_count"],
        "verification_tier": p["verification_tier"],
        "verification_tier_rank": p["verification_tier_rank"],
        "bond_multiplier": p["bond_multiplier"],
        "discovery_demote": p["discovery_demote"],
    }
