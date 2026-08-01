"""A2A-side intent discovery: registry + local merchant catalog + ranking."""
from __future__ import annotations

import copy
import os
import re
from typing import Any

from registry_client import RegistryClient
import config

# Keep rules local so the bridge package stays runnable without installing the full API.
_INTENT_RULES: list[tuple[re.Pattern[str], list[str], list[str], str]] = [
    (re.compile(r"外卖|点餐|订餐|food|pizza|sushi|restaurant|order\s*food|吃饭|美食", re.I),
     ["order_food", "karma_settle"], ["order_food"], "commerce.food"),
    (re.compile(r"机票|航班|飞行|flight|airline|book\s*flight|飞机票", re.I),
     ["book_flight", "karma_settle"], ["book_flight"], "commerce.flight"),
    (re.compile(r"酒店|住宿|hotel|book\s*hotel|民宿", re.I),
     ["book_hotel", "karma_settle"], ["book_hotel"], "commerce.hotel"),
    (re.compile(r"打车|出行|ride|taxi|uber|行程", re.I),
     ["book_ride", "karma_settle"], ["book_ride"], "commerce.ride"),
    (re.compile(r"字幕|caption|视频摘要", re.I),
     ["data_processing", "karma_settle"], ["api.caption"], "api.caption"),
    (re.compile(r"翻译|translat", re.I),
     ["data_processing", "karma_settle"], ["api.translate"], "api.translate"),
    (re.compile(r"标注|label", re.I),
     ["data_processing", "karma_settle"], ["api.labeling"], "api.labeling"),
]


def _demo_catalog() -> list[dict[str, Any]]:
    """Built-in merchants so discovery works without a live external registry."""
    base_karma = {
        "contract_address": config.KARMA_CONTRACT_ADDRESS,
        "verifier_registry": config.KARMA_VERIFIER_REGISTRY,
        "attestation_gateway": config.KARMA_ATTESTATION_GATEWAY,
        "supports_voucher": True,
        "supports_evidence": True,
        "supports_attestation": bool(config.KARMA_ATTESTATION_GATEWAY),
        "accepted_tokens": ["USDC"],
        "network": config.KARMA_NETWORK,
    }
    return [
        {
            "agent_id": "did:karma:0xfood000000000000000000000000000000000001",
            "name": "Karma Food Merchant",
            "description": "Food ordering with Karma settlement",
            "capabilities": ["order_food", "karma_settle", "karma_attestation"],
            "skills": [{"id": "order_food", "name": "Order Food"}],
            "endpoint": os.getenv("A2A_DEMO_FOOD_ENDPOINT", "http://localhost:8081"),
            "karma": {**base_karma},
            "_source": "local_catalog",
        },
        {
            "agent_id": "did:karma:0xflight0000000000000000000000000000000001",
            "name": "Karma Flight Merchant",
            "description": "Flight booking with Karma settlement",
            "capabilities": ["book_flight", "karma_settle"],
            "skills": [{"id": "book_flight", "name": "Book Flight"}],
            "endpoint": os.getenv("A2A_DEMO_FLIGHT_ENDPOINT", "http://localhost:8082"),
            "karma": {**base_karma},
            "_source": "local_catalog",
        },
        {
            "agent_id": "did:karma:0xhotel00000000000000000000000000000000001",
            "name": "Karma Hotel Merchant",
            "description": "Hotel booking with Karma settlement",
            "capabilities": ["book_hotel", "karma_settle"],
            "skills": [{"id": "book_hotel", "name": "Book Hotel"}],
            "endpoint": os.getenv("A2A_DEMO_HOTEL_ENDPOINT", "http://localhost:8083"),
            "karma": {**base_karma},
            "_source": "local_catalog",
        },
    ]


