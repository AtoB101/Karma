"""MiniApp Business / Agent / Capability / Offer registry routes."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.miniapp_registry import store as registry
from services.telegram import SessionError, get_session

router = APIRouter()


def _require_session(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing session")
    try:
        return get_session(authorization.split(" ", 1)[1].strip())
    except SessionError as exc:
        raise HTTPException(401, str(exc)) from exc


class BusinessBody(BaseModel):
    legal_name: str
    country: str = ""
    metadata: dict = Field(default_factory=dict)


class AgentBody(BaseModel):
    endpoint: str
    capabilities: list[str] = Field(default_factory=list)
    business_id: str | None = None
    wallet: str | None = None
    builder_address: str | None = None
    metadata: dict = Field(default_factory=dict)


class CapabilityBody(BaseModel):
    name: str
    category: str
    description: str = ""
    sla: dict = Field(default_factory=dict)
    evidence_requirements: list[str] | None = None


class OfferBody(BaseModel):
    agent_id: str
    capability_id: str
    title: str
    price_usdc: str
    category: str
    seller_wallet: str | None = None
    builder_address: str | None = None
    sla: dict = Field(default_factory=dict)
    requirements: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


@router.post("/registry/businesses")
def create_business(body: BusinessBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity first")
    b = registry.register_business(
        owner_identity_id=sess.identity_id,
        legal_name=body.legal_name,
        country=body.country,
        metadata=body.metadata,
    )
    return {
        "business_id": b.business_id,
        "legal_name": b.legal_name,
        "country": b.country,
        "verification_level": b.verification_level,
        "owner_identity_id": b.owner_identity_id,
    }


@router.post("/registry/businesses/{business_id}/verify")
def verify_business(business_id: str, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    try:
        b = registry.verify_business(business_id)
    except KeyError as exc:
        raise HTTPException(404, "business not found") from exc
    return {"business_id": b.business_id, "verification_level": b.verification_level}


@router.get("/registry/businesses")
def list_businesses(authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    items = registry.list_businesses(owner_identity_id=sess.identity_id)
    return {
        "businesses": [
            {
                "business_id": b.business_id,
                "legal_name": b.legal_name,
                "verification_level": b.verification_level,
                "country": b.country,
            }
            for b in items
        ]
    }


@router.post("/registry/agents")
def create_agent(body: AgentBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity first")
    a = registry.register_agent(
        owner_identity_id=sess.identity_id,
        endpoint=body.endpoint,
        capabilities=body.capabilities,
        business_id=body.business_id,
        wallet=body.wallet or sess.wallet,
        builder_address=body.builder_address,
        metadata=body.metadata,
    )
    return {
        "agent_id": a.agent_id,
        "endpoint": a.endpoint,
        "capabilities": a.capabilities,
        "wallet": a.wallet,
        "builder_address": a.builder_address,
        "reputation_score": a.reputation_score,
    }


@router.get("/registry/agents")
def list_agents(authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    items = registry.list_agents(owner_identity_id=sess.identity_id)
    return {
        "agents": [
            {
                "agent_id": a.agent_id,
                "endpoint": a.endpoint,
                "capabilities": a.capabilities,
                "reputation_score": a.reputation_score,
                "settled_count": a.settled_count,
                "builder_address": a.builder_address,
            }
            for a in items
        ]
    }


@router.post("/registry/capabilities")
def create_capability(body: CapabilityBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity first")
    c = registry.register_capability(
        owner_identity_id=sess.identity_id,
        name=body.name,
        category=body.category,
        description=body.description,
        sla=body.sla,
        evidence_requirements=body.evidence_requirements,
    )
    return {
        "capability_id": c.capability_id,
        "name": c.name,
        "category": c.category,
        "evidence_requirements": c.evidence_requirements,
    }


@router.get("/registry/capabilities")
def list_capabilities(category: str | None = None, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    items = registry.list_capabilities(category=category)
    return {
        "capabilities": [
            {
                "capability_id": c.capability_id,
                "name": c.name,
                "category": c.category,
                "description": c.description,
            }
            for c in items
        ]
    }


@router.post("/registry/offers")
def create_offer(body: OfferBody, authorization: str | None = Header(default=None)):
    sess = _require_session(authorization)
    if not sess.identity_id:
        raise HTTPException(400, "bind identity first")
    try:
        o = registry.publish_offer(
            owner_identity_id=sess.identity_id,
            agent_id=body.agent_id,
            capability_id=body.capability_id,
            title=body.title,
            price_usdc=body.price_usdc,
            category=body.category,
            seller_wallet=body.seller_wallet,
            builder_address=body.builder_address,
            sla=body.sla,
            requirements=body.requirements,
            metadata=body.metadata,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "offer_id": o.offer_id,
        "title": o.title,
        "price_usdc": o.price_usdc,
        "category": o.category,
        "agent_id": o.agent_id,
        "capability_id": o.capability_id,
        "builder_address": o.builder_address,
        "seller_wallet": o.seller_wallet,
    }


@router.get("/registry/offers")
def list_registry_offers(category: str | None = None, authorization: str | None = Header(default=None)):
    _require_session(authorization)
    registry.seed_demo_if_empty()
    items = registry.list_offers(category=category)
    return {
        "offers": [
            {
                "offer_id": o.offer_id,
                "title": o.title,
                "price_usdc": o.price_usdc,
                "category": o.category,
                "agent_id": o.agent_id,
                "builder_address": o.builder_address,
                "seller_wallet": o.seller_wallet,
            }
            for o in items
        ]
    }
