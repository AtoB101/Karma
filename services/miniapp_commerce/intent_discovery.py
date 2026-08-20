"""Chat intent extraction (MVP heuristic) + discovery offers."""
from __future__ import annotations

import re
from typing import Any

from services.discovery_priority import resolve_scene_id
from services.agent_trust import AgentTrustStats, compute_trust_bonus


def parse_chat_intent(text: str, *, default_amount: str | None = None) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty intent")

    amount = default_amount
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:USDC|usdc|\$)", raw)
    if m:
        amount = m.group(1)

    scene = "digital"
    low = raw.lower()
    if any(k in low for k in ("外卖", "配送", "delivery", "food")):
        scene = "daily_commerce"
    elif any(k in low for k in ("酒店", "hotel", "教育", "education")):
        scene = "professional"
    elif any(k in low for k in ("医疗", "金融", "medical", "finance", "bank")):
        scene = "high_risk"
    elif any(k in low for k in ("api", "数据", "data", "saas")):
        scene = "digital"
    elif any(k in low for k in ("采购", "制造", "b2b", "invoice")):
        scene = "b2b"

    scene_id = resolve_scene_id(scene_id=scene, task_type=None)
    return {
        "raw_text": raw,
        "scene_id": scene_id,
        "amount_usdc": amount or "100",
        "category": scene_id,
        "keywords": re.findall(r"[\w\u4e00-\u9fff]+", raw)[:12],
    }


def rank_offers(
    intent: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank capability/offers; may weight by trust/contribution later."""
    scene = intent.get("scene_id")
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in catalog:
        caps = item.get("capabilities") or item.get("scenes") or []
        if scene and caps and scene not in caps and item.get("category") != scene:
            continue
        stats = AgentTrustStats(
            agent_id=str(item.get("seller_identity_id") or item.get("offer_id") or "unknown"),
            reputation_score=float(item.get("reputation_score") or 50),
            settled_count=int(item.get("settled_count") or 0),
            settled_volume=float(item.get("settled_volume") or 0),
            success_rate=float(item.get("success_rate") or 0.5),
            dispute_rate=float(item.get("dispute_rate") or 0.0),
            cold_start=int(item.get("settled_count") or 0) == 0,
        )
        bonus, _reasons = compute_trust_bonus(stats)
        contrib = float(item.get("contribution_score") or 0)
        score = float(bonus) + min(contrib / 1000.0, 5.0)
        if item.get("builder_address"):
            score += 0.5
        out = dict(item)
        out["_rank_score"] = round(score, 4)
        scored.append((score, out))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored]


# Dev seed catalog (replace with registry in Sprint 3)
DEFAULT_OFFER_CATALOG: list[dict[str, Any]] = [
    {
        "offer_id": "off_api_data_1",
        "title": "API data fetch agent",
        "seller_identity_id": "kid_seller_api",
        "seller_wallet": "0x1111111111111111111111111111111111111111",
        "builder_address": "0x2222222222222222222222222222222222222222",
        "capabilities": ["digital"],
        "category": "digital",
        "amount_usdc": "100",
        "reputation_score": 72,
        "settled_count": 12,
        "success_rate": 0.92,
        "contribution_score": 800,
    },
    {
        "offer_id": "off_delivery_1",
        "title": "Local delivery coordinator",
        "seller_identity_id": "kid_seller_delivery",
        "seller_wallet": "0x3333333333333333333333333333333333333333",
        "builder_address": "0x4444444444444444444444444444444444444444",
        "capabilities": ["daily_commerce"],
        "category": "daily_commerce",
        "amount_usdc": "25",
        "reputation_score": 65,
        "settled_count": 40,
        "success_rate": 0.88,
        "contribution_score": 300,
    },
]
