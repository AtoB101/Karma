"""Intent → capability/skill matching for Karma agent/merchant discovery.

User NL → structured discovery query → rank AgentCards / Karma agents that can fulfill
the job. Settlement/verify/delivery stay on existing Karma rails; this module owns
the *find the right counterparty* step.

P3 priority (scene coverage / P1 / boundary / verifiable trust) is applied after
capability match via ``services.discovery_priority`` / ``apply_trust_rerank``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.human_confirmation_policy import task_type_to_scene_id


# skill_id / capability tags used on AgentCards and /v1/agents.capabilities
_INTENT_RULES: list[tuple[re.Pattern[str], list[str], list[str], str]] = [
    # (pattern, capabilities, skills, task_type)
    (re.compile(r"外卖|点餐|订餐|food|pizza|sushi|restaurant|order\s*food|吃饭|美食", re.I),
     ["order_food", "karma_settle"], ["order_food"], "commerce.food"),
    (re.compile(r"机票|航班|飞行|flight|airline|book\s*flight|飞机票", re.I),
     ["book_flight", "karma_settle"], ["book_flight"], "commerce.flight"),
    (re.compile(r"酒店|住宿|hotel|book\s*hotel|民宿", re.I),
     ["book_hotel", "karma_settle"], ["book_hotel"], "commerce.hotel"),
    (re.compile(r"打车|叫车|网约车|一辆车|出行|ride|taxi|uber|行程", re.I),
     ["book_ride", "karma_settle"], ["book_ride"], "commerce.ride"),
    (re.compile(r"采购|供应|耗材|订货|\bpo\b|procurement|purchase\s*order", re.I),
     ["b2b_procurement", "karma_settle"], ["b2b_procurement"], "commerce.procurement"),
    (re.compile(r"对账|财务|金融|finance|financial|报表服务", re.I),
     ["financial_services", "karma_settle"], ["financial_services"], "finance"),
    (re.compile(r"陪诊|医疗|挂号|healthcare|medical|非诊疗", re.I),
     ["healthcare_medical", "karma_settle"], ["healthcare_medical"], "healthcare"),
    (re.compile(r"代工|制造|manufactur|量产", re.I),
     ["manufacturing", "karma_settle"], ["manufacturing"], "manufacturing"),
    (re.compile(r"房产|看房|real\s*estate|租房中介", re.I),
     ["real_estate_services", "karma_settle"], ["real_estate_services"], "real_estate"),
    (re.compile(r"咨询顾问|consulting|顾问服务", re.I),
     ["consulting_advisory", "karma_settle"], ["consulting_advisory"], "consulting"),
    (re.compile(r"设计|创意|design\s*creative|UI设计", re.I),
     ["design_creative", "karma_settle"], ["design_creative"], "design"),
    (re.compile(r"投放|广告|marketing|marketing\s*ad", re.I),
     ["marketing_advertising", "karma_settle"], ["marketing_advertising"], "marketing"),
    (re.compile(r"培训|课程报名|education|training", re.I),
     ["education_training", "karma_settle"], ["education_training"], "education"),
    (re.compile(r"字幕|caption|视频摘要", re.I),
     ["data_processing", "karma_settle"], ["api.caption"], "api.caption"),
    (re.compile(r"翻译|translat", re.I),
     ["data_processing", "karma_settle"], ["api.translate"], "api.translate"),
    (re.compile(r"标注|label", re.I),
     ["data_processing", "karma_settle"], ["api.labeling"], "api.labeling"),
    (re.compile(r"验证|attest|verifier|审核", re.I),
     ["karma_attestation", "karma_settle"], ["attest_evidence"], "verify.attestation"),
]


@dataclass
class IntentDiscoveryQuery:
    requirement_text: str
    capabilities: list[str]
    skills: list[str]
    task_type: str
    scene_id: str = "api_tool_call"
    amount: float | None = None
    preferred_tokens: list[str] = field(default_factory=lambda: ["USDC"])
    require_karma_settle: bool = True
    require_voucher: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_text": self.requirement_text,
            "capabilities": self.capabilities,
            "skills": self.skills,
            "task_type": self.task_type,
            "scene_id": self.scene_id,
            "amount": self.amount,
            "preferred_tokens": self.preferred_tokens,
            "require_karma_settle": self.require_karma_settle,
            "require_voucher": self.require_voucher,
        }


def parse_intent_for_discovery(
    requirement_text: str,
    *,
    amount: float | None = None,
) -> IntentDiscoveryQuery:
    text = (requirement_text or "").strip()
    if not text:
        raise ValueError("requirement_text is required")

    caps: list[str] = []
    skills: list[str] = []
    task_type = "api.generic"

    for pattern, c, s, tt in _INTENT_RULES:
        if pattern.search(text):
            for x in c:
                if x not in caps:
                    caps.append(x)
            for x in s:
                if x not in skills:
                    skills.append(x)
            task_type = tt
            break

    if not caps:
        caps = ["karma_settle", "agent_discovery"]
        skills = ["generic_task"]
        task_type = "api.generic"
    elif "karma_settle" not in caps:
        caps.append("karma_settle")

    parsed_amount = amount
    if parsed_amount is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:USDC|u|元|美元)?", text, re.I)
        parsed_amount = float(m.group(1)) if m else None

    scene_id = task_type_to_scene_id(task_type)
    return IntentDiscoveryQuery(
        requirement_text=text,
        capabilities=caps,
        skills=skills,
        task_type=task_type,
        scene_id=scene_id,
        amount=parsed_amount,
    )


def score_agent_card(card: dict[str, Any], query: IntentDiscoveryQuery) -> tuple[float, list[str]]:
    """Rank a registry AgentCard / Karma agent dict against the intent query."""
    score = 0.0
    reasons: list[str] = []

    card_caps = {str(c).lower() for c in (card.get("capabilities") or [])}
    skill_ids = set()
    for s in card.get("skills") or []:
        if isinstance(s, dict):
            skill_ids.add(str(s.get("id", "")).lower())
        else:
            skill_ids.add(str(s).lower())

    for sk in query.skills:
        if sk.lower() in skill_ids or sk.lower() in card_caps:
            score += 3.0
            reasons.append(f"skill:{sk}")

    for cap in query.capabilities:
        if cap.lower() in card_caps:
            score += 1.5
            reasons.append(f"capability:{cap}")

    karma = card.get("karma") or {}
    if query.require_karma_settle and (
        "karma_settle" in card_caps or karma.get("supports_voucher") or karma.get("contract_address")
    ):
        score += 2.0
        reasons.append("karma_settle")

    if query.require_voucher and karma.get("supports_voucher", True):
        score += 0.5
        reasons.append("supports_voucher")

    if karma.get("supports_attestation") or karma.get("attestation_gateway"):
        score += 0.5
        reasons.append("attestation_ready")

    tokens = {str(t).upper() for t in (karma.get("accepted_tokens") or ["USDC"])}
    for t in query.preferred_tokens:
        if t.upper() in tokens:
            score += 0.25
            reasons.append(f"token:{t}")
            break

    if card.get("endpoint") or card.get("endpoint_url"):
        score += 0.25
        reasons.append("reachable")

    return score, reasons


def rank_candidates(
    cards: list[dict[str, Any]],
    query: IntentDiscoveryQuery,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for card in cards:
        score, reasons = score_agent_card(card, query)
        if score <= 0:
            continue
        item = {
            "agent_id": card.get("agent_id") or card.get("identity_id"),
            "name": card.get("name"),
            "description": card.get("description", ""),
            "endpoint": card.get("endpoint") or card.get("endpoint_url"),
            "capabilities": card.get("capabilities") or [],
            "skills": card.get("skills") or [],
            "karma": card.get("karma") or {},
            "score": round(score, 3),
            "capability_score": round(score, 3),
            "match_reasons": reasons,
            "source": card.get("_source", "registry"),
            # Preserve P1/P2 signals for priority ranking (must not drop)
            "p1_ready": card.get("p1_ready"),
            "boundary_complete": card.get("boundary_complete"),
            "boundary": card.get("boundary"),
            "boundary_hash": card.get("boundary_hash"),
            "scene_ids": card.get("scene_ids")
            or (card.get("boundary") or {}).get("scene_ids"),
            "identity_class": card.get("identity_class"),
            "owner_identity_id": card.get("owner_identity_id"),
        }
        ranked.append(item)
    ranked.sort(key=lambda x: (-x["score"], x.get("agent_id") or ""))
    return ranked[:limit]


def build_discovery_plan(
    *,
    query: IntentDiscoveryQuery,
    candidates: list[dict[str, Any]],
    buyer_identity_id: str | None = None,
) -> dict[str, Any]:
    recommended = candidates[0] if candidates else None
    next_steps = [
        "review_trust_signals",
        "a2a_negotiate_with_recommended",
        "confirm_task_eip712",
        "create_or_accept_voucher",
        "execute_and_submit_evidence",
        "settle_via_karma",
    ]
    if not recommended:
        next_steps = ["broaden_search", "register_more_merchant_agents"]

    launch_hint = None
    if recommended and buyer_identity_id:
        launch_hint = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": recommended["agent_id"],
            "requirement_text": query.requirement_text,
            "amount": query.amount,
            "task_type": query.task_type,
            "seller_endpoint": recommended.get("endpoint"),
            "a2a_skill": (query.skills[0] if query.skills else None),
        }

    why = None
    if recommended:
        pri = recommended.get("priority") or {}
        why = {
            "scene_id": recommended.get("scene_id") or query.scene_id,
            "p1_ready": recommended.get("p1_ready"),
            "boundary_complete": recommended.get("boundary_complete"),
            "scene_covered": recommended.get("scene_covered"),
            "trust_tier": recommended.get("trust_tier") or pri.get("trust_tier"),
            "score": recommended.get("score"),
            "trust_evidence": recommended.get("trust_evidence"),
            "note_zh": (
                "推荐依据：先能覆盖本场景并界定边界，再看可验证履约记录与系统评分；"
                "安全与问题匹配优先于单纯热度。"
            ),
        }

    return {
        "intent": query.to_dict(),
        "candidates": candidates,
        "recommended": recommended,
        "recommendation_why": why,
        "next_steps": next_steps,
        "trade_launch_hint": launch_hint,
        "flow": "discover → priority match → owner confirm → IF lock → voucher → evidence → settle",
    }
