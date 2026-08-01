"""P3 discovery priority — scene-aware selection order on verifiable records.

Priority (high → low):
  eligible → p1_ready → boundary_complete → scene_covered → trust_tier → score

Different scenes apply different gates/weights so users find merchants who can
actually solve the job, and enterprises find reliable partners. System scores
and settlement history are the verifiable foundation for longevity/reputation.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from services.agent_boundary import seller_covers_scene, scene_in_do_not
from services.agent_trust import AgentTrustStats, compute_trust_bonus
from services.human_confirmation_policy import task_type_to_scene_id

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "evidence-schema"
    / "discovery-priority.v1.json"
)

PRIORITY_SCHEMA = "karma-discovery-priority-v1"


class DiscoveryPriorityError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_priority_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"discovery priority catalog missing: {CATALOG_PATH}")
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != PRIORITY_SCHEMA:
        raise DiscoveryPriorityError("unsupported discovery priority schema")
    return data


def list_priority_scenes() -> list[dict[str, Any]]:
    cat = load_priority_catalog()
    out = []
    for sid, body in (cat.get("scenes") or {}).items():
        out.append(
            {
                "scene_id": sid,
                "title_zh": body.get("title_zh"),
                "reality_note_zh": body.get("reality_note_zh"),
                "high_risk": bool(body.get("high_risk")),
                "require_p1_ready": bool(body.get("require_p1_ready")),
                "require_boundary_complete": bool(body.get("require_boundary_complete")),
                "require_scene_coverage": bool(body.get("require_scene_coverage")),
                "allow_cold_start": body.get("allow_cold_start"),
                "min_settled_count_for_proven": body.get("min_settled_count_for_proven"),
                "trust_weight": body.get("trust_weight"),
            }
        )
    return out


def get_scene_priority_policy(scene_id: str | None) -> dict[str, Any]:
    cat = load_priority_catalog()
    defaults = dict(cat.get("global_defaults") or {})
    sid = (scene_id or "").strip()
    scene = dict((cat.get("scenes") or {}).get(sid) or {})
    merged = {**defaults, **scene, "scene_id": sid or None}
    if not scene:
        merged["fallback"] = True
    else:
        merged["fallback"] = False
    return merged


def resolve_scene_id(*, scene_id: str | None = None, task_type: str | None = None) -> str:
    if scene_id and str(scene_id).strip():
        return str(scene_id).strip()
    return task_type_to_scene_id(task_type)


def _card_scene_ids(card: dict[str, Any]) -> list[str]:
    if card.get("scene_ids"):
        return [str(x) for x in card["scene_ids"]]
    boundary = card.get("boundary") or {}
    if boundary.get("scene_ids"):
        return [str(x) for x in boundary["scene_ids"]]
    return []


def candidate_covers_scene(card: dict[str, Any], scene_id: str) -> bool:
    """Prefer explicit scene_ids; fall back to seller_covers_scene on boundary digests."""
    if not scene_id:
        return False
    scenes = set(_card_scene_ids(card))
    if scene_id in scenes:
        return True
    # Full boundary card (if present) may include service_specs
    if card.get("capability_boundary") or card.get("scene_ids") is not None:
        return seller_covers_scene(card, scene_id)
    # Digest-only: reconstruct minimal boundary
    boundary = {
        "scene_ids": list(scenes),
        "capability_boundary": {
            "service_specs": {s: {} for s in scenes},
            "do_not": (card.get("boundary") or {}).get("do_not") or card.get("do_not") or "",
        },
    }
    return seller_covers_scene(boundary, scene_id)


def candidate_refuses_scene(card: dict[str, Any], scene_id: str) -> bool:
    do_not = (card.get("boundary") or {}).get("do_not") or card.get("do_not") or ""
    boundary = {
        "capability_boundary": {"do_not": do_not},
        "scene_ids": _card_scene_ids(card),
    }
    return scene_in_do_not(boundary, scene_id)


def classify_trust_tier(
    stats: AgentTrustStats,
    *,
    policy: dict[str, Any],
) -> str:
    """proven | emerging | cold — based on verifiable settlement/reputation records."""
    min_n = int(policy.get("min_settled_count_for_proven") or 3)
    min_sr = float(policy.get("min_success_rate_for_proven") or 0.8)
    max_dr = float(policy.get("max_dispute_rate") or 0.25)
    settled = int(stats.settled_count or 0)
    tasks = int(stats.total_tasks or 0)
    sr = float(stats.success_rate if (tasks or settled) else 0.0)
    dr = float(stats.dispute_rate or 0.0)
    has_record = settled > 0 or tasks > 0
    if (
        settled >= min_n
        and sr >= min_sr
        and dr <= max_dr
        and not stats.cold_start
    ):
        return "proven"
    if has_record and not stats.cold_start:
        return "emerging"
    return "cold"


_TRUST_TIER_RANK = {"proven": 3, "emerging": 2, "cold": 1}


def trust_evidence_digest(
    *,
    agent_id: str,
    stats: AgentTrustStats,
    card: dict[str, Any],
    trust_tier: str,
    scene_id: str | None,
) -> dict[str, Any]:
    """Compact verifiable pointers for assistants / counterparties."""
    return {
        "agent_id": agent_id,
        "scene_id": scene_id,
        "trust_tier": trust_tier,
        "p1_ready": card.get("p1_ready"),
        "boundary_complete": card.get("boundary_complete"),
        "boundary_hash": card.get("boundary_hash"),
        "identity_class": card.get("identity_class"),
        "reputation_score": round(float(stats.reputation_score or 0), 3),
        "settled_count": int(stats.settled_count or 0),
        "settled_volume": round(float(stats.settled_volume or 0), 4),
        "success_rate": round(float(stats.success_rate or 0), 4),
        "dispute_rate": round(float(stats.dispute_rate or 0), 4),
        "verify_urls": {
            "p1_status": f"/v1/agents/{agent_id}/p1-status",
            "trust": f"/v1/agents/{agent_id}/trust",
            "boundary_verify": (
                f"/v1/agents/{agent_id}/boundary/verify?scene_id={scene_id}"
                if scene_id
                else f"/v1/agents/{agent_id}/boundary/verify"
            ),
        },
        "note_zh": "评分与笔数来自平台声誉行与结算聚合；对端可用 verify_urls 复验。",
    }


def evaluate_candidate_priority(
    card: dict[str, Any],
    *,
    stats: AgentTrustStats,
    scene_id: str,
    policy: dict[str, Any] | None = None,
    capability_score: float | None = None,
) -> dict[str, Any]:
    """Compute priority flags + composite score for one candidate."""
    pol = policy or get_scene_priority_policy(scene_id)
    aid = str(card.get("agent_id") or "")
    cap_score = float(
        capability_score if capability_score is not None else (card.get("score") or 0.0)
    )
    p1_ready = card.get("p1_ready") is True
    boundary_complete = card.get("boundary_complete") is True
    scene_covered = candidate_covers_scene(card, scene_id) if scene_id else False
    refused = candidate_refuses_scene(card, scene_id) if scene_id else False

    trust_tier = classify_trust_tier(stats, policy=pol)
    bonus, trust_reasons = compute_trust_bonus(stats)
    weight = float(pol.get("trust_weight") or 1.0)
    bonus = round(bonus * weight, 3)

    reasons = list(trust_reasons)
    if boundary_complete is False and card.get("boundary_complete") is False:
        bonus = round(bonus - float(pol.get("boundary_incomplete_penalty") or 1.5), 3)
        reasons.append("boundary_incomplete")
    if p1_ready:
        bonus = round(bonus + float(pol.get("p1_ready_bonus") or 2.0), 3)
        reasons.append("p1_ready")
    elif card.get("p1_ready") is False:
        bonus = round(bonus - float(pol.get("p1_not_ready_penalty") or 2.0), 3)
        reasons.append("p1_not_ready")

    if scene_covered:
        bonus = round(bonus + float(pol.get("scene_coverage_bonus") or 3.0), 3)
        reasons.append(f"scene_covered:{scene_id}")
    elif scene_id:
        reasons.append(f"scene_uncovered:{scene_id}")

    if refused:
        reasons.append(f"scene_refused:{scene_id}")

    ic = (card.get("identity_class") or "").lower() or None
    preferred = {
        str(x).lower()
        for x in (
            pol.get("prefer_identity_classes")
            or pol.get("preferred_identity_classes")
            or []
        )
    }
    identity_preferred = bool(ic and preferred and ic in preferred)
    if identity_preferred:
        bonus = round(bonus + 0.75, 3)
        reasons.append(f"identity:{ic}")

    # Eligibility for hard filters
    eligible = True
    drop_reasons: list[str] = []
    if refused:
        eligible = False
        drop_reasons.append("scene_refused")
    if pol.get("require_p1_ready") and not p1_ready:
        eligible = False
        drop_reasons.append("require_p1_ready")
    if pol.get("require_boundary_complete") and not boundary_complete:
        eligible = False
        drop_reasons.append("require_boundary_complete")
    if pol.get("require_scene_coverage") and not scene_covered:
        eligible = False
        drop_reasons.append("require_scene_coverage")
    if not pol.get("allow_cold_start", True) and trust_tier == "cold":
        # Soft for prefer; hard only when scene forbids cold AND require flags set
        if pol.get("require_p1_ready") or pol.get("high_risk"):
            eligible = False
            drop_reasons.append("cold_start_forbidden")

    # Soft prefer_p1: not a hard drop, but sorts below via p1_ready tier
    final = round(cap_score + bonus, 3)
    evidence = trust_evidence_digest(
        agent_id=aid,
        stats=stats,
        card=card,
        trust_tier=trust_tier,
        scene_id=scene_id,
    )

    return {
        "eligible": eligible,
        "drop_reasons": drop_reasons,
        "p1_ready": p1_ready,
        "boundary_complete": boundary_complete,
        "scene_covered": scene_covered,
        "scene_refused": refused,
        "trust_tier": trust_tier,
        "trust_tier_rank": _TRUST_TIER_RANK.get(trust_tier, 0),
        "identity_preferred": identity_preferred,
        "capability_score": cap_score,
        "trust_bonus": bonus,
        "score": final,
        "priority_reasons": reasons,
        "trust_evidence": evidence,
        "scene_id": scene_id,
        "policy_scene_id": pol.get("scene_id"),
        "high_risk_scene": bool(pol.get("high_risk")),
    }


def priority_sort_key(item: dict[str, Any]) -> tuple:
    """Lexicographic priority order — security & problem-fit before raw score."""
    accept = item.get("accept_risk") or {}
    # Higher verification_tier_rank first; demoted / high non-confirm last
    demote = 1 if accept.get("discovery_demote") else 0
    return (
        0 if item.get("eligible", True) else 1,
        0 if item.get("p1_ready") else 1,
        0 if item.get("boundary_complete") else 1,
        0 if item.get("scene_covered") else 1,
        -int(item.get("trust_tier_rank") or 0),
        demote,
        -int(accept.get("verification_tier_rank") or 3),
        int(accept.get("non_confirm_count") or 0),
        -float(item.get("score") or 0),
        -float((item.get("trust") or {}).get("settled_volume") or 0),
        -float((item.get("trust") or {}).get("reputation_score") or 0),
        item.get("agent_id") or "",
    )


def apply_priority_ranking(
    candidates: list[dict[str, Any]],
    stats_map: dict[str, AgentTrustStats],
    *,
    scene_id: str,
    task_type: str | None = None,
    limit: int | None = None,
    drop_ineligible: bool = True,
    enforce_scene_policy: bool = True,
) -> list[dict[str, Any]]:
    """Enrich + sort candidates by P3 priority order."""
    sid = resolve_scene_id(scene_id=scene_id, task_type=task_type)
    policy = get_scene_priority_policy(sid)
    # When enforce_scene_policy=False, treat require_* as soft (prefer) only
    if not enforce_scene_policy:
        policy = {
            **policy,
            "require_p1_ready": False,
            "require_boundary_complete": False,
            "require_scene_coverage": False,
        }

    enriched: list[dict[str, Any]] = []
    for c in candidates:
        aid = str(c.get("agent_id") or "")
        stats = stats_map.get(aid) or AgentTrustStats(agent_id=aid)
        pri = evaluate_candidate_priority(
            c,
            stats=stats,
            scene_id=sid,
            policy=policy,
            capability_score=float(c.get("capability_score") or c.get("score") or 0),
        )
        if drop_ineligible and not pri["eligible"]:
            continue
        # P6: soft demote sellers with repeated non-confirm / elevated verification
        accept_risk: dict[str, Any] = {}
        try:
            from services.accept_fulfillment import accept_enrichment_for_discovery

            if aid:
                accept_risk = accept_enrichment_for_discovery(aid, sid)
        except Exception:  # noqa: BLE001
            accept_risk = {}

        item = dict(c)
        item.update(
            {
                "capability_score": pri["capability_score"],
                "trust_bonus": pri["trust_bonus"],
                "score": pri["score"],
                "trust": stats.to_dict(),
                "eligible": pri["eligible"],
                "drop_reasons": pri["drop_reasons"],
                "p1_ready": c.get("p1_ready") if "p1_ready" in c else pri["p1_ready"],
                "boundary_complete": (
                    c.get("boundary_complete")
                    if "boundary_complete" in c
                    else pri["boundary_complete"]
                ),
                "scene_covered": pri["scene_covered"],
                "scene_refused": pri["scene_refused"],
                "trust_tier": pri["trust_tier"],
                "trust_tier_rank": pri["trust_tier_rank"],
                "trust_evidence": pri["trust_evidence"],
                "accept_risk": accept_risk,
                "scene_id": sid,
                "match_reasons": list(c.get("match_reasons") or [])
                + list(pri["priority_reasons"]),
                "priority": {
                    "order": [
                        "eligible",
                        "p1_ready",
                        "boundary_complete",
                        "scene_covered",
                        "trust_tier",
                        "accept_risk",
                        "composite_score",
                    ],
                    "p1_ready": pri["p1_ready"],
                    "boundary_complete": pri["boundary_complete"],
                    "scene_covered": pri["scene_covered"],
                    "trust_tier": pri["trust_tier"],
                    "high_risk_scene": pri["high_risk_scene"],
                    "accept_risk": accept_risk,
                },
            }
        )
        # Preserve identity flags for response
        if "identity_class" in c:
            item["identity_class"] = c.get("identity_class")
        if "boundary" in c:
            item["boundary"] = c.get("boundary")
        if "boundary_hash" in c:
            item["boundary_hash"] = c.get("boundary_hash")
        enriched.append(item)

    enriched.sort(key=priority_sort_key)
    if limit is not None:
        return enriched[:limit]
    return enriched


def ranking_metadata(
    *,
    scene_id: str,
    apply_priority: bool,
    enforce_scene_policy: bool,
    require_p1_ready: bool,
    drop_ineligible: bool,
) -> dict[str, Any]:
    cat = load_priority_catalog()
    policy = get_scene_priority_policy(scene_id)
    return {
        "mode": "priority+capability+trust" if apply_priority else "capability",
        "schema_version": PRIORITY_SCHEMA,
        "scene_id": scene_id,
        "priority_order": [x.get("key") for x in (cat.get("priority_order") or [])],
        "signals": [
            "skill_match",
            "scene_covered",
            "p1_ready",
            "boundary_complete",
            "trust_tier",
            "reputation_score",
            "success_rate",
            "settled_volume",
            "dispute_rate",
        ],
        "scene_policy": {
            "require_p1_ready": bool(policy.get("require_p1_ready")) or require_p1_ready,
            "require_boundary_complete": bool(policy.get("require_boundary_complete")),
            "require_scene_coverage": bool(policy.get("require_scene_coverage")),
            "allow_cold_start": bool(policy.get("allow_cold_start", True)),
            "min_settled_count_for_proven": policy.get("min_settled_count_for_proven"),
            "min_success_rate_for_proven": policy.get("min_success_rate_for_proven"),
            "trust_weight": policy.get("trust_weight"),
            "high_risk": bool(policy.get("high_risk")),
            "fallback": bool(policy.get("fallback")),
        },
        "enforce_scene_policy": enforce_scene_policy,
        "drop_ineligible": drop_ineligible,
        "require_p1_ready": require_p1_ready,
        "efficiency_note_zh": (
            "按优先级选出能解决该场景问题、边界清晰、信誉可核验的合作方；"
            "系统评分与结算记录支撑长久合作。"
        ),
    }
