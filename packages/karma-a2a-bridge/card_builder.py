from models import AgentCard, AgentCardSkill, AgentCardSkillInputSchema, AgentCardKarmaExt
from identity import (
    agent_address_from_identity_id,
    assert_agent_id_is_did_projection,
    identity_id_from_agent_address,
)
import config


def build_agent_card(
    agent_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    endpoint: str,
    icon_url: str = "",
    skills: list[dict] | None = None,
    protocols: list[str] | None = None,
    karma_ext: dict | None = None,
) -> AgentCard:
    assert_agent_id_is_did_projection(agent_id)

    skill_objects = []
    if skills:
        for s in skills:
            inp = AgentCardSkillInputSchema(
                type=s.get("input_schema", {}).get("type", "object"),
                properties=s.get("input_schema", {}).get("properties", {}),
                required=s.get("input_schema", {}).get("required", []),
            )
            skill_objects.append(AgentCardSkill(
                id=s["id"],
                name=s.get("name", s["id"]),
                description=s.get("description", ""),
                input_schema=inp,
                output_schema=s.get("output_schema", {"type": "object", "properties": {}}),
            ))

    ext_src = karma_ext or {}
    verifier_registry = ext_src.get("verifier_registry", config.KARMA_VERIFIER_REGISTRY)
    attestation_gateway = ext_src.get("attestation_gateway", config.KARMA_ATTESTATION_GATEWAY)
    did_agent_address = ext_src.get("did_agent_address", config.DID_AGENT_ADDRESS)
    on_chain_did = ext_src.get("on_chain_did", config.ON_CHAIN_DID)

    # If agent_id is a DID projection, backfill did_agent_address
    if not did_agent_address:
        projected = agent_address_from_identity_id(agent_id)
        if projected:
            did_agent_address = projected

    caps = list(capabilities)
    if (verifier_registry or attestation_gateway) and "karma_attestation" not in caps:
        caps.append("karma_attestation")

    ext = AgentCardKarmaExt(
        contract_address=ext_src.get("contract_address", config.KARMA_CONTRACT_ADDRESS),
        verifier_registry=verifier_registry,
        attestation_gateway=attestation_gateway,
        supports_attestation=bool(verifier_registry or attestation_gateway),
        network=ext_src.get("network", config.KARMA_NETWORK),
        settlement_modes=ext_src.get("settlement_modes", config.KARMA_SETTLEMENT_MODES),
        did_agent_address=did_agent_address,
        on_chain_did=on_chain_did,
    )
    return AgentCard(
        name=name,
        description=description,
        agent_id=agent_id,
        icon_url=icon_url,
        capabilities=caps,
        endpoint=endpoint,
        protocols=protocols or ["a2a", "karma"],
        skills=skill_objects,
        karma=ext,
    )


def build_from_karma_agent(agent_data: dict) -> AgentCard:
    """Build card from Karma identity projection (DID SSOT)."""
    did_addr = agent_data.get("did_agent_address") or agent_data.get("bound_wallet_address")
    if did_addr:
        agent_id = identity_id_from_agent_address(did_addr)
    else:
        agent_id = agent_data.get("agent_id") or agent_data.get("identity_id") or "unknown"

    return build_agent_card(
        agent_id=agent_id,
        name=agent_data.get("name", "Unknown Agent"),
        description=agent_data.get("description", ""),
        capabilities=agent_data.get("capabilities", []),
        endpoint=agent_data.get("endpoint_url", ""),
        icon_url=agent_data.get("icon_url", ""),
        karma_ext={
            "did_agent_address": did_addr or "",
            "on_chain_did": agent_data.get("on_chain_did", ""),
            "verifier_registry": agent_data.get("verifier_registry", config.KARMA_VERIFIER_REGISTRY),
            "attestation_gateway": agent_data.get("attestation_gateway", config.KARMA_ATTESTATION_GATEWAY),
            "contract_address": agent_data.get("contract_address", config.KARMA_CONTRACT_ADDRESS),
        },
    )