def parse_intent(requirement_text: str, amount: float | None = None) -> dict[str, Any]:
    text = (requirement_text or "").strip()
    if not text:
        raise ValueError("requirement_text is required")
    caps: list[str] = []
    skills: list[str] = []
    task_type = "api.generic"
    for pattern, c, s, tt in _INTENT_RULES:
        if pattern.search(text):
            caps, skills, task_type = list(c), list(s), tt
            break
    if not caps:
        caps, skills = ["karma_settle"], ["generic_task"]
    parsed_amount = amount
    if parsed_amount is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:USDC|u|元|美元)?", text, re.I)
        parsed_amount = float(m.group(1)) if m else None
    return {
        "requirement_text": text,
        "capabilities": caps,
        "skills": skills,
        "task_type": task_type,
        "amount": parsed_amount,
    }


def _score(card: dict[str, Any], intent: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    card_caps = {str(c).lower() for c in (card.get("capabilities") or [])}
    skill_ids = set()
    for s in card.get("skills") or []:
        skill_ids.add(str(s.get("id", "") if isinstance(s, dict) else s).lower())
    for sk in intent.get("skills") or []:
        if sk.lower() in skill_ids or sk.lower() in card_caps:
            score += 3.0
            reasons.append(f"skill:{sk}")
    for cap in intent.get("capabilities") or []:
        if cap.lower() in card_caps:
            score += 1.5
            reasons.append(f"capability:{cap}")
    karma = card.get("karma") or {}
    if "karma_settle" in card_caps or karma.get("supports_voucher"):
        score += 2.0
        reasons.append("karma_settle")
    if karma.get("supports_attestation") or karma.get("attestation_gateway"):
        score += 0.5
        reasons.append("attestation_ready")
    if card.get("endpoint"):
        score += 0.25
        reasons.append("reachable")
    return score, reasons


def discover_for_intent(
    requirement_text: str,
    *,
    amount: float | None = None,
    buyer_identity_id: str | None = None,
    limit: int = 10,
    include_local_catalog: bool = True,
    registry: RegistryClient | None = None,
) -> dict[str, Any]:
    intent = parse_intent(requirement_text, amount=amount)
    cards: list[dict[str, Any]] = []
    if include_local_catalog and os.getenv("A2A_DISABLE_LOCAL_CATALOG", "0") not in {"1", "true"}:
        cards.extend(copy.deepcopy(_demo_catalog()))

    client = registry or RegistryClient(base_url=config.REGISTRY_URL)
    remote = client.search(capabilities=intent["capabilities"], limit=limit * 2)
    for c in remote:
        c["_source"] = "a2a_registry"
        cards.append(c)

    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for card in cards:
        aid = str(card.get("agent_id") or "")
        if not aid or aid in seen:
            continue
        seen.add(aid)
        score, reasons = _score(card, intent)
        if score <= 0:
            continue
        ranked.append({
            "agent_id": aid,
            "name": card.get("name"),
            "description": card.get("description", ""),
            "endpoint": card.get("endpoint") or card.get("endpoint_url"),
            "capabilities": card.get("capabilities") or [],
            "skills": card.get("skills") or [],
            "karma": card.get("karma") or {},
            "score": round(score, 3),
            "match_reasons": reasons,
            "source": card.get("_source", "unknown"),
        })
    ranked.sort(key=lambda x: (-x["score"], x["agent_id"]))
    ranked = ranked[:limit]
    recommended = ranked[0] if ranked else None

    negotiate = None
    if recommended:
        skill = (intent["skills"][0] if intent["skills"] else "generic_task")
        negotiate = {
            "target_agent_id": recommended["agent_id"],
            "endpoint": recommended.get("endpoint"),
            "skill": skill,
            "params_hint": {"requirement": requirement_text},
            "amount": intent.get("amount"),
            "buyer_identity_id": buyer_identity_id,
        }

    return {
        "intent": intent,
        "candidates": ranked,
        "recommended": recommended,
        "negotiate": negotiate,
        "next_steps": [
            "a2a_task_create",
            "a2a_task_confirm_eip712",
            "handoff_to_karma_voucher",
            "evidence_and_settle",
        ] if recommended else ["register_merchants", "broaden_intent"],
        "flow": "intent → discover → negotiate → verify → deliver/settle",
    }
