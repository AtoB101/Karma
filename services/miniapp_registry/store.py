"""MiniApp registries: Business / Agent / Capability / Offer (V1.0 Sprint 3)."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from services import persist_json


_LOCK = Lock()


@dataclass
class Business:
    business_id: str
    owner_identity_id: str
    legal_name: str
    country: str = ""
    verification_level: str = "unverified"  # unverified|basic|verified
    status: str = "active"
    created_at: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentRecord:
    agent_id: str
    owner_identity_id: str
    endpoint: str
    capabilities: list[str] = field(default_factory=list)
    business_id: str | None = None
    status: str = "active"
    reputation_score: float = 50.0
    settled_count: int = 0
    success_rate: float = 0.5
    contribution_score: float = 0.0
    wallet: str | None = None
    builder_address: str | None = None
    created_at: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class Capability:
    capability_id: str
    owner_identity_id: str
    name: str
    category: str
    description: str = ""
    sla: dict = field(default_factory=dict)
    evidence_requirements: list[str] = field(default_factory=list)
    status: str = "active"
    created_at: int = 0


@dataclass
class Offer:
    offer_id: str
    owner_identity_id: str
    agent_id: str
    capability_id: str
    title: str
    price_usdc: str
    category: str
    availability: str = "available"
    sla: dict = field(default_factory=dict)
    requirements: dict = field(default_factory=dict)
    builder_address: str | None = None
    seller_wallet: str | None = None
    status: str = "active"
    created_at: int = 0
    metadata: dict = field(default_factory=dict)


_BUSINESS: dict[str, Business] = {}
_AGENTS: dict[str, AgentRecord] = {}
_CAPS: dict[str, Capability] = {}
_OFFERS: dict[str, Offer] = {}


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _persist() -> None:
    from dataclasses import asdict

    persist_json.save(
        "registry",
        {
            "businesses": [asdict(b) for b in _BUSINESS.values()],
            "agents": [asdict(a) for a in _AGENTS.values()],
            "capabilities": [asdict(c) for c in _CAPS.values()],
            "offers": [asdict(o) for o in _OFFERS.values()],
        },
    )


def _load() -> None:
    data = persist_json.load("registry")
    for d in data.get("businesses", []):
        try:
            b = Business(**d)
        except TypeError:
            continue
        _BUSINESS[b.business_id] = b
    for d in data.get("agents", []):
        try:
            a = AgentRecord(**d)
        except TypeError:
            continue
        _AGENTS[a.agent_id] = a
    for d in data.get("capabilities", []):
        try:
            c = Capability(**d)
        except TypeError:
            continue
        _CAPS[c.capability_id] = c
    for d in data.get("offers", []):
        try:
            o = Offer(**d)
        except TypeError:
            continue
        _OFFERS[o.offer_id] = o


_load()


def register_business(*, owner_identity_id: str, legal_name: str, country: str = "", metadata: dict | None = None) -> Business:
    b = Business(
        business_id=_id("biz"),
        owner_identity_id=owner_identity_id,
        legal_name=legal_name.strip(),
        country=country,
        created_at=int(time.time()),
        metadata=dict(metadata or {}),
    )
    with _LOCK:
        _BUSINESS[b.business_id] = b
        _persist()
    return b


def verify_business(business_id: str, *, level: str = "verified") -> Business:
    with _LOCK:
        b = _BUSINESS[business_id]
        b.verification_level = level
        _persist()
        return b


def register_agent(
    *,
    owner_identity_id: str,
    endpoint: str,
    capabilities: list[str] | None = None,
    business_id: str | None = None,
    wallet: str | None = None,
    builder_address: str | None = None,
    metadata: dict | None = None,
) -> AgentRecord:
    a = AgentRecord(
        agent_id=_id("agt"),
        owner_identity_id=owner_identity_id,
        endpoint=endpoint.strip(),
        capabilities=list(capabilities or []),
        business_id=business_id,
        wallet=(wallet.lower() if wallet else None),
        builder_address=(builder_address.lower() if builder_address else None),
        created_at=int(time.time()),
        metadata=dict(metadata or {}),
    )
    with _LOCK:
        _AGENTS[a.agent_id] = a
        _persist()
    return a


def register_capability(
    *,
    owner_identity_id: str,
    name: str,
    category: str,
    description: str = "",
    sla: dict | None = None,
    evidence_requirements: list[str] | None = None,
) -> Capability:
    c = Capability(
        capability_id=_id("cap"),
        owner_identity_id=owner_identity_id,
        name=name.strip(),
        category=category.strip(),
        description=description,
        sla=dict(sla or {}),
        evidence_requirements=list(evidence_requirements or ["proof_hash"]),
        created_at=int(time.time()),
    )
    with _LOCK:
        _CAPS[c.capability_id] = c
        _persist()
    return c


def publish_offer(
    *,
    owner_identity_id: str,
    agent_id: str,
    capability_id: str,
    title: str,
    price_usdc: str,
    category: str,
    seller_wallet: str | None = None,
    builder_address: str | None = None,
    sla: dict | None = None,
    requirements: dict | None = None,
    metadata: dict | None = None,
) -> Offer:
    if agent_id not in _AGENTS:
        raise KeyError("agent not found")
    if capability_id not in _CAPS:
        raise KeyError("capability not found")
    agent = _AGENTS[agent_id]
    o = Offer(
        offer_id=_id("off"),
        owner_identity_id=owner_identity_id,
        agent_id=agent_id,
        capability_id=capability_id,
        title=title.strip(),
        price_usdc=str(price_usdc),
        category=category.strip(),
        sla=dict(sla or {}),
        requirements=dict(requirements or {}),
        builder_address=(builder_address or agent.builder_address or "").lower() or None,
        seller_wallet=(seller_wallet or agent.wallet or "").lower() or None,
        created_at=int(time.time()),
        metadata=dict(metadata or {}),
    )
    with _LOCK:
        _OFFERS[o.offer_id] = o
        _persist()
    return o


def list_offers(*, category: str | None = None, status: str = "active") -> list[Offer]:
    with _LOCK:
        out = [o for o in _OFFERS.values() if o.status == status]
        if category:
            out = [o for o in out if o.category == category]
        return out


def get_offer(offer_id: str) -> Offer | None:
    with _LOCK:
        return _OFFERS.get(offer_id)


def get_agent(agent_id: str) -> AgentRecord | None:
    with _LOCK:
        return _AGENTS.get(agent_id)


def list_agents(*, owner_identity_id: str | None = None) -> list[AgentRecord]:
    with _LOCK:
        vals = list(_AGENTS.values())
        if owner_identity_id:
            vals = [a for a in vals if a.owner_identity_id == owner_identity_id]
        return vals


def list_businesses(*, owner_identity_id: str | None = None) -> list[Business]:
    with _LOCK:
        vals = list(_BUSINESS.values())
        if owner_identity_id:
            vals = [b for b in vals if b.owner_identity_id == owner_identity_id]
        return vals


def list_capabilities(*, category: str | None = None) -> list[Capability]:
    with _LOCK:
        vals = list(_CAPS.values())
        if category:
            vals = [c for c in vals if c.category == category]
        return vals


def bump_agent_reputation(agent_id: str, *, delta: float, settled: bool = False) -> AgentRecord | None:
    with _LOCK:
        a = _AGENTS.get(agent_id)
        if not a:
            return None
        a.reputation_score = max(0.0, min(200.0, a.reputation_score + delta))
        if settled:
            a.settled_count += 1
            # crude success rate EMA
            a.success_rate = 0.8 * a.success_rate + 0.2 * 1.0
        _persist()
        return a


def offers_as_discovery_catalog() -> list[dict[str, Any]]:
    """Shape offers for intent_discovery.rank_offers."""
    out = []
    with _LOCK:
        for o in _OFFERS.values():
            if o.status != "active":
                continue
            agent = _AGENTS.get(o.agent_id)
            out.append(
                {
                    "offer_id": o.offer_id,
                    "title": o.title,
                    "seller_identity_id": o.owner_identity_id,
                    "seller_wallet": o.seller_wallet,
                    "builder_address": o.builder_address,
                    "agent_id": o.agent_id,
                    "capability_id": o.capability_id,
                    "capabilities": [o.category] + (agent.capabilities if agent else []),
                    "category": o.category,
                    "amount_usdc": o.price_usdc,
                    "reputation_score": (agent.reputation_score if agent else 50),
                    "settled_count": (agent.settled_count if agent else 0),
                    "success_rate": (agent.success_rate if agent else 0.5),
                    "contribution_score": (agent.contribution_score if agent else 0),
                    "created_at": o.created_at,
                    "sla": o.sla,
                }
            )
    return out


def seed_demo_if_empty() -> None:
    """Keep backward-compatible demo catalog when registry empty."""
    with _LOCK:
        if _OFFERS:
            return
    # create a demo merchant stack
    biz = register_business(owner_identity_id="kid_seller_api", legal_name="Demo API Merchant", country="SG")
    verify_business(biz.business_id, level="verified")
    cap = register_capability(
        owner_identity_id="kid_seller_api",
        name="API data fetch",
        category="digital",
        description="Fetch and deliver API data packages",
        evidence_requirements=["proof_hash", "independent_attestation"],
    )
    agt = register_agent(
        owner_identity_id="kid_seller_api",
        endpoint="https://agent.example/api",
        capabilities=["digital"],
        business_id=biz.business_id,
        wallet="0x1111111111111111111111111111111111111111",
        builder_address="0x2222222222222222222222222222222222222222",
    )
    publish_offer(
        owner_identity_id="kid_seller_api",
        agent_id=agt.agent_id,
        capability_id=cap.capability_id,
        title="API data fetch agent",
        price_usdc="100",
        category="digital",
        seller_wallet=agt.wallet,
        builder_address=agt.builder_address,
    )
    # delivery demo
    biz2 = register_business(owner_identity_id="kid_seller_delivery", legal_name="Demo Delivery Co", country="CN")
    cap2 = register_capability(
        owner_identity_id="kid_seller_delivery",
        name="Local delivery",
        category="daily_commerce",
        description="Coordinate local delivery",
    )
    agt2 = register_agent(
        owner_identity_id="kid_seller_delivery",
        endpoint="https://agent.example/delivery",
        capabilities=["daily_commerce"],
        business_id=biz2.business_id,
        wallet="0x3333333333333333333333333333333333333333",
        builder_address="0x4444444444444444444444444444444444444444",
    )
    publish_offer(
        owner_identity_id="kid_seller_delivery",
        agent_id=agt2.agent_id,
        capability_id=cap2.capability_id,
        title="Local delivery coordinator",
        price_usdc="25",
        category="daily_commerce",
        seller_wallet=agt2.wallet,
        builder_address=agt2.builder_address,
    )


def reset_for_tests() -> None:
    with _LOCK:
        _BUSINESS.clear()
        _AGENTS.clear()
        _CAPS.clear()
        _OFFERS.clear()
        persist_json.delete("registry")
