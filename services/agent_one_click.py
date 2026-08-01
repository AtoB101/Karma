"""One-click vertical agent connect — resolve side/vertical → P1 template inputs."""
from __future__ import annotations

from typing import Any, Literal

from services.agent_onboarding_template import (
    OnboardingError,
    get_industry,
    suggest_industries_for_text,
)

Side = Literal["buyer", "seller"]

# Friendly vertical aliases → catalog industry_id (or profile hint)
VERTICAL_ALIASES: dict[str, dict[str, Any]] = {
    "hotel": {"industry_id": "hotel_booking", "profile_hint": "merchant"},
    "hotel_booking": {"industry_id": "hotel_booking", "profile_hint": "merchant"},
    "food": {"industry_id": "food_delivery", "profile_hint": "merchant"},
    "restaurant": {"industry_id": "food_delivery", "profile_hint": "merchant"},
    "food_delivery": {"industry_id": "food_delivery", "profile_hint": "merchant"},
    "ride": {"industry_id": "ride_hailing", "profile_hint": "merchant"},
    "ride_hailing": {"industry_id": "ride_hailing", "profile_hint": "merchant"},
    "flight": {"industry_id": "flight_booking", "profile_hint": "merchant"},
    "flight_booking": {"industry_id": "flight_booking", "profile_hint": "merchant"},
    "ecommerce": {"industry_id": "logistics_delivery", "profile_hint": "merchant"},
    "retail": {"industry_id": "logistics_delivery", "profile_hint": "merchant"},
    "customer_service": {"industry_id": "api_tool_call", "profile_hint": "merchant"},
    "cs": {"industry_id": "api_tool_call", "profile_hint": "merchant"},
    "support": {"industry_id": "api_tool_call", "profile_hint": "merchant"},
    "enterprise": {"industry_id": "b2b_procurement", "profile_hint": "enterprise"},
    "b2b": {"industry_id": "b2b_procurement", "profile_hint": "enterprise"},
    "b2b_procurement": {"industry_id": "b2b_procurement", "profile_hint": "enterprise"},
    "api": {"industry_id": "data_api_billing", "profile_hint": "merchant"},
    "data_api": {"industry_id": "data_api_billing", "profile_hint": "merchant"},
    "data_api_billing": {"industry_id": "data_api_billing", "profile_hint": "merchant"},
    "user": {"industry_id": None, "profile_hint": "user"},
    "buyer": {"industry_id": None, "profile_hint": "user"},
}


def list_vertical_aliases() -> list[dict[str, Any]]:
    out = []
    for alias, body in VERTICAL_ALIASES.items():
        out.append(
            {
                "vertical": alias,
                "industry_id": body.get("industry_id"),
                "profile_hint": body.get("profile_hint"),
            }
        )
    return sorted(out, key=lambda r: r["vertical"])


def resolve_one_click(
    *,
    side: str,
    vertical: str | None = None,
    self_description: str | None = None,
    display_name: str | None = None,
    answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map buyer/seller + vertical alias → profile_id + answers for connect-from-template."""
    side_n = (side or "").strip().lower()
    if side_n not in {"buyer", "seller"}:
        raise OnboardingError("side must be buyer|seller")

    vert = (vertical or "").strip().lower()
    alias = VERTICAL_ALIASES.get(vert) if vert else None
    industry_id = alias.get("industry_id") if alias else None
    profile_hint = alias.get("profile_hint") if alias else None

    if industry_id is None and vert and not alias:
        # Treat as raw industry_id if present in catalog
        try:
            get_industry(vert)
            industry_id = vert
            profile_hint = "merchant"
        except OnboardingError:
            if self_description:
                suggestions = suggest_industries_for_text(self_description, limit=1)
                if suggestions:
                    industry_id = suggestions[0]["industry_id"]
                    profile_hint = "merchant"
            if industry_id is None:
                raise OnboardingError(
                    f"unknown vertical '{vertical}' — use hotel|food|ecommerce|"
                    "customer_service|enterprise|ride|flight|api or a catalog industry_id"
                ) from None

    if side_n == "buyer":
        profile_id = "user"
    elif profile_hint == "enterprise" or vert in {"enterprise", "b2b"}:
        profile_id = "enterprise"
    else:
        profile_id = "merchant"

    ans = dict(answers or {})
    name = (display_name or ans.get("display_name") or "").strip()
    if not name:
        if profile_id == "user":
            name = "Karma Buyer Agent"
        else:
            label = industry_id or vertical or "merchant"
            name = f"Karma {label} Agent"
    ans["display_name"] = name

    if profile_id == "user":
        ans.setdefault("preferred_currency", "USDC")
    else:
        if industry_id:
            ans.setdefault("industry_ids", [industry_id])
        elif self_description:
            suggestions = suggest_industries_for_text(self_description, limit=3)
            ans.setdefault(
                "industry_ids", [s["industry_id"] for s in suggestions] or ["api_tool_call"]
            )
        else:
            ans.setdefault("industry_ids", ["api_tool_call"])
        if self_description:
            ans.setdefault("capability_summary", self_description.strip()[:500])
        else:
            ans.setdefault(
                "capability_summary",
                f"Vertical {industry_id or 'merchant'} agent auto-connected via Karma one-click",
            )
        ans.setdefault("service_targets", ["consumer", "agent"])
        ans.setdefault("service_area", {"mode": "hybrid", "regions": ["global"]})
        if profile_id == "enterprise":
            ans.setdefault("enterprise_type", "other")
            ans.setdefault("trade_side", ["sell"])
            ans.setdefault(
                "compliance_flags",
                {"no_fund_custody": True, "non_clinical_only": True},
            )

    scene_ids = list(ans.get("industry_ids") or [])
    if profile_id == "user" and industry_id:
        scene_ids = [industry_id]

    return {
        "side": side_n,
        "vertical": vert or None,
        "profile_id": profile_id,
        "industry_id": industry_id,
        "scene_ids": scene_ids,
        "answers": ans,
        "display_name": name,
    }


def build_next_steps(*, agent_id: str, side: str, scene_ids: list[str]) -> list[str]:
    steps = [
        f"Export KARMA_AGENT_ID={agent_id} and X-Karma-Api-Key from credentials.api_key",
        f"GET /v1/agents/{agent_id}/p1-status until p1_ready=true",
    ]
    if side == "buyer":
        steps.append(
            "POST /v1/orchestration/fulfill-intent with requirement_text + buyer_identity_id"
        )
        steps.append("POST /v1/discovery/intent to find vertical sellers")
    else:
        scene = scene_ids[0] if scene_ids else "api_tool_call"
        steps.append(
            f"Keep boundary/scene coverage for {scene}; counterparties verify via /p1-status"
        )
        steps.append("Optional: POST /runtime/create-key (wallet sign) for voucher/receipt path")
    steps.append("Optional MCP: set KARMA_API_KEY and use karma_discover_for_intent / fulfill")
    return steps
